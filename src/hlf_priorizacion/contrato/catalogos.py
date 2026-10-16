"""Enumerados cerrados y catálogos del contrato ``contrato-v1.0.0`` (docs/datos.md).

Un valor fuera de estos catálogos manda el perfil a cuarentena (R1.1).
"""

from __future__ import annotations

from typing import Final, Literal, get_args

VERSION_CONTRATO: Final = "contrato-v1.0.0"

PrioridadInicial = Literal["alta", "media", "baja"]
EstadoSolicitud = Literal["en_espera", "atendido", "fallecido", "citado", "egresado"]
EstadoALaFecha = Literal["en_espera", "atendido", "fallecido", "citado", "egresado", "desconocido_a_la_fecha"]
TipoEvento = Literal["visita_urgencia", "hospitalizacion", "examen_alterado", "cambio_farmaco", "control_aps"]
Severidad = Literal["leve", "moderada", "grave"]
TipoMedicion = Literal[
    "presion_sistolica",
    "presion_diastolica",
    "glicemia",
    "HbA1c",
    "saturacion_o2",
    "peak_flow",
    "escala_dolor_eva",
    "PHQ9",
]
EstadoCita = Literal["asistio", "no_asistio", "reprogramo", "cancelo"]

TIPOS_EVENTO: Final[tuple[str, ...]] = get_args(TipoEvento)
TIPOS_MEDICION: Final[tuple[TipoMedicion, ...]] = get_args(TipoMedicion)
ESTADOS_CITA: Final[tuple[str, ...]] = get_args(EstadoCita)

# Combinaciones tipo_evento / subtipo -> severidad (cada subtipo tiene siempre la misma severidad).
COMBINACIONES_EVENTO: Final[dict[tuple[str, str], str]] = {
    ("visita_urgencia", "triage ESI 2"): "grave",
    ("visita_urgencia", "descompensación grave"): "grave",
    ("visita_urgencia", "descompensación"): "moderada",
    ("hospitalizacion", "ingreso hospitalario"): "grave",
    ("hospitalizacion", "ingreso UCI"): "grave",
    ("examen_alterado", "resultado alterado"): "moderada",
    ("cambio_farmaco", "aumento dosis"): "moderada",
    ("cambio_farmaco", "reducción dosis"): "leve",
    ("control_aps", "buena respuesta"): "leve",
    ("control_aps", "estabilización"): "leve",
    ("control_aps", "control crónico"): "leve",
    ("control_aps", "control de rutina"): "leve",
    ("control_aps", "control"): "leve",
}

# Unidad obligatoria por tipo de medición.
UNIDAD_POR_TIPO: Final[dict[str, str]] = {
    "presion_sistolica": "mmHg",
    "presion_diastolica": "mmHg",
    "glicemia": "mg/dL",
    "HbA1c": "%",
    "saturacion_o2": "%",
    "peak_flow": "L/min",
    "escala_dolor_eva": "puntos",
    "PHQ9": "puntos",
}

# Especialidades del dataset (docs/datos.md). Las usa la validación del documento de relaciones clínicas (R11).
# El contrato no restringe `especialidad`: un valor nuevo no manda el perfil a cuarentena.
ESPECIALIDADES_CATALOGO: Final = frozenset(
    {
        "Broncopulmonar",
        "Cardiología",
        "Endocrinología",
        "Gastroenterología",
        "Neurología",
        "Salud Mental",
        "Traumatología",
    }
)

# Especialidades donde aparece cada medición (docs/datos.md). Se usa para la contradicción (R5.9).
ESPECIALIDADES_POR_MEDICION: Final[dict[str, frozenset[str]]] = {
    "presion_sistolica": frozenset({"Cardiología"}),
    "presion_diastolica": frozenset({"Cardiología"}),
    "HbA1c": frozenset({"Endocrinología"}),
    "glicemia": frozenset({"Endocrinología", "Gastroenterología"}),
    "saturacion_o2": frozenset({"Broncopulmonar"}),
    "peak_flow": frozenset({"Broncopulmonar"}),
    "escala_dolor_eva": frozenset({"Traumatología", "Neurología"}),
    "PHQ9": frozenset({"Salud Mental"}),
}

# Eventos graves para aceleración (R5.4), bandera de 30 días (R6.3) y desenlace de cohortes (R9).
TIPOS_EVENTO_GRAVE: Final = frozenset({"visita_urgencia", "hospitalizacion"})

# Subtipos de mejoría sujetos a contradicción (R5.9) y a la evidencia de mejoría (R6.5).
SUBTIPOS_MEJORIA: Final = frozenset({"buena respuesta", "reducción dosis", "estabilización"})

PATRON_ID_PACIENTE: Final = r"^PAC-[A-Z0-9]+-\d{5}$"
PATRON_ID_SOLICITUD: Final = r"^IC-[A-Z0-9]+-\d{5}$"
PATRON_ID_EVENTO: Final = r"^EV-\d{6}$"
PATRON_ID_CITA: Final = r"^CT-\d{6}$"
PATRON_ID_BOX: Final = r"^BOX-\d{2}$"
PATRON_CIE10: Final = r"^[A-Z]\d{2}(\.[0-9A-Z]{1,4})?$"


def es_evento_grave(tipo_evento: str, severidad: str) -> bool:
    """Urgencia u hospitalización con severidad grave."""
    return tipo_evento in TIPOS_EVENTO_GRAVE and severidad == "grave"
