"""Tubería completa para las propiedades: perfil crudo -> contrato -> ingesta -> contexto -> DQ -> motor."""

from __future__ import annotations

from datetime import date
from typing import Any

from estrategias import FECHA_EXTRACCION
from hlf_priorizacion.calidad.auditoria import auditar
from hlf_priorizacion.contrato.validacion import validar_perfil
from hlf_priorizacion.ingesta.normalizacion import PerfilNormalizado, normalizar_perfil
from hlf_priorizacion.modelos import ContextoPaciente, Evaluacion, HallazgoDQ
from hlf_priorizacion.motor.evaluar import evaluar
from hlf_priorizacion.motor.parametros import cargar_parametros
from hlf_priorizacion.repositorio.contexto import contexto_a_fecha

PARAMS = cargar_parametros()


def normalizar(raw: dict[str, Any]) -> PerfilNormalizado:
    res = validar_perfil(raw)
    assert res.ok and res.perfil is not None, res.motivos
    return normalizar_perfil(res.perfil).perfil


def contexto(raw: dict[str, Any], corte: date) -> ContextoPaciente:
    perfil = normalizar(raw)
    return contexto_a_fecha(perfil, perfil.solicitudes[0].id_solicitud, corte, FECHA_EXTRACCION)


def evaluar_crudo(raw: dict[str, Any], corte: date) -> tuple[ContextoPaciente, list[HallazgoDQ], Evaluacion]:
    ctx = contexto(raw, corte)
    dq = auditar(ctx)
    return ctx, dq, evaluar(ctx, dq, PARAMS)
