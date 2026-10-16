"""Propiedades de reglas-v0.2.0 (business-rules.md, "Propiedades testeables nuevas"): R5.3 modificada y R11.

Pacientes con 1 a 3 SIC, incluidas duplicadas (misma especialidad y CIE-10), de la misma especialidad y de
otra especialidad (con y sin par listado en el documento de relaciones), algunas con ingreso posterior al corte.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any

from hypothesis import assume, given
from hypothesis import strategies as st

from estrategias import ESPECIALIDADES, perfil_multi_y_corte, perfil_y_corte, solicitudes_extra
from estrategias.tuberia import PARAMS, PARAMS_V010, evaluar_crudo, evaluar_todas
from hlf_priorizacion.calidad.auditoria import ids_descartados
from hlf_priorizacion.modelos import Evaluacion, SolicitudContexto
from hlf_priorizacion.motor.evaluar import evaluar
from hlf_priorizacion.motor.parametros import ParametrosReglas
from hlf_priorizacion.motor.referencia import puntaje_y_niveles

DOC = PARAMS.documento_relaciones
assert DOC is not None and PARAMS.otras_solicitudes is not None
PESOS = PARAMS.otras_solicitudes.pesos
TOPE = PARAMS.otras_solicitudes.tope


def _otras(ev: Evaluacion) -> dict[str, float]:
    return {f.ids_registro[0]: f.aporte for f in ev.factores if f.factor == "otra_solicitud"}


def _par_listado(cie_a: str, cie_b: str) -> bool:
    assert DOC is not None
    return any({p.a, p.b} == {cie_a, cie_b} for p in DOC.diagnosticos.pares)


def _sin_pares_de_especialidad(params: ParametrosReglas) -> ParametrosReglas:
    """El documento "por defecto": sin pares de especialidades (solo su valor por defecto, 0,5)."""
    doc = params.documento_relaciones
    assert doc is not None
    vacio = doc.especialidades.model_copy(update={"pares": []})
    return params.model_copy(update={"documento_relaciones": doc.model_copy(update={"especialidades": vacio})})


# --------------------------------------------------------------------------- simetría (R11.6)


@st.composite
def _dos_sic_en_espera(draw: st.DrawFn) -> tuple[dict[str, Any], date]:
    raw, corte = draw(perfil_y_corte(estado="en_espera"))
    principal = raw["lista_espera"]
    sufijo = principal["id_solicitud"].rsplit("-", 1)[1]
    hasta = max(corte, date.fromisoformat(principal["fecha_ingreso_lista"]))
    otra = draw(solicitudes_extra(principal, f"IC-MUL1-{sufijo}", hasta=hasta, estados=("en_espera",)))
    raw["lista_espera"] = [principal, otra]
    return raw, corte


@given(_dos_sic_en_espera())
def test_simetria_cada_una_usa_la_prioridad_de_la_otra(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    assert DOC is not None
    evs = evaluar_todas(raw, corte)
    assume(len(evs) == 2)
    (ia, (ctx_a, _, a)), (ib, (ctx_b, _, b)) = sorted(evs.items())
    assume(a.tipo_resultado != "exclusion" and b.tipo_resultado != "exclusion")
    sa, sb = ctx_a.solicitud, ctx_b.solicitud
    misma = sa.especialidad == sb.especialidad
    assume(not (misma and sa.diagnostico_cie10 == sb.diagnostico_cie10))
    rel = DOC.factor_diagnosticos(sa.diagnostico_cie10, sb.diagnostico_cie10, misma)
    assert rel == DOC.factor_diagnosticos(sb.diagnostico_cie10, sa.diagnostico_cie10, misma)
    esperado_a = round(getattr(PESOS, sb.prioridad_inicial) * rel, 2)
    esperado_b = round(getattr(PESOS, sa.prioridad_inicial) * rel, 2)
    assert _otras(a) == ({ib: esperado_a} if rel > 0 else {})
    assert _otras(b) == ({ia: esperado_b} if rel > 0 else {})


# --------------------------------------------------------------------------- agregar una SIC


@st.composite
def _con_sic_agregada(draw: st.DrawFn, tipo: str | None = None) -> tuple[dict[str, Any], dict[str, Any], date]:
    raw, corte = draw(perfil_multi_y_corte(max_solicitudes=2))
    principal = raw["lista_espera"][0]
    sufijo = principal["id_solicitud"].rsplit("-", 1)[1]
    nueva = draw(solicitudes_extra(principal, f"IC-NUEVA-{sufijo}", tipo=tipo))
    otro = copy.deepcopy(raw)
    otro["lista_espera"].append(nueva)  # al final: no cambia la especialidad de respaldo de los eventos
    return raw, otro, corte


@given(_con_sic_agregada())
def test_agregar_una_sic_nunca_baja_el_puntaje_de_otra(caso: tuple[dict[str, Any], dict[str, Any], date]) -> None:
    raw, otro, corte = caso
    antes, despues = evaluar_todas(raw, corte), evaluar_todas(otro, corte)
    for i, (_, _, ev) in antes.items():
        nuevo = despues[i][2]
        assert (ev.tipo_resultado == "exclusion") == (nuevo.tipo_resultado == "exclusion")
        if ev.puntaje is not None:
            assert nuevo.puntaje is not None and nuevo.puntaje >= ev.puntaje


@given(_con_sic_agregada(tipo="otra_especialidad"))
def test_sic_de_otra_especialidad_sin_par_no_cambia_el_puntaje(
    caso: tuple[dict[str, Any], dict[str, Any], date],
) -> None:
    raw, otro, corte = caso
    nueva = otro["lista_espera"][-1]
    antes, despues = evaluar_todas(raw, corte), evaluar_todas(otro, corte)
    for i, (ctx, _, ev) in antes.items():
        s = ctx.solicitud
        if s.especialidad == nueva["especialidad"] or _par_listado(s.diagnostico_cie10, nueva["diagnostico_cie10"]):
            continue
        nuevo = despues[i][2]
        assert (nuevo.puntaje, nuevo.nivel_calculado, nuevo.nivel_propuesto) == (
            ev.puntaje,
            ev.nivel_calculado,
            ev.nivel_propuesto,
        )
        assert nueva["id_solicitud"] not in _otras(nuevo)


# --------------------------------------------------------------------------- duplicadas, tope y vigencia


@given(perfil_multi_y_corte())
def test_duplicadas_no_se_aportan_y_la_mas_reciente_se_alerta(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    for ctx, _, ev in evaluar_todas(raw, corte).values():
        if ev.tipo_resultado == "exclusion":
            continue
        s = ctx.solicitud
        duplicadas = {
            o.id_solicitud
            for o in ctx.otras_solicitudes
            if o.especialidad == s.especialidad and o.diagnostico_cie10 == s.diagnostico_cie10
        }
        assert not duplicadas & set(_otras(ev))
        alertadas = {i for a in ev.alertas_gestion if a.codigo == "sic_duplicada" for i in a.ids_registro}
        assert alertadas <= duplicadas
        for i in alertadas:
            o = next(o for o in ctx.otras_solicitudes if o.id_solicitud == i)
            assert (o.fecha_ingreso_lista, o.id_solicitud) < (s.fecha_ingreso_lista, s.id_solicitud)


@given(perfil_multi_y_corte(min_solicitudes=3, max_solicitudes=3))
def test_tope_de_otras_solicitudes(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    for _, _, ev in evaluar_todas(raw, corte).values():
        assert sum(_otras(ev).values()) <= TOPE + 1e-9
        assert all(v >= 0 for v in _otras(ev).values())


@given(perfil_multi_y_corte(), st.integers(1, 200))
def test_sic_con_ingreso_posterior_al_corte_no_aporta(caso: tuple[dict[str, Any], date], dias: int) -> None:
    raw, corte = caso
    for ctx, dq, ev in evaluar_todas(raw, corte).values():
        assert all(o.fecha_ingreso_lista <= corte for o in ctx.otras_solicitudes)  # repositorio
        futura = SolicitudContexto(
            id_solicitud="IC-FUT-00001",
            especialidad=ctx.solicitud.especialidad,
            sub_especialidad="futura",
            diagnostico_cie10="I50" if ctx.solicitud.diagnostico_cie10 != "I50" else "I20",
            diagnostico_texto="futura",
            prioridad_inicial="alta",
            fecha_ingreso_lista=corte + timedelta(days=dias),
            origen_derivacion="Urgencia",
            estado_extraccion="en_espera",
            estado_a_la_fecha="desconocido_a_la_fecha",
        )
        con_futura = ctx.model_copy(update={"otras_solicitudes": [*ctx.otras_solicitudes, futura]})
        assert evaluar(con_futura, dq, PARAMS) == ev  # motor: tampoco la cuenta


# --------------------------------------------------------------------------- oráculos


@given(perfil_y_corte())
def test_una_sic_v020_con_documento_por_defecto_igual_a_v010(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    ctx, dq, _ = evaluar_crudo(raw, corte)
    v1 = evaluar(ctx, dq, PARAMS_V010)
    v2 = evaluar(ctx, dq, _sin_pares_de_especialidad(PARAMS))
    assert (v2.puntaje, v2.nivel_calculado, v2.nivel_propuesto, v2.tipo_resultado) == (
        v1.puntaje,
        v1.nivel_calculado,
        v1.nivel_propuesto,
        v1.tipo_resultado,
    )


@given(perfil_y_corte())
def test_una_sic_sin_pares_de_especialidad_usados_v020_igual_a_v010(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    assert DOC is not None
    ctx, dq, v2 = evaluar_crudo(raw, corte)
    listados = {(p.de, p.a) for p in DOC.especialidades.pares}
    assume(all((e.especialidad_evento, ctx.solicitud.especialidad) not in listados for e in ctx.eventos))
    v1 = evaluar(ctx, dq, PARAMS_V010)
    assert (v2.puntaje, v2.nivel_calculado, v2.nivel_propuesto, v2.tipo_resultado) == (
        v1.puntaje,
        v1.nivel_calculado,
        v1.nivel_propuesto,
        v1.tipo_resultado,
    )
    assert [f.aporte for f in v2.factores] == [f.aporte for f in v1.factores]
    if all(e.especialidad_evento == ctx.solicitud.especialidad for e in ctx.eventos):
        # Sin eventos de otra especialidad no se usa el documento: todo igual salvo la versión.
        assert v2 == v1.model_copy(update={"version_reglas": v2.version_reglas})


@given(perfil_multi_y_corte())
def test_motor_coincide_con_la_referencia_con_varias_sic(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    for ctx, dq, ev in evaluar_todas(raw, corte).values():
        if ev.tipo_resultado == "exclusion":
            continue
        puntaje, calculado, propuesto = puntaje_y_niveles(ctx, dq, PARAMS)
        assert ev.puntaje is not None and abs(ev.puntaje - puntaje) < 1e-9
        assert (ev.nivel_calculado, ev.nivel_propuesto) == (calculado, propuesto)


@given(perfil_multi_y_corte())
def test_confianza_no_alta_si_uso_el_documento_no_validado(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    for ctx, dq, ev in evaluar_todas(raw, corte).values():
        fuera = ids_descartados(dq)
        otra_esp = any(
            e.especialidad_evento != ctx.solicitud.especialidad for e in ctx.eventos if e.id_evento not in fuera
        )
        uso = bool(_otras(ev)) or (otra_esp and ev.tipo_resultado != "exclusion")
        assert ("relaciones clínicas no validadas" in ev.motivo_confianza) == uso
        if uso:
            assert ev.confianza != "alta"


def test_especialidades_de_las_estrategias_estan_en_el_catalogo() -> None:
    from hlf_priorizacion.contrato.catalogos import ESPECIALIDADES_CATALOGO

    assert set(ESPECIALIDADES) == ESPECIALIDADES_CATALOGO
