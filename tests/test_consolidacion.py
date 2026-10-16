"""Consolidación (F0006): sumar un periodo y correr el pipeline deja lo mismo que recalcular todo de cero.

Prueba clave: con el dataset partido en dos exportaciones (scripts/exportaciones_demo.py),
  cargar el periodo 1 → consolidar (historia completa) → sumar el periodo 2 → consolidar (solo lo afectado)
deja la serie nocturna y las propuestas IDÉNTICAS a cargar el dataset entero y consolidar una sola vez.

Requiere PostgreSQL (HLF_TEST_DATABASE_URL) y el dataset.
"""
import importlib.util
import os
import threading
from datetime import date

import pandas as pd
import pytest

from db import carga, conexion, esquema
from priorizacion.config import DATA_DIR, RAIZ
from priorizacion.consolidacion import CANDADO, consolidar
from priorizacion.datos import Repositorio
from priorizacion.registro_postgres import RegistroPostgres

URL = os.environ.get("HLF_TEST_DATABASE_URL")
pytestmark = [pytest.mark.datos,
              pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")]
CORTES = [date(2026, 6, 30), date(2026, 10, 13)]
SIN_PROGRESO = {"progreso": lambda *_: None}


def _exportaciones():
    spec = importlib.util.spec_from_file_location("exportaciones_demo", RAIZ / "scripts" / "exportaciones_demo.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def periodos(tmp_path_factory):
    return _exportaciones().partir(DATA_DIR, CORTES, tmp_path_factory.mktemp("buzon"))


def _limpiar():
    with conexion.conectar(URL) as c:
        carga.borrar(c, "todos")
        with c.transaction():
            for nombre in esquema.ESQUEMAS:
                esquema.aplicar(c, nombre)


def _serie(registro) -> pd.DataFrame:
    s = registro.serie().drop(columns=["id_serie"], errors="ignore")
    return s.sort_values(["fecha", "id_solicitud"]).reset_index(drop=True)


def _propuestas(registro) -> set:
    p = registro.propuestas()
    return set(p[["id_solicitud", "fecha_corte", "prioridad_propuesta", "alerta", "origen"]]
               .astype(str).itertuples(index=False, name=None))


@pytest.fixture(scope="module")
def completo():
    """Referencia: el dataset entero cargado de una vez y consolidado una sola vez."""
    _limpiar()
    with conexion.conectar(URL) as c:
        carga.cargar(c, DATA_DIR, **SIN_PROGRESO)
    registro = RegistroPostgres(URL)
    res = consolidar(Repositorio.desde_postgres(URL), registro, origen="completo", hasta=CORTES[-1])
    return {"serie": _serie(registro), "propuestas": _propuestas(registro), "resultado": res}


@pytest.fixture(scope="module")
def sumado(completo, periodos):
    """El camino de producción: periodo 1, consolidar, sumar periodo 2, consolidar solo lo afectado."""
    p1, p2 = periodos
    _limpiar()
    with conexion.conectar(URL) as c:
        carga.cargar(c, p1, **SIN_PROGRESO)
    registro = RegistroPostgres(URL)
    primera = consolidar(Repositorio.desde_postgres(URL), registro, origen="completo", hasta=CORTES[0])
    with conexion.conectar(URL) as c:
        previa = carga.vista_previa(c, p2, (date(2026, 7, 1), CORTES[1]), cargado_por="administradora")
        aplicada = carga.aplicar_incremental(c, previa["id_carga"], p2)
    segunda = consolidar(Repositorio.desde_postgres(URL), registro, origen="carga",
                         afectados=set(aplicada["pacientes_afectados"]), id_carga=aplicada["id_carga"])
    return {"serie": _serie(registro), "propuestas": _propuestas(registro), "primera": primera,
            "segunda": segunda, "aplicada": aplicada, "registro": registro}


def test_sumar_un_periodo_da_la_misma_serie_que_recalcular_todo(completo, sumado):
    assert sumado["segunda"]["modo"] == "incremental"
    assert sumado["segunda"]["fecha_corte"] == CORTES[1].isoformat()     # la fecha de corte viene de los datos
    pd.testing.assert_frame_equal(sumado["serie"], completo["serie"], check_dtype=False)


def test_y_las_mismas_propuestas(completo, sumado):
    assert sumado["propuestas"] == completo["propuestas"]


def test_solo_se_recalcula_lo_afectado(sumado):
    seg = sumado["segunda"]
    n_sol = sumado["serie"]["id_solicitud"].nunique()
    assert 0 < seg["solicitudes_recalculadas"] < n_sol                    # no se rehízo todo
    assert seg["pacientes_afectados"] == len(sumado["aplicada"]["pacientes_afectados"])


def test_la_bitacora_registra_origen_y_carga(sumado):
    corridas = sumado["registro"].corridas()
    ultimas = corridas.sort_values("id_corrida").tail(2)
    assert list(ultimas["origen"]) == ["completo", "carga"]
    assert list(ultimas["estado"]) == ["completa", "completa"]
    assert int(ultimas.iloc[-1]["id_carga"]) == sumado["aplicada"]["id_carga"]
    assert not sumado["registro"].corrida_en_curso()


def test_estimaciones_a_la_fecha_de_corte(sumado):
    todas = sumado["registro"].estimaciones()
    assert set(todas["fecha_calculo"]) == {c.isoformat() for c in CORTES}   # una por fecha de corte: queda el histórico
    est = todas[todas["fecha_calculo"] == CORTES[1].isoformat()]
    assert len(est) == sumado["segunda"]["estimaciones"] > 0
    assert (est["dias_estimados_max"] >= est["dias_estimados_min"]).all()
    assert not est["publicable"].astype(bool).any()


def test_una_corrida_a_la_vez(sumado):
    registro = sumado["registro"]
    tomado, soltar = threading.Event(), threading.Event()

    def ocupar():
        with registro.candado(CANDADO):
            tomado.set()
            soltar.wait(10)

    hilo = threading.Thread(target=ocupar)
    hilo.start()
    tomado.wait(10)
    resultado = {}
    segunda = threading.Thread(target=lambda: resultado.update(
        consolidar(Repositorio.desde_postgres(URL), registro, origen="solicitud")))
    try:
        segunda.start()
        segunda.join(3)
        assert segunda.is_alive() and not resultado         # espera su turno: no corre en paralelo
        assert registro.corrida_en_curso()                   # y la bitácora lo muestra
    finally:
        soltar.set()
        hilo.join()
        segunda.join(120)
    assert resultado["evaluaciones"] == 0                    # nada nuevo: la serie ya estaba al día
    assert not registro.corrida_en_curso()
