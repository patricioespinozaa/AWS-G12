"""Propiedades del repositorio y la calidad de datos (sin fuga de futuro, Wilson, plausibilidad, equidad)."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any

from hypothesis import assume, given
from hypothesis import strategies as st
from statsmodels.stats.proportion import proportion_confint

from estrategias import FECHA_EXTRACCION, citas, eventos, fechas, mediciones, perfil_y_corte
from estrategias.tuberia import contexto, evaluar_crudo
from hlf_priorizacion.repositorio.cohortes import wilson


@st.composite
def _con_registros_futuros(draw: st.DrawFn) -> tuple[dict[str, Any], dict[str, Any], date]:
    raw, corte = draw(perfil_y_corte())
    assume(corte < FECHA_EXTRACCION)
    desde = corte + timedelta(days=1)
    esp = raw["lista_espera"]["especialidad"]
    futuro = copy.deepcopy(raw)
    futuro["eventos_clinicos"] += [
        draw(eventos(f"EV-9{k:05d}", desde, FECHA_EXTRACCION, esp)) for k in range(draw(st.integers(1, 3)))
    ]
    futuro["mediciones"] += [draw(mediciones(desde, FECHA_EXTRACCION)) for _ in range(draw(st.integers(0, 3)))]
    futuro["citaciones"] += [
        draw(citas(f"CT-9{k:05d}", desde, FECHA_EXTRACCION, esp)) for k in range(draw(st.integers(0, 3)))
    ]
    return raw, futuro, corte


@given(_con_registros_futuros())
def test_registros_posteriores_al_corte_no_cambian_nada(caso: tuple[dict[str, Any], dict[str, Any], date]) -> None:
    raw, futuro, corte = caso
    ctx_a, _, ev_a = evaluar_crudo(raw, corte)
    ctx_b, _, ev_b = evaluar_crudo(futuro, corte)
    assert ctx_a == ctx_b
    assert ev_a == ev_b


@given(st.integers(1, 500).flatmap(lambda n: st.tuples(st.just(n), st.integers(0, n))))
def test_wilson_contiene_p_y_coincide_con_statsmodels(nk: tuple[int, int]) -> None:
    n, k = nk
    inf, sup = wilson(k, n)
    p = k / n
    assert 0.0 <= inf <= p <= sup <= 1.0
    ref_inf, ref_sup = proportion_confint(k, n, alpha=0.05, method="wilson")
    assert abs(inf - float(ref_inf)) < 1e-9 and abs(sup - float(ref_sup)) < 1e-9


@st.composite
def _con_imposibles(draw: st.DrawFn) -> tuple[dict[str, Any], dict[str, Any], date]:
    raw, corte = draw(perfil_y_corte())
    ingreso = date.fromisoformat(raw["lista_espera"]["fecha_ingreso_lista"])
    otro = copy.deepcopy(raw)
    otro["mediciones"] += [
        draw(mediciones(ingreso, corte, categoria="imposible")) for _ in range(draw(st.integers(1, 3)))
    ]
    return raw, otro, corte


@given(_con_imposibles())
def test_mediciones_implausibles_no_cambian_el_puntaje(caso: tuple[dict[str, Any], dict[str, Any], date]) -> None:
    raw, otro, corte = caso
    _, _, a = evaluar_crudo(raw, corte)
    _, dq, b = evaluar_crudo(otro, corte)
    assert a.puntaje == b.puntaje
    assert a.nivel_propuesto == b.nivel_propuesto
    if b.tipo_resultado != "exclusion":
        assert any(h.codigo == "fuera_de_plausibilidad" for h in dq)


@given(
    perfil_y_corte(),
    st.sampled_from(["Pirque", "San Ramón"]),
    st.sampled_from(["FONASA C", "FONASA D"]),
    st.sampled_from(["bajo", "medio"]),
    st.text(min_size=1, max_size=20),
)
def test_equidad_campos_socioeconomicos_no_cambian_la_evaluacion(
    caso: tuple[dict[str, Any], date], comuna: str, prevision: str, nse: str, nombre: str
) -> None:
    raw, corte = caso
    otro = copy.deepcopy(raw)
    otro["paciente"].update(
        {"comuna": comuna, "prevision": prevision, "nivel_socioeconomico": nse, "nombre_fantasia": nombre}
    )
    assert evaluar_crudo(raw, corte)[2] == evaluar_crudo(otro, corte)[2]
    volcado = contexto(otro, corte).model_dump_json()
    for valor in (comuna, prevision):
        assert valor not in volcado


@given(perfil_y_corte())
def test_contexto_solo_contiene_registros_hasta_el_corte(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    ctx = contexto(raw, corte)
    assert all(e.fecha_evento <= corte for e in ctx.eventos)
    assert all(m.fecha_medicion <= corte for m in ctx.mediciones)
    assert all(c.fecha_cita <= corte for c in ctx.citas)


@given(fechas(date(2025, 1, 1), FECHA_EXTRACCION))
def test_estado_desconocido_antes_de_la_extraccion(corte: date) -> None:
    from ayudantes import perfil_base

    raw = perfil_base()
    raw["lista_espera"]["fecha_ingreso_lista"] = "2025-01-01"
    ctx = contexto(raw, corte)
    esperado = "en_espera" if corte == FECHA_EXTRACCION else "desconocido_a_la_fecha"
    assert ctx.solicitud.estado_a_la_fecha == esperado
