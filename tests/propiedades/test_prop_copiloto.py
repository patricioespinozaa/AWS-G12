"""Las 14 propiedades de U2 (``business-logic-model.md``, PBT-01), más P15 (presupuesto de invocaciones, C2.5)
y P16a/b/c (equidad determinista sin negaciones, C6.5, decisión E-1 = C). Ninguna llama a Bedrock."""

from __future__ import annotations

import itertools
import json
import shutil
import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from ayudantes import evento, medicion, perfil_base
from estrategias import FECHA_EXTRACCION, perfiles
from estrategias.copiloto import (
    analisis_con_justificacion,
    correr_lote,
    entrada_valida,
    escribir_dataset,
    frase_con_atributo_no_disponible,
    frase_inasistencia_con_bajada,
    paquetes,
    pares_fechas,
    perfil_y_paquete,
    responder_eco,
    respuestas,
)
from estrategias.tuberia import evaluar_crudo
from hlf_priorizacion.copiloto.barrido import (
    MAX_INVOCACIONES_POR_SOLICITUD,
    ClienteConPresupuesto,
    ConfigBarrido,
    Contexto,
    CorteCircuito,
    construir_tarea,
    ejecutar_barrido,
    ejecutar_tareas,
)
from hlf_priorizacion.copiloto.cliente import (
    ClienteFalso,
    ErrorModelo,
    ErrorReintentable,
    PeticionModelo,
    RespuestaModelo,
    respuesta_falsa,
)
from hlf_priorizacion.copiloto.config import ConfigModelo
from hlf_priorizacion.copiloto.fechas import MAX_DIAS_RANGO, ErrorFecha, cortes_a_procesar, parsear_fecha
from hlf_priorizacion.copiloto.modelos import PaqueteBarrido
from hlf_priorizacion.copiloto.paquete import render_datos
from hlf_priorizacion.copiloto.persistencia import carpeta_analisis, leer_analisis, leer_fallidos
from hlf_priorizacion.copiloto.prompt import cargar_prompt
from hlf_priorizacion.copiloto.seleccion import ids_citados, planificar
from hlf_priorizacion.copiloto.validacion import (
    MOTIVO_EQUIDAD,
    atributo_no_disponible,
    entrada_de_analisis,
    frases_revision_equidad,
    riesgo_de_paquete,
    validar_salida,
)
from hlf_priorizacion.modelos import AnalisisIA, Evaluacion, MetadatosAnalisis
from hlf_priorizacion.motor.parametros import VERSION_POR_DEFECTO

PROMPT = cargar_prompt()
CONFIG = ConfigModelo()
CAMPOS_PROHIBIDOS = ("comuna", "prevision", "nivel_socioeconomico", "nombre_fantasia")
# Frases que C6.5 no rechaza ni marca (para P16c).
RELLENO_C65 = (
    "La urgencia reciente obliga a subir la prioridad.",
    "Tiene inasistencias previas; conviene confirmar la próxima cita.",
    "Se sugiere postergar el examen hasta tener la medición.",
)


def _meta(p: PaqueteBarrido) -> MetadatosAnalisis:
    return MetadatosAnalisis(
        model_id=CONFIG.model_id, version_prompt=PROMPT.version_prompt, request_id="req", fecha_corte=p.fecha_corte,
        id_ejecucion="prueba",
    )


def _usuario(p: PaqueteBarrido) -> str:
    return construir_tarea(p, PROMPT).usuario


def _cx(cliente: Any, circuito: CorteCircuito | None = None) -> Contexto:
    return Contexto(cliente, CONFIG, PROMPT, "prueba", circuito or CorteCircuito(), threading.Event(), lambda _s: None)


# --------------------------------------------------------------------------- fechas (1, 2)


@given(st.dates(date(1900, 1, 1), date(2999, 12, 31)))
def test_p01_fecha_iso_ida_y_vuelta(d: date) -> None:
    assert parsear_fecha(d.isoformat()) == d


@given(pares_fechas())
def test_p02_pares_aceptados_cumplen_c23_y_el_resto_se_rechaza(par: tuple[date, date, date]) -> None:
    desde, hasta, extraccion = par
    valido = desde < hasta and hasta <= extraccion and (hasta - desde).days + 1 <= MAX_DIAS_RANGO
    try:
        cortes = cortes_a_procesar(None, desde, hasta, extraccion)
    except ErrorFecha:
        assert not valido
        return
    assert valido
    assert cortes[0] == desde and cortes[-1] == hasta and len(cortes) <= MAX_DIAS_RANGO
    assert all(b - a == timedelta(days=1) for a, b in itertools.pairwise(cortes))


# --------------------------------------------------------------------------- selección (3, 4, 5)


@st.composite
def evaluaciones_de_un_corte(draw: st.DrawFn) -> list[Evaluacion]:
    corte = date(2026, 10, 13)
    crudos = draw(st.lists(perfiles(), min_size=1, max_size=6, unique_by=lambda r: r["lista_espera"]["id_solicitud"]))
    return [evaluar_crudo(r, corte)[2] for r in crudos]


@given(evaluaciones_de_un_corte(), st.data())
def test_p03_cada_solicitud_termina_en_exactamente_un_estado(evs: list[Evaluacion], data: st.DataObject) -> None:
    corte = evs[0].fecha_corte
    ya = set(data.draw(st.lists(st.sampled_from([e.id_solicitud for e in evs]), max_size=3)))
    plan = planificar({corte: evs}, {corte: ya}, modo_rango=False, forzar=False)
    decisiones = plan.cortes[0].decisiones
    assert sorted(d.id_solicitud for d in decisiones) == sorted(e.id_solicitud for e in evs)
    assert all((d.estado == "omitida") == (d.motivo is not None) for d in decisiones)
    omitidas = {d.id_solicitud for d in plan.cortes[0].omitidas}
    pendientes = {d.id_solicitud for d in plan.cortes[0].pendientes}
    assert omitidas.isdisjoint(pendientes) and omitidas | pendientes == {e.id_solicitud for e in evs}


@given(st.lists(perfil_y_paquete(), min_size=1, max_size=5), st.data())
def test_p03b_pendientes_terminan_analizadas_o_fallidas(items: list[Any], data: st.DataObject) -> None:
    paquetes_ = {p.id_solicitud: p for _, p in items}
    falla = set(data.draw(st.lists(st.sampled_from(sorted(paquetes_)), max_size=3)))

    def responder(pet: PeticionModelo) -> RespuestaModelo | Exception:
        return ErrorModelo("ValidationException") if pet.id_solicitud in falla else responder_eco(pet)

    tareas = [construir_tarea(p, PROMPT) for p in paquetes_.values()]
    resultados = ejecutar_tareas(tareas, _cx(ClienteFalso(responder), CorteCircuito(ventana=10, umbral=1.0)), 3)
    assert sorted(r.id_solicitud for r in resultados) == sorted(paquetes_)
    for r in resultados:
        assert (r.registro is None) != (r.fallido is None)
        assert (r.fallido is not None) == (r.id_solicitud in falla)


@given(evaluaciones_de_un_corte())
def test_p04_solo_priorizacion_puede_quedar_pendiente(evs: list[Evaluacion]) -> None:
    corte = evs[0].fecha_corte
    plan = planificar({corte: evs}, {}, modo_rango=False, forzar=True)
    for d in plan.cortes[0].decisiones:
        if d.estado == "pendiente":
            assert d.evaluacion.tipo_resultado == "priorizacion"
        else:
            assert d.evaluacion.tipo_resultado != "priorizacion" or d.motivo in {"ya_analizada", "sin_cambio_en_rango"}
            if d.evaluacion.tipo_resultado != "priorizacion":
                assert d.motivo == d.evaluacion.tipo_resultado


@given(evaluaciones_de_un_corte(), st.randoms(use_true_random=False))
def test_p05_la_seleccion_no_depende_del_orden(evs: list[Evaluacion], rnd: Any) -> None:
    corte = evs[0].fecha_corte
    otro = list(evs)
    rnd.shuffle(otro)
    a = planificar({corte: evs}, {}, modo_rango=False, forzar=False)
    b = planificar({corte: otro}, {}, modo_rango=False, forzar=False)
    assert a == b


# --------------------------------------------------------------------------- paquete (6, 7)


def _valores(nodo: Any) -> list[str]:
    if isinstance(nodo, dict):
        return [v for x in nodo.values() for v in _valores(x)] + [str(k) for k in nodo]
    if isinstance(nodo, list):
        return [v for x in nodo for v in _valores(x)]
    return [nodo] if isinstance(nodo, str) else []


@given(perfil_y_paquete())
def test_p06_el_paquete_nunca_lleva_atributos_prohibidos(item: tuple[dict[str, Any], PaqueteBarrido]) -> None:
    raw, p = item
    texto = _usuario(p)
    for campo in CAMPOS_PROHIBIDOS:
        assert campo not in texto
    paciente = raw["paciente"]
    for valor in (paciente["comuna"], paciente["prevision"], paciente["nombre_fantasia"]):
        assert valor not in texto
    valores = set(_valores(json.loads(render_datos(p))))
    for campo in CAMPOS_PROHIBIDOS:
        assert paciente[campo] not in valores


@given(paquetes())
def test_p07_todo_id_de_la_evaluacion_esta_en_el_paquete(p: PaqueteBarrido) -> None:
    texto = render_datos(p)
    for i in ids_citados(p.evaluacion):
        assert f'"{i}"' in texto
    assert ids_citados(p.evaluacion) <= p.ids_paquete()


# --------------------------------------------------------------------------- validación (8, 9, 10, 11)


@st.composite
def paquete_y_respuesta(draw: st.DrawFn) -> tuple[PaqueteBarrido, str, dict[str, Any] | None]:
    p = draw(paquetes())
    tipo, entrada = draw(respuestas(p))
    return p, tipo, entrada


@given(paquete_y_respuesta())
def test_p08_tras_validar_los_documentados_citan_ids_existentes(t: tuple[PaqueteBarrido, str, Any]) -> None:
    p, tipo, entrada = t
    v = validar_salida(entrada, p, _meta(p))
    if tipo in {"malformada", "atributo_no_disponible"}:
        assert not v.valido and v.motivo_rechazo
        return
    assert bool(v.revision_equidad) == (tipo == "revision_equidad")
    assert v.valido and v.analisis is not None, v.motivo_rechazo
    ids = p.ids_paquete()
    for h in v.analisis.hallazgos:
        assert set(h.ids_registro) <= ids
        if h.tipo == "documentado":
            assert h.ids_registro
    for e in v.analisis.linea_tiempo_relevante:
        assert set(e.ids_registro) <= ids
    for inc in v.analisis.inconsistencias_datos:
        assert inc.ids_registro and set(inc.ids_registro) <= ids
    if tipo == "ids_inventados":
        assert any(c.tipo == "hallazgo_a_inferido" for c in v.correcciones)
    assert v.analisis.metadatos.estado == "pendiente_revision_medica"


@given(paquete_y_respuesta())
def test_p09_riesgo_poblacional_es_el_de_la_cohorte(t: tuple[PaqueteBarrido, str, Any]) -> None:
    p, tipo, entrada = t
    v = validar_salida(entrada, p, _meta(p))
    if v.analisis is not None:
        assert v.analisis.riesgo_poblacional == riesgo_de_paquete(p)
    if tipo == "cifras_distintas" and v.valido:
        esperado = riesgo_de_paquete(p)
        if entrada is not None and (esperado is None or entrada["riesgo_poblacional"] != esperado.model_dump()):
            assert any(c.tipo == "riesgo_poblacional_reemplazado" for c in v.correcciones)


@given(paquete_y_respuesta())
def test_p10_validar_dos_veces_es_validar_una(t: tuple[PaqueteBarrido, str, Any]) -> None:
    p, _tipo, entrada = t
    v1 = validar_salida(entrada, p, _meta(p))
    if v1.analisis is None:
        return
    v2 = validar_salida(entrada_de_analisis(v1.analisis), p, _meta(p))
    assert v2.valido and v2.analisis == v1.analisis
    # La marca de equidad (C6.5 regla 2) se vuelve a calcular igual; ninguna otra corrección se repite.
    assert v2.revision_equidad == v1.revision_equidad
    assert v2.correcciones == [c for c in v1.correcciones if c.tipo == "revision_equidad"]


@given(paquetes())
def test_p11_analisis_json_ida_y_vuelta(p: PaqueteBarrido) -> None:
    v = validar_salida(entrada_valida(p), p, _meta(p))
    assert v.analisis is not None, v.motivo_rechazo
    assert AnalisisIA.model_validate_json(v.analisis.model_dump_json()) == v.analisis


# --------------------------------------------------------------------------- persistencia (12)


@settings(max_examples=8)
@given(st.lists(perfiles(), min_size=1, max_size=5, unique_by=lambda r: r["id_paciente"]))
def test_p12_segunda_ejecucion_sin_llamadas_ni_duplicados(crudos: list[dict[str, Any]]) -> None:
    for n, raw in enumerate(crudos):  # IDs únicos en todo el dataset, como en el real
        raw["lista_espera"]["id_solicitud"] = f"IC-HLF-{n + 1:05d}"
    corte = FECHA_EXTRACCION
    with tempfile.TemporaryDirectory() as tmp:
        datos = escribir_dataset(Path(tmp) / "datos", crudos)
        salidas = Path(tmp) / "salidas"
        correr_lote(datos, salidas, [corte])
        cfg = ConfigBarrido([corte], False, FECHA_EXTRACCION, datos, salidas, VERSION_POR_DEFECTO, 300)
        r1 = ejecutar_barrido(cfg, CONFIG, PROMPT, ClienteFalso(responder_eco), "e1", dormir=lambda _s: None)
        antes = leer_analisis(salidas, corte, VERSION_POR_DEFECTO)
        cliente2 = ClienteFalso(responder_eco)
        r2 = ejecutar_barrido(cfg, CONFIG, PROMPT, cliente2, "e2", dormir=lambda _s: None)
        assert cliente2.llamadas == [] and r2.llamadas_modelo == 0
        assert leer_analisis(salidas, corte, VERSION_POR_DEFECTO) == antes
        assert len(antes) == r1.analizadas
        assert r2.omitidas.get("ya_analizada", 0) == r1.analizadas


# --------------------------------------------------------------------------- ejecución (13, 14)


def _sin_ids_de_ejecucion(a: AnalisisIA) -> dict[str, Any]:
    d = a.model_dump(mode="json")
    d["metadatos"].pop("id_ejecucion")
    return d


@given(st.lists(paquetes(), min_size=1, max_size=6, unique_by=lambda p: p.id_solicitud))
def test_p13_secuencial_y_paralelo_dan_el_mismo_conjunto(ps: list[PaqueteBarrido]) -> None:
    tareas = [construir_tarea(p, PROMPT) for p in ps]
    uno = ejecutar_tareas(tareas, _cx(ClienteFalso(responder_eco)), 1)
    cuatro = ejecutar_tareas(list(reversed(tareas)), _cx(ClienteFalso(responder_eco)), 4)

    def conjunto(rs: list[Any]) -> list[tuple[str, Any]]:
        return [
            (r.id_solicitud, _sin_ids_de_ejecucion(r.registro.analisis) if r.registro else r.fallido.motivo)
            for r in rs
        ]

    assert conjunto(uno) == conjunto(cuatro)


class MaquinaCorteCircuito(RuleBasedStateMachine):
    """Stateful: una vez abierto, ninguna llamada nueva empieza; se abre con más del 20 % de 10 fallando."""

    def __init__(self) -> None:
        super().__init__()
        self.c = CorteCircuito()
        self.ultimas: list[bool] = []
        self.abierto_modelo = False

    @rule(ok=st.booleans())
    def llamada(self, ok: bool) -> None:
        if self.c.permitir():
            assert not self.abierto_modelo
            self.c.registrar(ok)
            self.ultimas = ([*self.ultimas, ok])[-10:]
            if sum(1 for x in self.ultimas if not x) > 2:
                self.abierto_modelo = True
        else:
            assert self.abierto_modelo

    @invariant()
    def estado_coincide(self) -> None:
        assert self.c.abierto == self.abierto_modelo

    @invariant()
    def nada_empieza_despues_de_abrir(self) -> None:
        if "apertura" in self.c.bitacora:
            assert "inicio" not in self.c.bitacora[self.c.bitacora.index("apertura") :]


TestMaquinaCorteCircuito = MaquinaCorteCircuito.TestCase


@pytest.mark.parametrize("concurrencia", [1, 4, 8])
def test_p14_con_fallas_ninguna_llamada_empieza_tras_abrir(concurrencia: int) -> None:
    import hypothesis

    @hypothesis.given(st.lists(paquetes(), min_size=6, max_size=12, unique_by=lambda p: p.id_solicitud))
    @hypothesis.settings(max_examples=10)
    def caso(ps: list[PaqueteBarrido]) -> None:
        circuito = CorteCircuito()
        cliente = ClienteFalso(lambda _p: ErrorModelo("ValidationException"))
        resultados = ejecutar_tareas([construir_tarea(p, PROMPT) for p in ps], _cx(cliente, circuito), concurrencia)
        assert circuito.abierto
        abre = circuito.bitacora.index("apertura")
        assert "inicio" not in circuito.bitacora[abre:]
        assert len(cliente.llamadas) == circuito.bitacora.count("inicio")
        assert all(r.fallido is not None for r in resultados)
        assert sum(1 for r in resultados if r.fallido and r.fallido.motivo == "circuito_abierto") == len(ps) - len(
            cliente.llamadas
        )

    caso()


# --------------------------------------------------------------------------- presupuesto de invocaciones (15)


SALIDAS_FALSAS = ("valida", "malformada", "limitacion", "error_modelo")


@settings(max_examples=40)
@given(
    st.lists(paquetes(), min_size=1, max_size=5, unique_by=lambda p: p.id_solicitud),
    st.integers(0, 20),
    st.integers(1, 4),
    st.data(),
)
def test_p15_el_presupuesto_nunca_se_excede(
    ps: list[PaqueteBarrido], presupuesto: int, concurrencia: int, data: st.DataObject
) -> None:
    """C2.5: con cualquier mezcla de respuestas, invocaciones reales <= B y cada solicitud en un solo estado."""
    guiones = {
        p.id_solicitud: data.draw(
            st.lists(
                st.sampled_from(SALIDAS_FALSAS),
                min_size=MAX_INVOCACIONES_POR_SOLICITUD,
                max_size=MAX_INVOCACIONES_POR_SOLICITUD,
            )
        )
        for p in ps
    }
    posicion = dict.fromkeys(guiones, 0)  # cada solicitud la atiende un solo hilo

    def responder(pet: PeticionModelo) -> RespuestaModelo | Exception:
        tipo = guiones[pet.id_solicitud][posicion[pet.id_solicitud]]
        posicion[pet.id_solicitud] += 1
        if tipo == "limitacion":
            return ErrorReintentable("ThrottlingException")
        if tipo == "error_modelo":
            return ErrorModelo("ValidationException")
        if tipo == "malformada":
            return respuesta_falsa({"id_solicitud": pet.id_solicitud})
        return responder_eco(pet)

    falso = ClienteFalso(responder)
    con_presupuesto = ClienteConPresupuesto(falso, presupuesto)
    resultados = ejecutar_tareas([construir_tarea(p, PROMPT) for p in ps], _cx(con_presupuesto), concurrencia)
    assert len(falso.llamadas) == con_presupuesto.invocaciones <= presupuesto
    assert sorted(r.id_solicitud for r in resultados) == sorted(p.id_solicitud for p in ps)
    estados = [r.estado for r in resultados]  # lanza si alguna queda en más de un estado o en ninguno
    assert set(estados) <= {"analizada", "omitida", "fallida"}
    if "omitida" in estados:  # solo se deja una solicitud cuando el presupuesto ya se usó entero
        assert con_presupuesto.invocaciones == presupuesto


# --------------------------------------------------------------------------- persistencia incremental y Ctrl+C (17)


CORTE_P17 = date(2026, 7, 20)
IDS_P17 = [f"IC-TST-{i:05d}" for i in range(1, 7)]
SALIDAS_P17 = ("valida", "malformada", "error_modelo", "inesperado")


def _perfil_pendiente(i: int) -> dict[str, Any]:
    """Sube a crítica el 2026-07-20 (urgencia ESI 2): siempre queda pendiente para el copiloto."""
    p = perfil_base(
        id_paciente=f"PAC-TST-{i:05d}",
        eventos_clinicos=[evento(f"EV-{i:06d}", "2026-07-20", "visita_urgencia", "triage ESI 2", "grave")],
        mediciones=[medicion("2026-07-08", "presion_sistolica", 167, "mmHg", True)],
    )
    p["lista_espera"]["id_solicitud"] = f"IC-TST-{i:05d}"
    return p


@pytest.fixture(scope="module")
def lote_p17(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    raiz = tmp_path_factory.mktemp("p17")
    datos = escribir_dataset(raiz / "datos", [_perfil_pendiente(i) for i in range(1, len(IDS_P17) + 1)])
    correr_lote(datos, raiz / "lote", [CORTE_P17])
    return datos, raiz / "lote"


def _lineas_jsonl(ruta: Path) -> list[dict[str, Any]]:
    if not ruta.exists():
        return []
    texto = ruta.read_text(encoding="utf-8")
    assert texto.endswith("\n")  # ninguna línea quedó a medias
    return [json.loads(x) for x in texto.split("\n")[:-1]]  # cada línea es un JSON completo


@settings(max_examples=25)
@given(
    st.lists(st.sampled_from(SALIDAS_P17), min_size=len(IDS_P17), max_size=len(IDS_P17)),
    st.integers(1, 8),
    st.integers(1, len(IDS_P17) + 1),  # tras cuántas terminadas llega Ctrl+C; N + 1 = nunca
)
def test_p17_lo_persistido_es_completo_y_con_lo_interrumpido_cubre_el_plan(
    lote_p17: tuple[Path, Path], mezcla: list[str], concurrencia: int, k: int
) -> None:
    datos, lote = lote_p17
    tipo = dict(zip(IDS_P17, mezcla, strict=True))
    soltar = threading.Event()  # desde la k-ésima, las llamadas esperan a Ctrl+C: algunas quedan en curso

    def responder(pet: PeticionModelo) -> RespuestaModelo | Exception:
        if IDS_P17.index(pet.id_solicitud) >= k:
            assert soltar.wait(10)
        t = tipo[pet.id_solicitud]
        if t == "error_modelo":
            return ErrorModelo("ValidationException")
        if t == "inesperado":
            return RuntimeError("fallo")
        if t == "malformada":
            return respuesta_falsa({"id_solicitud": pet.id_solicitud})
        return responder_eco(pet)

    def vigia(n: int) -> None:
        if n == k:
            soltar.set()
            raise KeyboardInterrupt

    with tempfile.TemporaryDirectory() as tmp:
        salidas = Path(tmp) / "salidas"
        shutil.copytree(lote, salidas)
        cfg = ConfigBarrido([CORTE_P17], False, FECHA_EXTRACCION, datos, salidas, VERSION_POR_DEFECTO, 300)
        config = ConfigModelo(concurrencia=concurrencia)
        r = ejecutar_barrido(cfg, config, PROMPT, ClienteFalso(responder), "e1", dormir=lambda _s: None, vigia=vigia)

        carpeta = carpeta_analisis(salidas, CORTE_P17, VERSION_POR_DEFECTO)
        filas_analisis = _lineas_jsonl(carpeta / "analisis.jsonl")
        filas_fallidos = _lineas_jsonl(carpeta / "fallidos.jsonl")
        eventos = _lineas_jsonl(salidas / "auditoria" / "eventos.jsonl")
        analisis = leer_analisis(salidas, CORTE_P17, VERSION_POR_DEFECTO)
        assert len(analisis) == len(filas_analisis)
        fallidas = {f.id_solicitud for f in leer_fallidos(salidas, CORTE_P17, VERSION_POR_DEFECTO)}
        assert len(fallidas) == len(filas_fallidos)

        # Todo análisis guardado tiene su llamada auditada, su E/S del modelo y su evento analisis_ia.
        llamadas = [e for e in eventos if e["tipo"] == "llamada_modelo"]
        io = salidas / "copiloto_io" / f"fecha_corte={CORTE_P17.isoformat()}"
        for a in analisis:
            assert any(e["id_solicitud"] == a.id_solicitud and e["huella_salida"] == a.huella_salida for e in llamadas)
            assert (io / (a.huella_salida.removeprefix("sha256:") + ".json")).is_file()
        assert {a.id_solicitud for a in analisis} == {e["id_solicitud"] for e in eventos if e["tipo"] == "analisis_ia"}
        assert r.tokens_entrada == sum(int(e["tokens_entrada"]) for e in llamadas)

        # Persistidas + interrumpidas = plan, sin solapes.
        analizadas = {a.id_solicitud for a in analisis}
        interrumpidas = {
            e["id_solicitud"] for e in eventos if e["tipo"] == "analisis_omitido" and e["motivo"] == "interrumpido"
        }
        assert analizadas.isdisjoint(fallidas) and analizadas.isdisjoint(interrumpidas)
        assert fallidas.isdisjoint(interrumpidas)
        assert analizadas | fallidas | interrumpidas == set(IDS_P17)
        assert r.interrumpido == (k <= len(IDS_P17))
        assert (r.analizadas, r.total_fallidas, r.interrumpidas) == (len(analizadas), len(fallidas), len(interrumpidas))
        if not r.interrumpido:
            assert interrumpidas == set()


# --------------------------------------------------------------------------- C6.5 sin negaciones (16a, 16b, 16c)


@given(frase_con_atributo_no_disponible())
def test_p16a_atributo_no_disponible_siempre_se_rechaza(frase: str) -> None:
    """Regla 1: comuna, previsión o NSE, con cualquier escritura y cualquier negación alrededor, rechaza."""
    assert atributo_no_disponible(analisis_con_justificacion(frase)) is not None, frase


@given(frase_inasistencia_con_bajada())
def test_p16b_inasistencia_con_bajada_siempre_se_marca(frase: str) -> None:
    """Regla 2: inasistencia + cualquier forma de bajada en la oración marca, haya o no negaciones."""
    a = analisis_con_justificacion(frase)
    assert atributo_no_disponible(a) is None, frase
    marcas = frases_revision_equidad(a)
    assert [(m.campo, m.texto) for m in marcas] == [("justificacion", frase)], frase


@given(
    paquetes(),
    st.one_of(frase_con_atributo_no_disponible(), frase_inasistencia_con_bajada(), st.sampled_from(RELLENO_C65)),
    st.sampled_from(["justificacion", "resumen", "nota_preconsulta", "acciones_sugeridas"]),
)
def test_p16c_validar_es_idempotente_y_la_marca_no_toca_lo_del_modelo(
    p: PaqueteBarrido, frase: str, campo: str
) -> None:
    entrada = entrada_valida(p)
    entrada[campo] = [frase] if campo == "acciones_sugeridas" else frase
    v1 = validar_salida(entrada, p, _meta(p))
    if not v1.valido:
        assert v1.motivo_rechazo is not None and v1.motivo_rechazo.startswith(MOTIVO_EQUIDAD)
        assert validar_salida(entrada, p, _meta(p)) == v1
        return
    assert v1.analisis is not None
    # La marca es metadato del sistema: los campos que escribió el modelo quedan tal cual.
    del_sistema = {"riesgo_poblacional", "version_esquema"}  # C6.3 y valor por defecto del esquema
    autor = entrada_de_analisis(v1.analisis)
    assert {k: v for k, v in autor.items() if k not in del_sistema} == {
        k: v for k, v in json.loads(json.dumps(entrada)).items() if k not in del_sistema
    }
    v2 = validar_salida(entrada_de_analisis(v1.analisis), p, _meta(p))
    assert v2.valido and v2.analisis == v1.analisis and v2.revision_equidad == v1.revision_equidad
    assert [c for c in v2.correcciones if c.tipo == "revision_equidad"] == [
        c for c in v1.correcciones if c.tipo == "revision_equidad"
    ]
    assert len(v1.revision_equidad) == sum(1 for c in v1.correcciones if c.tipo == "revision_equidad")
