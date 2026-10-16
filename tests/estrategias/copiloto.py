"""Estrategias y ayudantes de U2: paquetes, respuestas del modelo y pares de fechas.

Reutilizan los perfiles de ``estrategias`` (U1). Las respuestas del modelo cubren: válidas, con IDs
inventados, con cifras distintas, malformadas, con un atributo no disponible (C6.5 regla 1) y con
inasistencias junto a un verbo de bajada (C6.5 regla 2). Ninguna prueba llama a Bedrock:
el cliente falso responde a partir del propio bloque ``<datos_clinicos>`` de la petición.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from hypothesis import strategies as st

from estrategias import FECHA_EXTRACCION, perfil_y_corte
from estrategias.tuberia import PARAMS, evaluar_crudo
from hlf_priorizacion.copiloto.cliente import PeticionModelo, RespuestaModelo, respuesta_falsa
from hlf_priorizacion.copiloto.modelos import PaqueteBarrido
from hlf_priorizacion.copiloto.paquete import armar_paquete
from hlf_priorizacion.copiloto.validacion import riesgo_de_paquete
from hlf_priorizacion.lote import Configuracion, ejecutar_lote
from hlf_priorizacion.modelos import AnalisisIA, ResultadoCohorte
from hlf_priorizacion.motor.parametros import ParametrosReglas

TIPOS_RESPUESTA = (
    "valida", "ids_inventados", "cifras_distintas", "malformada", "atributo_no_disponible", "revision_equidad"
)
RESUMEN_FALSO = "Resumen sintético del cliente falso: TEXTO-DEL-MODELO-NO-DEBE-IR-A-LOGS."
_RE_DATOS = re.compile(r"<datos_clinicos>\n(.*)\n</datos_clinicos>", re.DOTALL)


# --------------------------------------------------------------------------- fechas


@st.composite
def pares_fechas(draw: st.DrawFn) -> tuple[date, date, date]:
    """``(desde, hasta, extraccion)`` mezclando pares válidos e inválidos (iguales, invertidos, largos, futuros)."""
    extraccion = draw(st.dates(date(2025, 1, 1), date(2027, 12, 31)))
    desde = draw(st.dates(extraccion - timedelta(days=120), extraccion + timedelta(days=5)))
    delta = draw(st.one_of(st.integers(-5, 40), st.sampled_from([-1, 0, 1, 29, 30, 31, 32])))
    return desde, desde + timedelta(days=delta), extraccion


# --------------------------------------------------------------------------- paquetes


@st.composite
def cohortes(draw: st.DrawFn) -> ResultadoCohorte | None:
    if draw(st.booleans()):
        return None
    n = draw(st.integers(0, 80))
    k = draw(st.integers(0, n))
    p = k / n if n else None
    return ResultadoCohorte(
        clave="I20|40-59",
        nivel_relajacion=draw(st.integers(0, 2)),
        n=n,
        k=k,
        p=p,
        ic95_inf=0.0 if n else None,
        ic95_sup=min(1.0, (p or 0.0) + 0.2) if n else None,
        advertencia_muestra_pequena=n < 10,
    )


@st.composite
def perfil_y_paquete(draw: st.DrawFn) -> tuple[dict[str, Any], PaqueteBarrido]:
    raw, corte = draw(perfil_y_corte())
    ctx, dq, ev = evaluar_crudo(raw, corte)
    return raw, armar_paquete(ctx, ev, hallazgos_dq=dq, cohorte=draw(cohortes()))


def paquetes() -> st.SearchStrategy[PaqueteBarrido]:
    return perfil_y_paquete().map(lambda t: t[1])


# --------------------------------------------------------------------------- respuestas del modelo


def datos_de_usuario(usuario: str) -> dict[str, Any]:
    m = _RE_DATOS.search(usuario)
    assert m is not None, "la petición no trae el bloque <datos_clinicos>"
    datos: dict[str, Any] = json.loads(m.group(1))
    return datos


_CAMPOS_RIESGO = ("n", "k", "p", "ic95_inf", "ic95_sup", "advertencia_muestra_pequena", "advertencia_sesgo_acceso")


def _riesgo(cohorte: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if cohorte is None else {k: cohorte[k] for k in _CAMPOS_RIESGO}


def entrada_desde_datos(datos: dict[str, Any], id_solicitud: str) -> dict[str, Any]:
    """Respuesta válida y determinista construida solo con lo que trae el paquete."""
    ev = datos["evaluacion_motor"]
    ids = sorted({i for f in ev["factores"] for i in f["ids_registro"]})
    nivel = "critica" if ev["banderas"] else (ev["nivel_propuesto"] or "media")
    hallazgos: list[dict[str, Any]] = []
    if ids:
        hallazgos.append({"texto": "Factores del motor revisados.", "tipo": "documentado", "ids_registro": ids[:3]})
    hallazgos.append({"texto": "Sin otras señales en los registros.", "tipo": "inferido", "ids_registro": []})
    linea = [
        {"fecha": e["fecha_evento"], "descripcion": e["subtipo"], "ids_registro": [e["id_evento"]]}
        for e in datos["eventos"][:3]
    ]
    return {
        "id_solicitud": id_solicitud,
        "resumen": RESUMEN_FALSO,
        "relacion_con_derivacion": {"tipo": "incierta", "texto": "Relación por confirmar con el especialista."},
        "linea_tiempo_relevante": linea,
        "hallazgos": hallazgos,
        "riesgo_poblacional": _riesgo(datos["riesgo_poblacional_cohorte"]),
        "prioridad_sugerida": nivel,
        "acuerdo_con_motor": {"acuerdo": True, "motivo_discrepancia": None},
        "justificacion": "Coincide con la propuesta del motor.",
        "confianza": "media",
        "acciones_sugeridas": [],
        "propuesta_agenda": None,
        "datos_faltantes": [] if datos["riesgo_poblacional_cohorte"] else ["sin cohorte disponible"],
        "escalas_sustitutas": [],
        "inconsistencias_datos": [],
        "nota_preconsulta": "Nota breve para el especialista.",
    }


def responder_eco(peticion: PeticionModelo) -> RespuestaModelo:
    """Cliente falso determinista: responde válido a partir de los datos de la petición."""
    entrada = entrada_desde_datos(datos_de_usuario(peticion.usuario), peticion.id_solicitud)
    return respuesta_falsa(entrada, request_id=f"req-{peticion.id_solicitud}-{peticion.intento}")


def entrada_valida(p: PaqueteBarrido) -> dict[str, Any]:
    from hlf_priorizacion.copiloto.paquete import datos_paquete

    return entrada_desde_datos(json.loads(json.dumps(datos_paquete(p))), p.id_solicitud)


@st.composite
def respuestas(draw: st.DrawFn, p: PaqueteBarrido) -> tuple[str, dict[str, Any] | None]:
    """``(tipo, entrada_herramienta)`` de uno de los ``TIPOS_RESPUESTA``."""
    tipo = draw(st.sampled_from(TIPOS_RESPUESTA))
    e = copy.deepcopy(entrada_valida(p))
    if tipo == "valida":
        e["confianza"] = draw(st.sampled_from(["alta", "media", "baja"]))
    elif tipo == "ids_inventados":
        reales = sorted(p.ids_paquete())
        mezcla = draw(st.lists(st.sampled_from(reales), max_size=2)) if reales else []
        e["hallazgos"].append(
            {"texto": "Cita inventada.", "tipo": "documentado", "ids_registro": [*mezcla, "EV-INVENTADO-1"]}
        )
        if draw(st.booleans()):  # D-1: documentado sin ningún ID
            e["hallazgos"].append({"texto": "Sin cita.", "tipo": "documentado", "ids_registro": []})
        e["linea_tiempo_relevante"].append(
            {"fecha": p.fecha_corte.isoformat(), "descripcion": "x", "ids_registro": ["MED-inventada"]}
        )
        e["inconsistencias_datos"].append({"texto": "inventada", "ids_registro": ["CT-INVENTADA"]})
    elif tipo == "cifras_distintas":
        n = draw(st.integers(1, 500))
        e["riesgo_poblacional"] = {
            "n": n,
            "k": draw(st.integers(0, n)),
            "p": draw(st.floats(0, 1)),
            "ic95_inf": 0.01,
            "ic95_sup": 0.99,
            "advertencia_muestra_pequena": draw(st.booleans()),
            "advertencia_sesgo_acceso": draw(st.booleans()),
        }
    elif tipo == "malformada":
        variante = draw(st.integers(0, 5))
        if variante == 0:
            return tipo, None
        if variante == 1:
            del e["resumen"]
        elif variante == 2:
            e["prioridad_sugerida"] = "urgentisima"
        elif variante == 3:
            e["resumen"] = "x" * 1300
        elif variante == 4:
            e["campo_extra"] = 1
        else:
            e["id_solicitud"] = "IC-OTRA-99999"
    elif tipo == "atributo_no_disponible":  # C6.5 regla 1: se rechaza
        e[draw(st.sampled_from(CAMPOS_TEXTO))] = draw(st.sampled_from(FRASES_ATRIBUTO_NO_DISPONIBLE))
    else:  # revision_equidad (C6.5 regla 2): se guarda marcado
        e[draw(st.sampled_from(CAMPOS_TEXTO))] = draw(st.sampled_from(FRASES_REVISION_EQUIDAD))
    return tipo, e


# --------------------------------------------------------------------------- C6.5: frases generadas

CAMPOS_TEXTO = ("justificacion", "resumen", "nota_preconsulta")
FRASES_ATRIBUTO_NO_DISPONIBLE = (
    "Se sugiere bajar la prioridad por la comuna de residencia.",
    "Por su previsión FONASA conviene postergar la atención.",
    "Dado el nivel socioeconómico, se puede reducir la urgencia.",
    "La comuna no se usa para decidir.",
)
FRASES_REVISION_EQUIDAD = (
    "Tiene inasistencias previas y se recomienda disminuir la prioridad.",
    "Las inasistencias no se usan para bajar la prioridad.",
)

# Términos de la regla 1 tal como podría escribirlos el modelo (las tildes y mayúsculas se varían aparte).
ATRIBUTOS_NO_DISPONIBLES = ("comuna", "comunas", "comunal", "comunales", "previsión", "prevision", "previsiones",
                            "previsional", "previsionales", "FONASA", "Isapre", "ISAPRES", "nivel socioeconómico",
                            "niveles socioeconómicos", "socioeconómico", "nivel socio-económico", "socio económico",
                            "socio-económica", "NSE", "N.S.E.", "N. S. E.", "N S E", "GSE", "socio - económico",
                            "socio\u2014económico", "socio/económica", "comuna_residencia", "prevision_salud",
                            "intercomunal", "previsionalmente", "imprevisión", "Fondo Nacional de Salud",
                            "socioeconómicamente", "FONASAs", "NSEs", "socioeconomía", "F.O.N.A.S.A.",
                            "I.S.A.P.R.E.")
INASISTENCIAS = ("inasistencia", "inasistencias", "no asistió", "no asistio", "no-show", "no show", "no_asistio",
                 "ausencias a citas", "ausencia a la cita", "citas fallidas", "cita fallida")
FORMAS_BAJADA = ("bajar", "bajarla", "bajarlo", "baja", "bajan", "bajó", "bajamos", "bajando", "bajaría",
                 "rebajar", "rebaja", "rebajarla", "postergar", "postergarlo", "postergue", "posterguemos",
                 "postergación", "reducir", "reduce", "redujo", "reduzca", "reducción", "disminuir", "disminuye",
                 "disminuyó", "disminución", "degradar", "degrada", "degradación", "relegar", "relegue", "relegada")
NEGACIONES = ("no", "sin", "sino", "salvo", "excepto", "nunca", "ni", "jamás", "tampoco", "no solo")
# Palabras de relleno: ninguna es atributo, inasistencia ni verbo de bajada.
RELLENO = ("el", "la", "paciente", "prioridad", "por", "su", "clínica", "se", "sugiere", "conviene", "motivo",
           "urgente", "hay", "control", "especialista", "aquí", "debe", "corresponde", "considerar", "usar",
           "cita", "atención", "que", "para", "como", "datos", "registro", "CT-000005", "(EV-000004)", ",")
_TILDES = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú"}


@st.composite
def variar_escritura(draw: st.DrawFn, texto: str) -> str:
    """Mismo término con mayúsculas y tildes al azar: la regla compara sin mayúsculas ni tildes."""
    sin_tilde = {v: k for k, v in _TILDES.items()}
    letras: list[str] = []
    for original in texto:
        c = sin_tilde.get(original.lower(), original.lower())
        if c in _TILDES and draw(st.booleans()):
            c = _TILDES[c]
        letras.append(c.upper() if draw(st.booleans()) else c)
    return "".join(letras)


@st.composite
def _palabras_alrededor(draw: st.DrawFn) -> list[str]:
    return draw(st.lists(st.one_of(st.sampled_from(RELLENO), st.sampled_from(NEGACIONES)), max_size=8))


@st.composite
def frase_con_atributo_no_disponible(draw: st.DrawFn) -> str:
    """Una oración con un atributo de la regla 1, entre palabras y negaciones al azar: debe rechazarse."""
    termino = draw(variar_escritura(draw(st.sampled_from(ATRIBUTOS_NO_DISPONIBLES))))
    antes, despues = draw(_palabras_alrededor()), draw(_palabras_alrededor())
    if draw(st.booleans()):  # a veces, también una bajada: no cambia nada
        despues.append(draw(st.sampled_from(FORMAS_BAJADA)))
    return " ".join([*antes, termino, *despues]) + "."


@st.composite
def frase_inasistencia_con_bajada(draw: st.DrawFn) -> str:
    """Una oración con inasistencias y una forma de bajada, con negaciones al azar: debe marcarse."""
    inasistencia = draw(variar_escritura(draw(st.sampled_from(INASISTENCIAS))))
    bajada = draw(variar_escritura(draw(st.sampled_from(FORMAS_BAJADA))))
    partes = [inasistencia, *draw(_palabras_alrededor()), bajada]
    if draw(st.booleans()):
        partes.reverse()
    return " ".join([*draw(_palabras_alrededor()), *partes, *draw(_palabras_alrededor())]) + "."


def analisis_con_justificacion(frase: str) -> AnalisisIA:
    """Un ``AnalisisIA`` válido cuya ``justificacion`` es ``frase`` (para probar C6.5 de forma aislada)."""
    base = entrada_desde_datos(
        {"evaluacion_motor": {"factores": [], "banderas": [], "nivel_propuesto": "alta"}, "eventos": [],
         "riesgo_poblacional_cohorte": None},
        "IC-1",
    )
    base["justificacion"] = frase
    base["metadatos"] = {"model_id": "m", "version_prompt": "v", "request_id": None, "fecha_corte": "2026-07-19",
                         "id_ejecucion": "e"}
    return AnalisisIA.model_validate_json(json.dumps(base))


# --------------------------------------------------------------------------- lote en carpetas temporales


def correr_lote(datos: Path, salidas: Path, cortes: list[date], fecha_extraccion: date = FECHA_EXTRACCION) -> None:
    correr_lote_con(datos, salidas, cortes, PARAMS, fecha_extraccion)


def correr_lote_con(
    datos: Path, salidas: Path, cortes: list[date], params: ParametrosReglas, fecha_extraccion: date = FECHA_EXTRACCION
) -> None:
    """Como ``correr_lote`` con una versión de reglas explícita (p. ej. reglas-v0.1.0)."""
    for corte in cortes:
        cfg = Configuracion(corte, fecha_extraccion, datos, salidas, None)
        ejecutar_lote(cfg, params, f"lote-prueba-{corte.isoformat()}")


def escribir_dataset(datos: Path, perfiles: list[dict[str, Any]]) -> Path:
    datos.mkdir(parents=True, exist_ok=True)
    (datos / "perfiles.json").write_text(json.dumps(perfiles, ensure_ascii=False), encoding="utf-8")
    return datos


__all__ = [
    "RESUMEN_FALSO",
    "TIPOS_RESPUESTA",
    "analisis_con_justificacion",
    "correr_lote",
    "correr_lote_con",
    "datos_de_usuario",
    "entrada_desde_datos",
    "entrada_valida",
    "escribir_dataset",
    "frase_con_atributo_no_disponible",
    "frase_inasistencia_con_bajada",
    "paquetes",
    "pares_fechas",
    "perfil_y_paquete",
    "responder_eco",
    "respuestas",
    "riesgo_de_paquete",
]
