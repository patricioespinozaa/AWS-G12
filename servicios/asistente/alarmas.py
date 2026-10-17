"""Síntomas de alarma (F0010): detección determinista, antes del modelo.

Un síntoma de alarma nunca recibe consejo clínico: se deriva a una persona con urgencia inmediata, queda como
canal.mensaje_paciente `sintoma_alarma` pendiente de revisión, y el paciente recibe un mensaje fijo de seguridad.
La lista es deliberadamente amplia: un falso positivo cuesta una llamada; un falso negativo, mucho más.
"""
from __future__ import annotations

import re
import unicodedata

MENSAJE_SEGURIDAD = (
    "Lo que describes puede ser importante. Si es grave o empeora, llama ahora al SAMU (131) o acude al servicio de "
    "urgencia más cercano. Ya avisé al equipo del hospital para que te contacten. No puedo darte indicaciones médicas "
    "por este medio.")

PATRONES = [
    r"dolor (fuerte |intenso |muy fuerte )?(en el |de |del )?pecho", r"me duele (mucho )?el pecho", r"opresion (en el |de )?pecho",
    r"(falta|dificultad) (de|para) (aire|respirar)", r"no (puedo|logro) respirar", r"me ahogo", r"ahogo",
    r"desmay", r"perdi (el )?conocimiento", r"convuls",
    r"sangr\w* (mucho|abundante)", r"vomit\w* sangre", r"tos con sangre",
    r"no (puedo )?mover (el|la|un|una) (brazo|pierna|lado)", r"cara (chueca|torcida)", r"no puedo hablar",
    r"(quiero|pienso en|ganas de) (morir|matarme|suicid)", r"suicid", r"hacerme dano", r"quitarme la vida",
    r"dolor (de cabeza )?(muy fuerte|insoportable|el peor)", r"confusion", r"glicemia (muy )?(alta|baja) (y|con) (mareo|sudor)",
]
_PATRON = re.compile("|".join(f"(?:{p})" for p in PATRONES))


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin_tildes)


def es_alarma(texto: str) -> bool:
    return bool(_PATRON.search(_normalizar(texto)))
