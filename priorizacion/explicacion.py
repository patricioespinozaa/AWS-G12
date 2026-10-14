"""Explicación de la propuesta en lenguaje clínico.

Por defecto usa una plantilla determinista. Si LLM_PROVEEDOR=bedrock, Claude en Amazon Bedrock
redacta el texto a partir de los mismos factores; la salida se valida (solo puede citar referencias,
fechas y niveles presentes en los factores) y, si no pasa, se usa la plantilla.
El LLM nunca calcula ni cambia la prioridad.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import config
from .motor import CATEGORIAS_CLINICAS, Resultado, _num
from .reglas import BASE_PRIORIDAD, UMBRAL_ALTA, UMBRAL_MEDIA


@dataclass
class Explicacion:
    texto: str
    fuente: str            # plantilla | bedrock
    aviso: str | None = None


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
    if r.nivel_propuesto not in texto.lower():
        return "no menciona el nivel propuesto"
    return None


def explicacion_llm(r: Resultado) -> Explicacion:
    """Redacta con Claude en Amazon Bedrock. Requiere `pip install "anthropic[bedrock]"` y credenciales AWS."""
    plantilla = explicacion_plantilla(r)
    if config.LLM_PROVEEDOR != "bedrock":
        return Explicacion(plantilla, "plantilla", "IA generativa desactivada (LLM_PROVEEDOR no es 'bedrock').")
    try:
        from anthropic import AnthropicBedrockMantle
    except ImportError:
        return Explicacion(plantilla, "plantilla", 'Falta el paquete: pip install "anthropic[bedrock]".')
    try:
        cliente = AnthropicBedrockMantle(aws_region=config.AWS_REGION)
        respuesta = cliente.messages.create(
            model=config.BEDROCK_MODEL_ID,
            max_tokens=8000,
            system=SISTEMA,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": json.dumps(_carga_llm(r), ensure_ascii=False)}],
        )
    except Exception as e:  # sin credenciales, región sin el modelo, red, etc.
        return Explicacion(plantilla, "plantilla", f"No se pudo llamar a Bedrock ({type(e).__name__}: {e}).")
    if respuesta.stop_reason == "refusal":
        return Explicacion(plantilla, "plantilla", "El modelo declinó la solicitud; se usa la plantilla.")
    texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
    if motivo := validar_texto_llm(texto, r):
        return Explicacion(plantilla, "plantilla", f"Texto del LLM descartado: {motivo}.")
    return Explicacion(texto, "bedrock")
