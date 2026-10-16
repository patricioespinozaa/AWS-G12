"""Validación de un perfil contra el contrato y decisión de cuarentena (R1)."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hlf_priorizacion.contrato.catalogos import PATRON_ID_PACIENTE, PATRON_ID_SOLICITUD, VERSION_CONTRATO
from hlf_priorizacion.contrato.esquema import PerfilCrudo, PerfilValido

_RE_PACIENTE = re.compile(PATRON_ID_PACIENTE)
_RE_SOLICITUD = re.compile(PATRON_ID_SOLICITUD)


class ResultadoValidacion(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    ok: bool
    id_paciente: str | None
    ids_solicitud: list[str] = Field(default_factory=list)
    perfil: PerfilValido | None = None
    motivos: list[str] = Field(default_factory=list)
    version_contrato: str = VERSION_CONTRATO


def _motivos(error: ValidationError) -> list[str]:
    """Motivos legibles sin copiar los valores de entrada (no se registran datos clínicos)."""
    motivos = []
    for e in error.errors(include_input=False, include_url=False):
        ubicacion = ".".join(str(p) for p in e["loc"]) or "perfil"
        motivos.append(f"{ubicacion}: {e['msg']}")
    return sorted(set(motivos))


def _id_paciente(raw: Any) -> str | None:
    if isinstance(raw, dict):
        valor = raw.get("id_paciente")
        if isinstance(valor, str) and _RE_PACIENTE.match(valor):
            return valor
    return None


def _ids_solicitud(raw: Any) -> list[str]:
    """IDs de solicitud recuperables de un perfil inválido (para la alerta ``perfil_en_cuarentena``)."""
    if not isinstance(raw, dict):
        return []
    lista = raw.get("lista_espera")
    items = [lista] if isinstance(lista, dict) else lista if isinstance(lista, list) else []
    ids = []
    for item in items:
        if isinstance(item, dict):
            valor = item.get("id_solicitud")
            if isinstance(valor, str) and _RE_SOLICITUD.match(valor):
                ids.append(valor)
    return ids


def validar_perfil(raw: Any) -> ResultadoValidacion:
    """``ok`` con el ``PerfilValido`` o cuarentena con sus motivos. Descarta ``nombre_fantasia``."""
    id_paciente = _id_paciente(raw)
    ids_solicitud = _ids_solicitud(raw)
    if not isinstance(raw, dict):
        return ResultadoValidacion(ok=False, id_paciente=None, motivos=["perfil: no es un objeto JSON"])
    try:
        texto = json.dumps(raw, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return ResultadoValidacion(
            ok=False,
            id_paciente=id_paciente,
            ids_solicitud=ids_solicitud,
            motivos=["perfil: contiene valores no serializables o no numéricos"],
        )
    try:
        crudo = PerfilCrudo.model_validate_json(texto)
        perfil = PerfilValido.desde_crudo(crudo)
    except ValidationError as error:
        return ResultadoValidacion(
            ok=False, id_paciente=id_paciente, ids_solicitud=ids_solicitud, motivos=_motivos(error)
        )
    return ResultadoValidacion(
        ok=True,
        id_paciente=perfil.id_paciente,
        ids_solicitud=[s.id_solicitud for s in perfil.lista_espera],
        perfil=perfil,
    )
