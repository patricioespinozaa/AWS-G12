"""Propiedades del motor de reglas (invariantes, metamórficas, idempotencia y oráculo)."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any

from hypothesis import assume, given
from hypothesis import strategies as st

from estrategias import citas, perfil_y_corte
from estrategias.tuberia import PARAMS, evaluar_crudo
from hlf_priorizacion.contrato.catalogos import SUBTIPOS_MEJORIA
from hlf_priorizacion.modelos import ORDEN_NIVEL
from hlf_priorizacion.motor.evaluar import evaluar
from hlf_priorizacion.motor.referencia import puntaje_y_niveles


@given(perfil_y_corte())
def test_puntaje_acotado_y_salida_coherente(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    ctx, _, ev = evaluar_crudo(raw, corte)
    if ev.tipo_resultado != "exclusion":
        assert ev.puntaje is not None and 0.0 <= ev.puntaje <= 100.0
    assert ev.prioridad_inicial == ctx.solicitud.prioridad_inicial == raw["lista_espera"]["prioridad_inicial"]
    assert ev.estado_revision == "pendiente_revision_medica"


@given(perfil_y_corte())
def test_bandera_implica_critica_y_piso_al_menos_alta(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    _, _, ev = evaluar_crudo(raw, corte)
    if ev.banderas:
        assert ev.nivel_propuesto == "critica"
    if ev.pisos:
        assert ev.nivel_propuesto is not None and ORDEN_NIVEL[ev.nivel_propuesto] >= ORDEN_NIVEL["alta"]


@given(perfil_y_corte())
def test_bajada_limitada_a_un_nivel_y_solo_con_evidencia(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    ctx, _, ev = evaluar_crudo(raw, corte)
    assume(ev.nivel_propuesto is not None)
    assert ev.nivel_propuesto is not None
    inicial = ORDEN_NIVEL[ev.prioridad_inicial]
    propuesto = ORDEN_NIVEL[ev.nivel_propuesto]
    assert propuesto >= inicial - 1
    if not any(e.subtipo in SUBTIPOS_MEJORIA for e in ctx.eventos):
        assert propuesto >= inicial


@given(perfil_y_corte(max_eventos=0, max_mediciones=0))
def test_sin_eventos_ni_mediciones_no_baja(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    _, _, ev = evaluar_crudo(raw, corte)
    if ev.nivel_propuesto is not None:
        assert ORDEN_NIVEL[ev.nivel_propuesto] >= ORDEN_NIVEL[ev.prioridad_inicial]


@st.composite
def _con_citas_extra(draw: st.DrawFn) -> tuple[dict[str, Any], dict[str, Any], date]:
    raw, corte = draw(perfil_y_corte(estado="en_espera"))
    ingreso = date.fromisoformat(raw["lista_espera"]["fecha_ingreso_lista"])
    otro = copy.deepcopy(raw)
    otro["citaciones"] += [
        draw(citas(f"CT-8{k:05d}", ingreso, corte, raw["lista_espera"]["especialidad"]))
        for k in range(draw(st.integers(1, 5)))
    ]
    return raw, otro, corte


@given(_con_citas_extra())
def test_citas_no_cambian_puntaje_ni_nivel(caso: tuple[dict[str, Any], dict[str, Any], date]) -> None:
    raw, otro, corte = caso
    _, _, a = evaluar_crudo(raw, corte)
    _, _, b = evaluar_crudo(otro, corte)
    assert (a.puntaje, a.nivel_calculado, a.nivel_propuesto) == (b.puntaje, b.nivel_calculado, b.nivel_propuesto)


@given(perfil_y_corte(), st.integers(1, 400))
def test_mas_espera_nunca_baja_el_puntaje(caso: tuple[dict[str, Any], date], dias_extra: int) -> None:
    raw, corte = caso
    ctx, dq, ev = evaluar_crudo(raw, corte)
    assume(ev.tipo_resultado != "exclusion")
    solicitud = ctx.solicitud.model_copy(
        update={"fecha_ingreso_lista": ctx.solicitud.fecha_ingreso_lista - timedelta(days=dias_extra)}
    )
    mas_espera = evaluar(ctx.model_copy(update={"solicitud": solicitud}), dq, PARAMS)
    assert ev.puntaje is not None and mas_espera.puntaje is not None
    assert mas_espera.puntaje >= ev.puntaje


@given(perfil_y_corte())
def test_evaluar_es_idempotente(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    ctx, dq, ev = evaluar_crudo(raw, corte)
    assert evaluar(ctx, dq, PARAMS) == ev
    assert evaluar(ctx, dq, PARAMS).model_dump_json() == ev.model_dump_json()


@given(perfil_y_corte())
def test_factores_con_aporte_citan_ids_del_contexto(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    ctx, _, ev = evaluar_crudo(raw, corte)
    presentes = ctx.ids_presentes()
    for f in ev.factores:
        if f.aporte != 0:
            assert f.ids_registro and set(f.ids_registro) <= presentes
    for grupo in (ev.banderas, ev.pisos, ev.alertas_gestion):
        for item in grupo:
            assert set(item.ids_registro) <= presentes


@given(perfil_y_corte())
def test_motor_coincide_con_la_referencia(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    ctx, dq, ev = evaluar_crudo(raw, corte)
    assume(ev.tipo_resultado != "exclusion")
    puntaje, calculado, propuesto = puntaje_y_niveles(ctx, dq, PARAMS)
    assert ev.puntaje is not None and abs(ev.puntaje - puntaje) < 1e-9
    assert (ev.nivel_calculado, ev.nivel_propuesto) == (calculado, propuesto)
