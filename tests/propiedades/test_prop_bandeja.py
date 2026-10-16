"""Propiedades de U3 (``business-logic-model.md``, PBT-01): filas, cambios y decisiones.

Perfil ``ci`` (derandomize). Todo E/S va a carpetas temporales; ninguna prueba toca ``salidas/`` real.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from estrategias.bandeja import (
    CORTE_B,
    MEDICOS,
    V,
    cortes_y_lineas,
    decisiones_validas,
    filas,
    filtros,
    listas_evaluaciones,
)
from hlf_priorizacion.bandeja.cambios import cambio_relevante, comparar
from hlf_priorizacion.bandeja.decisiones import (
    MAX_MOTIVO,
    ErrorDecision,
    crear_decision,
    guardar_decision,
    leer_decisiones,
    ruta_decisiones,
    vigentes,
)
from hlf_priorizacion.bandeja.filas import FilaBandeja, Filtros, filtrar, ordenar
from hlf_priorizacion.modelos import NIVELES, Decision, Evaluacion, RegistroCitado

Caso = tuple[date, date, list[Evaluacion], list[Evaluacion], dict[str, list[RegistroCitado]]]

# --------------------------------------------------------------------------- filas


@given(st.data())
def test_p01_orden_total_y_determinista(data: st.DataObject) -> None:
    fs = data.draw(filas())
    permutada = data.draw(st.permutations(fs))
    assert ordenar(permutada) == ordenar(fs)


@given(filas())
def test_p02_criticas_antes_que_cualquier_otra(fs: list[FilaBandeja]) -> None:
    orden = ordenar(fs)
    es_critica = [f.nivel_propuesto == "critica" for f in orden]
    assert es_critica == sorted(es_critica, reverse=True)


def _es_subsecuencia(sub: list[FilaBandeja], total: list[FilaBandeja]) -> bool:
    it = iter(total)
    return all(any(x is y for y in it) for x in sub)


@given(filas(), filtros())
def test_p03_filtrar_es_subconjunto_ordenado(fs: list[FilaBandeja], f: Filtros) -> None:
    orden = ordenar(fs)
    resultado = filtrar(orden, f)
    assert len(resultado) <= len(orden)
    assert _es_subsecuencia(resultado, orden)
    assert all(f.acepta(x) for x in resultado)
    assert all(not f.acepta(x) for x in orden if not any(x is y for y in resultado))


@given(filas(), filtros())
def test_p04_filtrar_es_idempotente(fs: list[FilaBandeja], f: Filtros) -> None:
    una = filtrar(ordenar(fs), f)
    assert filtrar(una, f) == una


# --------------------------------------------------------------------------- cambios


@given(listas_evaluaciones())
def test_p05_comparar_un_corte_consigo_mismo_no_da_cambios(evs: list[Evaluacion]) -> None:
    cmp = comparar(evs, evs, CORTE_B, CORTE_B, lambda ev: [])
    assert cmp.cambios == [] and cmp.ingresos_nuevos == [] and cmp.a_exclusion == []


@given(cortes_y_lineas())
def test_p06_registros_nuevos_con_fecha_en_el_intervalo(caso: Caso) -> None:
    a, b, props_a, props_b, lineas = caso
    cmp = comparar(props_a, props_b, a, b, lambda ev: lineas[ev.id_solicitud])
    for c in [*cmp.cambios, *cmp.ingresos_nuevos, *cmp.a_exclusion]:
        assert len(c.registros_nuevos) == len(c.fechas_registros_nuevos)
        assert all(a < f <= b for f in c.fechas_registros_nuevos)
        esperados = sorted((r.fecha, r.id_registro) for r in lineas[c.id_solicitud] if a < r.fecha <= b)
        assert list(c.registros_nuevos) == [i for _, i in esperados]


@given(cortes_y_lineas())
def test_p07_todo_cambio_listado_tiene_nivel_banderas_o_pisos_distintos(caso: Caso) -> None:
    a, b, props_a, props_b, lineas = caso
    por_a = {ev.id_solicitud: ev for ev in props_a}
    por_b = {ev.id_solicitud: ev for ev in props_b}
    cmp = comparar(props_a, props_b, a, b, lambda ev: lineas[ev.id_solicitud])
    for c in [*cmp.cambios, *cmp.a_exclusion]:
        assert cambio_relevante(por_a[c.id_solicitud], por_b[c.id_solicitud])
    assert {c.id_solicitud for c in cmp.ingresos_nuevos} == set(por_b) - set(por_a)
    # Y no se pierde ninguno: las compartidas con cambio relevante están listadas en una de las dos secciones.
    listadas = {c.id_solicitud for c in [*cmp.cambios, *cmp.a_exclusion]}
    for i in set(por_a) & set(por_b):
        if cambio_relevante(por_a[i], por_b[i]):
            assert i in listadas


# --------------------------------------------------------------------------- decisiones


def _lineas(raiz: Path) -> list[str]:
    """Líneas del JSONL separadas solo por salto de línea LF (el motivo puede traer U+0085 o U+2028 sin escapar)."""
    ruta = ruta_decisiones(raiz)
    return ruta.read_text(encoding="utf-8").split("\n")[:-1] if ruta.exists() else []


@given(decisiones_validas())
def test_p08_decision_ida_y_vuelta_por_jsonl(d: Decision) -> None:
    linea = json.dumps(d.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    assert Decision.model_validate_json(linea) == d
    with tempfile.TemporaryDirectory() as tmp:
        guardar_decision(Path(tmp), d)
        assert leer_decisiones(Path(tmp)) == [d]


@settings(max_examples=25)
@given(st.lists(decisiones_validas(), min_size=1, max_size=8, unique_by=lambda d: d.id_decision))
def test_p09_guardar_n_deja_n_y_no_cambia_las_anteriores(ds: list[Decision]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        previas: list[str] = []
        for n, d in enumerate(ds, start=1):
            guardar_decision(raiz, d)
            lineas = _lineas(raiz)
            assert len(lineas) == n
            assert lineas[: n - 1] == previas
            previas = lineas
        assert leer_decisiones(raiz) == ds


@given(st.lists(decisiones_validas(), min_size=1, max_size=10, unique_by=lambda d: d.id_decision))
def test_p10_la_vigente_es_la_de_mayor_timestamp_con_empate_por_id(ds: list[Decision]) -> None:
    vig = vigentes(ds)
    assert len(vig) == 1
    (actual,) = vig.values()
    assert actual == max(ds, key=lambda d: (d.timestamp, d.id_decision))
    assert vigentes(reversed(ds)) == vig


# --------------------------------------------------------------------------- P11: máquina de estados


def _evaluacion(propuesta: str) -> Evaluacion:
    return Evaluacion(
        id_solicitud="IC-HLF-00002",
        fecha_corte=CORTE_B,
        version_reglas=V,
        huella_contexto="sha256:prueba",
        prioridad_inicial="baja",
        puntaje=58.82,
        nivel_calculado=propuesta,  # type: ignore[arg-type]
        nivel_propuesto=propuesta,  # type: ignore[arg-type]
        tipo_resultado="priorizacion",
        confianza="media",
    )


MOTIVOS = st.one_of(
    st.none(),
    st.just(""),
    st.just("   "),
    st.text(min_size=1, max_size=30),
    st.just("x" * MAX_MOTIVO),
    st.just("x" * (MAX_MOTIVO + 1)),
)


def _es_valida(opcion: str, propuesta: str, final: str | None, motivo: str | None, usuario: str) -> bool:
    """Oráculo independiente de las reglas B5.2/B5.3."""
    texto = (motivo or "").strip()
    if len(texto) > MAX_MOTIVO or not usuario:
        return False
    if opcion == "aceptar":
        return True
    if opcion == "ajustar":
        return final is not None and final != propuesta and bool(texto)
    if opcion == "rechazar":
        return bool(texto)
    return False


class MaquinaDecisiones(RuleBasedStateMachine):
    """Aceptar/ajustar/rechazar válidas e inválidas: solo las válidas se guardan y nunca se edita una línea."""

    def __init__(self) -> None:
        super().__init__()
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.lineas: list[str] = []
        self.guardadas: list[Decision] = []
        self.segundo = 0

    @initialize()
    def empezar(self) -> None:
        assert not ruta_decisiones(self.raiz).exists()

    @rule(
        opcion=st.sampled_from(["aceptar", "ajustar", "rechazar", "otra"]),
        propuesta=st.sampled_from(NIVELES),
        final=st.one_of(st.none(), st.sampled_from(NIVELES)),
        motivo=MOTIVOS,
        usuario=st.sampled_from([*MEDICOS, ""]),
        avance=st.integers(0, 2),
    )
    def decidir(
        self, opcion: str, propuesta: str, final: str | None, motivo: str | None, usuario: str, avance: int
    ) -> None:
        self.segundo += avance  # avance 0: mismo timestamp que la anterior (empate por id_decision)
        instante = datetime(2026, 7, 20, tzinfo=UTC) + timedelta(seconds=self.segundo)
        valida = _es_valida(opcion, propuesta, final, motivo, usuario)
        try:
            d = crear_decision(
                evaluacion=_evaluacion(propuesta),
                opcion=opcion,
                usuario=usuario,
                prioridad_final=final,
                motivo=motivo,
                reloj=lambda: instante,
            )
        except ErrorDecision as e:
            assert not valida, e.mensajes
            assert e.mensajes
            return
        assert valida
        guardar_decision(self.raiz, d)
        self.guardadas.append(d)

    @invariant()
    def solo_agregar(self) -> None:
        actuales = _lineas(self.raiz)
        assert len(actuales) == len(self.guardadas)
        assert actuales[: len(self.lineas)] == self.lineas  # ninguna anterior cambió
        self.lineas = actuales

    @invariant()
    def vigente_es_la_ultima(self) -> None:
        if self.guardadas:
            (vig,) = vigentes(leer_decisiones(self.raiz)).values()
            assert vig == max(self.guardadas, key=lambda d: (d.timestamp, d.id_decision))

    def teardown(self) -> None:
        self._tmp.cleanup()


MaquinaDecisiones.TestCase.settings = settings(max_examples=30, stateful_step_count=12)
test_p11_maquina_de_decisiones = MaquinaDecisiones.TestCase
