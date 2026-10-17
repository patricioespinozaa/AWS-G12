"""Persistencia en RDS (F0005 fase A): el registro PostgreSQL se comporta igual que el de SQLite.

Requiere PostgreSQL (HLF_TEST_DATABASE_URL) y el dataset.
"""
import os
import threading
from datetime import date

import pandas as pd
import pytest

from db import carga, conexion, esquema
from priorizacion.archivos import ArchivoGuardado
from priorizacion.bandeja import construir_bandeja
from priorizacion.config import DATA_DIR
from priorizacion.datos import Repositorio
from priorizacion.explicacion import explicacion_plantilla
from priorizacion.motor import evaluar
from priorizacion.nocturno import calcular_posiciones
from priorizacion.registro import RegistroSQLite
from priorizacion.registro_postgres import RegistroPostgres

URL = os.environ.get("HLF_TEST_DATABASE_URL")
pytestmark = [pytest.mark.datos,
              pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")]
CORTE = date(2026, 8, 10)


@pytest.fixture(scope="module")
def repo():
    return Repositorio.desde_csv()


@pytest.fixture
def pg():
    with conexion.conectar(URL) as c:
        carga.borrar(c, "todos")
        with c.transaction():
            for nombre in esquema.ESQUEMAS:
                esquema.aplicar(c, nombre)
        carga.cargar(c, DATA_DIR, progreso=lambda *_: None)
    return RegistroPostgres(URL)


@pytest.fixture
def sqlite(tmp_path):
    return RegistroSQLite(tmp_path / "registro.sqlite")


def _operar(registro, repo):
    """La misma secuencia de escrituras que hace la app, sobre cualquier implementación."""
    sol = repo.solicitudes["IC-HLF-00002"]
    r = evaluar(sol, repo.historias[sol.id_paciente], CORTE)
    pid = registro.guardar_propuesta(r, "huella", explicacion_plantilla(r), "plantilla", "validacion")
    registro.registrar_decision(pid, r, "acepta", r.nivel_propuesto, "Acepta la propuesta", "administradora")
    archivo = ArchivoGuardado("examen.pdf", "a" * 64, "application/pdf", "examen.pdf")
    ide = registro.agregar_evidencia("PAC-HLF-00028", date(2026, 10, 1), "PHQ9", 21, "Clínica", archivo,
                                     date(2026, 10, 2))
    registro.revisar_evidencia(ide, "validada", "administradora", "ok")
    idm = registro.agregar_mensaje("PAC-HLF-00001", date(2026, 10, 3), "sintoma_alarma", "Dolor")
    registro.revisar_mensaje(idm, "validada", "administradora")
    registro.agregar_mensaje("PAC-HLF-00001", date(2026, 10, 4), "confirma_asistencia", "")
    filas = pd.DataFrame([{"fecha": "2026-08-10", "id_solicitud": s.id_solicitud, "id_paciente": s.id_paciente,
                           "especialidad": s.especialidad, "puntaje": 10.5, "puntaje_nivel": 9.0,
                           "nivel_propuesto": "alta", "prioridad_vigente": "media",
                           "prioridad_inicial": s.prioridad_inicial, "cambio": "sube", "alerta": 1,
                           "motivo_principal": "prueba", "fecha_ingreso": s.fecha_ingreso.isoformat()}
                          for s in list(repo.solicitudes.values())[:5]])
    registro.reemplazar_serie(calcular_posiciones(filas))
    registro.registrar_corrida(inicio="2026-10-15T10:00:00", fin="2026-10-15T10:00:05", desde="2025-04-21",
                               hasta="2026-10-13", alcance="prueba", version_reglas="v", n_evaluaciones=5,
                               n_propuestas=1, segundos=5.0)
    return pid


def _forma(df: pd.DataFrame) -> dict:
    return {c: pd.api.types.infer_dtype(df[c], skipna=True) for c in df.columns}


def test_mismo_formato_que_sqlite(pg, sqlite, repo):
    pid_pg, pid_sq = _operar(pg, repo), _operar(sqlite, repo)
    for metodo in ("evidencias", "mensajes", "decisiones", "propuestas", "serie", "serie_resumen", "corridas"):
        a, b = getattr(sqlite, metodo)(), getattr(pg, metodo)()
        assert list(a.columns) == list(b.columns), metodo
        assert len(a) == len(b), metodo
        assert _forma(a) == _forma(b), (metodo, _forma(a), _forma(b))
    assert list(sqlite.factores(pid_sq).columns) == list(pg.factores(pid_pg).columns)
    assert pg.decisiones_por_solicitud().keys() == sqlite.decisiones_por_solicitud().keys()


def test_decision_persiste_y_otra_tarea_la_ve(pg, repo):
    otra = RegistroPostgres(URL)                       # otra tarea del backend, con su propia conexión
    antes = otra.version()
    _operar(pg, repo)
    assert otra.version() != antes                     # la otra tarea sabe que debe refrescar
    d = otra.decisiones("IC-HLF-00002")
    assert d.iloc[0]["usuario"] == "administradora"
    nueva = RegistroPostgres(URL)                      # "reinicio": una instancia nueva lee lo mismo
    assert len(nueva.decisiones()) == 1 and len(nueva.evidencias()) == 1


def test_bandeja_igual_en_local_y_en_rds(pg, sqlite):
    local = construir_bandeja(Repositorio.desde_csv(), sqlite, date(2026, 10, 13))[0]
    rds = construir_bandeja(Repositorio.desde_postgres(URL), pg, date(2026, 10, 13))[0]
    columnas = ["id_solicitud", "nivel_propuesto", "posicion_dinamica", "posicion_estatica", "alerta"]
    a = local[columnas].sort_values("id_solicitud").reset_index(drop=True)
    b = rds[columnas].sort_values("id_solicitud").reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_decisiones_concurrentes_no_se_pierden(pg, repo):
    sols = list(repo.solicitudes.values())[:20]
    errores = []

    def decidir(lote):
        reg = RegistroPostgres(URL)
        try:
            for s in lote:
                r = evaluar(s, repo.historias[s.id_paciente], max(s.fecha_ingreso, CORTE))
                pid = reg.guardar_propuesta(r, "h", "x", "plantilla", "validacion")
                reg.registrar_decision(pid, r, "rechaza", r.prioridad_vigente, "Prueba de concurrencia", "administradora")
        except Exception as e:  # noqa: BLE001
            errores.append(e)

    hilos = [threading.Thread(target=decidir, args=(sols[i::2],)) for i in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert not errores
    assert len(pg.decisiones()) == 20


def test_la_decision_sin_motivo_la_rechaza_la_base(pg, repo):
    import psycopg
    sol = repo.solicitudes["IC-HLF-00002"]
    r = evaluar(sol, repo.historias[sol.id_paciente], CORTE)
    pid = pg.guardar_propuesta(r, "h", "x", "plantilla", "validacion")
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.registrar_decision(pid, r, "acepta", r.nivel_propuesto, "", "administradora")
