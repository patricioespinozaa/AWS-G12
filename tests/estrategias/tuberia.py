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
from hlf_priorizacion.motor.parametros import ParametrosReglas, cargar_parametros, ruta_version
from hlf_priorizacion.repositorio.contexto import contexto_a_fecha

PARAMS = cargar_parametros()  # versión por defecto (reglas-v0.2.0)
PARAMS_V010 = cargar_parametros(ruta_version("reglas-v0.1.0"))


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


def evaluar_todas(
    raw: dict[str, Any], corte: date, params: ParametrosReglas = PARAMS
) -> dict[str, tuple[ContextoPaciente, list[HallazgoDQ], Evaluacion]]:
    """Evalúa cada SIC del perfil ya ingresada al corte (como el lote)."""
    perfil = normalizar(raw)
    salida = {}
    for s in perfil.solicitudes:
        if s.fecha_ingreso_lista > corte:
            continue
        ctx = contexto_a_fecha(perfil, s.id_solicitud, corte, FECHA_EXTRACCION)
        dq = auditar(ctx)
        salida[s.id_solicitud] = (ctx, dq, evaluar(ctx, dq, params))
    return salida
