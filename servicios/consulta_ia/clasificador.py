"""Clasificación de la pregunta (F0009): texto, conteo o rechazada. Una sola ruta por pregunta.

Primero un filtro determinista: lo que pide modificar datos o identificar personas se rechaza sin llamar al modelo.
Después Claude (Bedrock, con respuesta estructurada) decide la ruta y extrae los filtros (paciente, especialidad).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..comun import bedrock

VERSION_PROMPT = "clasif-v1"
ESPECIALIDADES = ["Broncopulmonar", "Cardiología", "Endocrinología", "Gastroenterología", "Neurología", "Salud Mental",
                  "Traumatología"]
# Órdenes de escritura (imperativo o "puedes/podrías …") y comandos SQL. No basta una palabra suelta: "¿cuántos
# tuvieron una modificación de tratamiento?" es una pregunta válida
_VERBOS = r"(borr|elimin|actualiz|modific|insert|cambi|sub|baj|reasign|marc|asign|anot|guard|cre)"
_ESCRITURA = re.compile(
    rf"(?i)(^\s*¿?\s*{_VERBOS}(a|e|ar)\b|\b(puedes|podr[ií]as|quiero|necesito)\s+{_VERBOS}(ar|er|ir)\b"
    r"|\b(drop|truncate|alter)\s+table\b|\bdelete\s+from\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b)")
_IDENTIDAD = re.compile(r"(?i)\b(rut|run|nombres?|tel[eé]fonos?|direcci[oó]n(es)?|correos?|e-?mails?)\b")
_ID_PACIENTE = re.compile(r"(?i)\b(?:PAC-HLF-)?0*(\d{1,5})\b")

SISTEMA = """Clasificas preguntas de la Administradora de la lista de espera de especialidad de un hospital público. La herramienta solo informa: no modifica datos ni decide prioridades.

Rutas:
- "conteo": la respuesta es un número, un agregado o una tabla corta (cuántos, cuántas, promedio, porcentaje, máximo, mínimo, ranking, por especialidad, por comuna, por mes…). Se responde con SQL exacto.
- "texto": la respuesta es una descripción o un resumen (evolución de un paciente, por qué subió su prioridad, qué eventos tuvo, cómo está una especialidad o un box). Se responde con los documentos de la base de conocimiento.
- "rechazada": pide modificar datos o prioridades, que el sistema diagnostique o proponga un diagnóstico nuevo, una indicación de tratamiento, un pronóstico, datos que identifiquen a una persona (nombre, RUT, teléfono), o algo ajeno a la lista de espera.

Consultar lo que ya está registrado (el diagnóstico CIE-10 de la interconsulta, los eventos, las mediciones, las citas) está permitido: es "texto" o "conteo" según la pregunta.

Filtros (solo si la pregunta los menciona explícitamente):
- id_paciente: el número del paciente, solo los dígitos (por ejemplo "28" para "paciente 00028").
- especialidad: una de {especialidades}."""

HERRAMIENTA = {
    "name": "clasificar_pregunta",
    "description": "Clasifica la pregunta en una ruta y extrae los filtros.",
    "schema": {"type": "object", "properties": {
        "ruta": {"type": "string", "enum": ["texto", "conteo", "rechazada"]},
        "motivo": {"type": "string", "description": "Por qué esa ruta, en una frase"},
        "id_paciente": {"type": "string", "description": "Dígitos del paciente mencionado, o vacío"},
        "especialidad": {"type": "string", "enum": [""] + ESPECIALIDADES},
    }, "required": ["ruta", "motivo"]},
}


@dataclass
class Clasificacion:
    ruta: str
    motivo: str
    id_paciente: str | None = None
    especialidad: str | None = None
    medida: dict = field(default_factory=dict)


def normalizar_paciente(valor: str | None) -> str | None:
    if not valor:
        return None
    m = _ID_PACIENTE.search(valor)
    return f"PAC-HLF-{int(m.group(1)):05d}" if m else None


def filtro_previo(pregunta: str) -> Clasificacion | None:
    """Rechazos que no necesitan al modelo."""
    if _ESCRITURA.search(pregunta):
        return Clasificacion("rechazada", "Pide modificar datos o prioridades: la consulta solo lee.")
    if _IDENTIDAD.search(pregunta):
        return Clasificacion("rechazada", "Pide datos que identifican a una persona: no se entregan.")
    return None


def clasificar(pregunta: str) -> Clasificacion:
    if previo := filtro_previo(pregunta):
        return previo
    sistema = SISTEMA.format(especialidades=", ".join(ESPECIALIDADES))
    salida, medida = bedrock.converse_herramienta(sistema, pregunta, HERRAMIENTA, max_tokens=300)
    ruta = salida.get("ruta") if salida.get("ruta") in ("texto", "conteo", "rechazada") else "rechazada"
    especialidad = salida.get("especialidad") if salida.get("especialidad") in ESPECIALIDADES else None
    return Clasificacion(ruta, (salida.get("motivo") or "").strip(), normalizar_paciente(salida.get("id_paciente")),
                         especialidad, medida)
