"""Explicación de la propuesta en lenguaje clínico.

Por defecto usa una plantilla determinista. Si LLM_PROVEEDOR=bedrock, un modelo de Amazon Bedrock (Claude)
redacta el texto a partir de los mismos factores; la salida se valida (solo puede citar referencias,
fechas y niveles presentes en los factores) y, si no pasa, se usa la plantilla.
El LLM nunca calcula ni cambia la prioridad.

Solo IA del ecosistema AWS (F0008): el modelo se invoca con el SDK de AWS (boto3, bedrock-runtime, API Converse) y
las credenciales IAM de la tarea. No hay SDKs ni claves de otros proveedores (lo verifica tests/test_solo_aws.py).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from . import config
from .motor import CATEGORIAS_CLINICAS, Resultado, _num
from .reglas import BASE_PRIORIDAD, UMBRAL_ALTA, UMBRAL_MEDIA


log = logging.getLogger("hlf.explicacion")
# Sube si cambia el prompt o la carga: invalida los textos guardados en caché
VERSION_PROMPT = "p1"


@dataclass
class Explicacion:
    texto: str
    fuente: str            # plantilla | bedrock
    aviso: str | None = None
    modelo: str | None = None
    desde_cache: bool = False


class CacheExplicaciones(Protocol):
    """Lo implementa el registro (SQLite o RDS): textos ya aceptados, por huella de los datos y modelo."""
    def explicacion_guardada(self, huella: str, modelo: str, version_prompt: str) -> str | None: ...
    def guardar_explicacion(self, huella: str, modelo: str, version_prompt: str, id_solicitud: str,
                            texto: str) -> None: ...


def _ref_corta(ref: str) -> str:
    return ref.split(" … ")[-1] if " … " in ref else ref


def explicacion_plantilla(r: Resultado) -> str:
    if r.excluido:
        return f"La solicitud {r.id_solicitud} está fuera de la lista activa ({r.motivo_exclusion})."
    movimiento = {
        "sube": f"sube de {r.prioridad_vigente} a {r.nivel_propuesto}",
        "baja": f"baja de {r.prioridad_vigente} a {r.nivel_propuesto}",
        "igual": f"se mantiene en {r.nivel_propuesto}",
    }[r.cambio]
    partes = [f"Propuesta al {r.fecha_corte.isoformat()}: prioridad {r.nivel_propuesto.upper()} ({movimiento}). "
              f"Puntaje de nivel {_num(r.puntaje_nivel)} (umbrales: media ≥ {_num(UMBRAL_MEDIA)}, alta ≥ "
              f"{_num(UMBRAL_ALTA)}); parte de {_num(BASE_PRIORIDAD[r.prioridad_inicial])} por la prioridad inicial "
              f"{r.prioridad_inicial}."]
    if r.alerta:
        partes.append("Alerta: " + "; ".join(r.motivos_alerta) + ".")
    if r.resguardo_aplicado:
        partes.append(f"El puntaje por sí solo indicaría {r.nivel_calculado}, pero no hay evidencia de mejora, "
                      f"así que se mantiene la prioridad vigente ({r.prioridad_vigente}).")
    clinicos = [f for f in r.factores if f.categoria in CATEGORIAS_CLINICAS and abs(f.aporte) >= 0.05]
    if clinicos:
        top = sorted(clinicos, key=lambda f: -abs(f.aporte))[:4]
        partes.append("Señales durante la espera: " + "; ".join(
            f"{'+' if f.aporte >= 0 else '−'}{_num(abs(f.aporte))} {f.descripcion}"
            f" [{_ref_corta(f.ref_fuente)}{', ' + f.fecha_dato.isoformat() if f.fecha_dato else ''}]" for f in top) + ".")
        if len(clinicos) > 4:
            partes.append(f"Hay {len(clinicos) - 4} señales menores más en el detalle de factores.")
    else:
        partes.append("No hay señales clínicas registradas durante la espera.")
    for f in r.factores:
        if f.categoria == "ajuste":
            partes.append(f"{f.descripcion} ({'+' if f.aporte >= 0 else '−'}{_num(abs(f.aporte))}).")
    contexto = [f for f in r.factores if f.categoria == "contexto"]
    if contexto:
        def corta(d: str) -> str:
            d = d.split(" (")[0].split(";")[0]
            return d[:1].lower() + d[1:]
        partes.append(f"Orden dentro del nivel (puntaje de orden {_num(r.puntaje)}): " + ", ".join(
            f"{corta(f.descripcion)} +{_num(f.aporte)}" for f in contexto) + ".")
    partes.append(f"Reglas {r.version_reglas}. La decisión final es del equipo clínico.")
    return " ".join(partes)


SISTEMA = """Redactas, en español de Chile, explicaciones breves para el equipo clínico que gestiona una lista de espera de especialidad en un hospital público.

Recibes una propuesta de prioridad que ya calculó un sistema de reglas, junto con los factores que la explican, cada uno con su aporte al puntaje, su fecha y su referencia de origen (ref).

Cómo escribir:
- Usa solo la información entregada. No agregues diagnósticos, causas, pronósticos, recomendaciones de tratamiento ni datos que no estén en los factores.
- No cambies el nivel propuesto, el puntaje ni los aportes.
- Cada vez que menciones un hecho clínico, pon su referencia entre corchetes tal como viene en ref (por ejemplo [EV-000004]).
- Escribe de 3 a 5 oraciones en prosa, sin listas ni títulos. Empieza por lo que más pesó.
- Termina con una oración que recuerde que la decisión es del equipo clínico."""

_PATRON_ID = re.compile(r"\b(?:EV|CT|EXT|MSG)-\d+\b|\bIC-HLF-\d+\b")
_PATRON_FECHA = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")
# Fechas en prosa o con barras ("6 de agosto", "6 de agosto de 2026", "06/08/2026"): también deben estar en los factores
_PATRON_FECHA_TEXTO = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(MESES) + r"|setiembre)(?:\s+(?:de|del)\s+(\d{4}))?\b",
                                 re.IGNORECASE)
_PATRON_FECHA_BARRA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def limpiar_formato(texto: str) -> str:
    """Quita el markdown que algunos modelos agregan aunque se les pide prosa: títulos y negritas."""
    lineas = [linea for linea in texto.splitlines() if not linea.lstrip().startswith("#")]
    texto = "\n".join(lineas).replace("**", "").replace("__", "")
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def _fechas_en_texto(texto: str) -> set[tuple[int, int, int | None]]:
    """(día, mes, año o None) de cada fecha escrita en prosa o con barras."""
    fechas = set()
    for d, mes, anio in _PATRON_FECHA_TEXTO.findall(texto):
        m = 9 if mes.lower() == "setiembre" else MESES.index(mes.lower()) + 1
        fechas.add((int(d), m, int(anio) if anio else None))
    for d, m, anio in _PATRON_FECHA_BARRA.findall(texto):
        fechas.add((int(d), int(m), int(anio)))
    return fechas


def _carga_llm(r: Resultado) -> dict:
    return {
        "fecha_corte": r.fecha_corte.isoformat(),
        "prioridad_inicial": r.prioridad_inicial,
        "prioridad_vigente": r.prioridad_vigente,
        "prioridad_propuesta": r.nivel_propuesto,
        "cambio": r.cambio,
        "puntaje_de_nivel": r.puntaje_nivel,
        "umbrales": {"media": UMBRAL_MEDIA, "alta": UMBRAL_ALTA},
        "puntaje_de_orden_dentro_del_nivel": r.puntaje,
        "alerta": r.motivos_alerta,
        "resguardo_sin_evidencia_de_mejora": r.resguardo_aplicado,
        "factores": [{"descripcion": f.descripcion, "aporte": round(f.aporte, 2), "categoria": f.categoria,
                      "fecha": f.fecha_dato.isoformat() if f.fecha_dato else None, "ref": _ref_corta(f.ref_fuente)}
                     for f in r.factores],
    }


def validar_texto_llm(texto: str, r: Resultado) -> str | None:
    """Devuelve el motivo de rechazo, o None si el texto solo usa datos presentes en los factores."""
    permitidos = " ".join([f.ref_fuente for f in r.factores] + [r.id_solicitud, r.id_paciente])
    ids_validos = set(_PATRON_ID.findall(permitidos))
    if extra := set(_PATRON_ID.findall(texto)) - ids_validos:
        return f"cita referencias que no están en los factores: {', '.join(sorted(extra))}"
    fechas_validas = {f.fecha_dato.isoformat() for f in r.factores if f.fecha_dato} | {r.fecha_corte.isoformat()}
    fechas_validas |= set(_PATRON_FECHA.findall(permitidos))
    if extra := set(_PATRON_FECHA.findall(texto)) - fechas_validas:
        return f"menciona fechas que no están en los factores: {', '.join(sorted(extra))}"
    conocidas = [tuple(map(int, f.split("-"))) for f in fechas_validas]          # (año, mes, día)
    for d, m, anio in sorted(_fechas_en_texto(texto), key=str):
        if not any(cd == d and cm == m and (anio is None or ca == anio) for ca, cm, cd in conocidas):
            escrita = f"{d} de {MESES[m - 1]}" + (f" de {anio}" if anio else "")
            return f"menciona una fecha que no está en los factores: {escrita}"
    if r.nivel_propuesto not in texto.lower():
        return "no menciona el nivel propuesto"
    return None


_cliente_bedrock = None
_cliente_lock = threading.Lock()


def _cliente():
    """Cliente de bedrock-runtime (boto3), con tiempo de espera acotado: CloudFront corta a los 60 s."""
    global _cliente_bedrock
    with _cliente_lock:
        if _cliente_bedrock is None:
            import boto3
            from botocore.config import Config
            _cliente_bedrock = boto3.client(
                "bedrock-runtime", region_name=config.BEDROCK_REGION,
                config=Config(connect_timeout=5, read_timeout=40, retries={"max_attempts": 2, "mode": "standard"}))
        return _cliente_bedrock


def _registrar(r: Resultado, resultado: str, motivo: str | None = None, uso: dict | None = None,
               ms: float | None = None, huella: str | None = None) -> None:
    """Una línea JSON por pedido (CloudWatch Logs): costo, latencia y tasa de descarte. Sin datos clínicos."""
    uso = uso or {}
    log.info(json.dumps({
        "evento": "explicacion_ia", "id_solicitud": r.id_solicitud, "fecha_corte": r.fecha_corte.isoformat(),
        "huella": huella, "modelo": config.BEDROCK_MODEL_ID, "guardrail": config.BEDROCK_GUARDRAIL_ID or None,
        "resultado": resultado, "motivo": motivo, "tokens_entrada": uso.get("inputTokens"),
        "tokens_salida": uso.get("outputTokens"), "latencia_ms": round(ms) if ms is not None else None,
    }, ensure_ascii=False))


def explicacion_llm(r: Resultado, huella: str | None = None, cache: CacheExplicaciones | None = None) -> Explicacion:
    """Redacta con un modelo de Amazon Bedrock (API Converse de boto3). Ante cualquier problema, la plantilla.

    Con `huella` (huella_datos de la propuesta) y `cache`, un texto ya aceptado para los mismos datos y el mismo
    modelo se devuelve sin volver a llamar a Bedrock.
    """
    plantilla = explicacion_plantilla(r)
    if config.LLM_PROVEEDOR != "bedrock":
        return Explicacion(plantilla, "plantilla", "IA generativa desactivada (LLM_PROVEEDOR no es 'bedrock').")
    modelo = config.BEDROCK_MODEL_ID
    if huella and cache is not None:
        try:
            if guardado := cache.explicacion_guardada(huella, modelo, VERSION_PROMPT):
                _registrar(r, "cache", huella=huella)
                return Explicacion(guardado, "bedrock", modelo=modelo, desde_cache=True)
        except Exception as e:  # noqa: BLE001 — la caché es opcional
            log.warning("No se pudo leer la caché de explicaciones: %s", e)

    pedido = {
        "modelId": modelo,
        "system": [{"text": SISTEMA}],
        "messages": [{"role": "user", "content": [{"text": json.dumps(_carga_llm(r), ensure_ascii=False)}]}],
        "inferenceConfig": {"maxTokens": config.BEDROCK_MAX_TOKENS},
    }
    if config.BEDROCK_GUARDRAIL_ID:
        pedido["guardrailConfig"] = {"guardrailIdentifier": config.BEDROCK_GUARDRAIL_ID,
                                     "guardrailVersion": config.BEDROCK_GUARDRAIL_VERSION, "trace": "disabled"}
    t0 = time.perf_counter()
    try:
        respuesta = _cliente().converse(**pedido)
    except Exception as e:  # sin permisos, modelo no habilitado, red, tiempo de espera…
        _registrar(r, "error", f"{type(e).__name__}", ms=(time.perf_counter() - t0) * 1000, huella=huella)
        return Explicacion(plantilla, "plantilla", f"No se pudo llamar a Bedrock ({type(e).__name__}); se usa la plantilla.")
    ms = (time.perf_counter() - t0) * 1000
    uso, parada = respuesta.get("usage", {}), respuesta.get("stopReason")
    if parada == "guardrail_intervened":
        _registrar(r, "guardrail", "el guardrail bloqueó el texto", uso, ms, huella)
        return Explicacion(plantilla, "plantilla", "El guardrail de Bedrock bloqueó el texto; se usa la plantilla.")
    if parada == "max_tokens":
        _registrar(r, "descartado", "texto incompleto (max_tokens)", uso, ms, huella)
        return Explicacion(plantilla, "plantilla", "El texto del modelo quedó incompleto; se usa la plantilla.")
    bloques = respuesta.get("output", {}).get("message", {}).get("content", [])
    texto = limpiar_formato("".join(b.get("text", "") for b in bloques))
    if not texto:
        _registrar(r, "descartado", "respuesta vacía", uso, ms, huella)
        return Explicacion(plantilla, "plantilla", "El modelo no devolvió texto; se usa la plantilla.")
    if motivo := validar_texto_llm(texto, r):
        _registrar(r, "descartado", motivo, uso, ms, huella)
        return Explicacion(plantilla, "plantilla", f"Texto del LLM descartado: {motivo}.")
    _registrar(r, "aceptado", uso=uso, ms=ms, huella=huella)
    if huella and cache is not None:
        try:
            cache.guardar_explicacion(huella, modelo, VERSION_PROMPT, r.id_solicitud, texto)
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo guardar la explicación en caché: %s", e)
    return Explicacion(texto, "bedrock", modelo=modelo)
