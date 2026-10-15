"""Módulo db: lectura y conversión de los CSV (siempre) y carga real en PostgreSQL (si hay base de prueba).

Para correr las pruebas de integración, apunta a una base desechable:
    HLF_TEST_DATABASE_URL=postgresql://postgres@localhost:55432/hlf_test python -m pytest tests/test_db.py
"""
import os
import shutil
from datetime import date, time
from decimal import Decimal

import pytest

from db import carga, conexion
from priorizacion.config import DATA_DIR


def test_lee_y_convierte_los_csv():
    datos = carga.leer_todo(DATA_DIR)
    assert {t: len(f) for t, f in datos.items()} == {
        "pacientes": 500, "lista_espera": 500, "eventos_clinicos": 786, "mediciones": 2487,
        "agenda_box": 2188, "citaciones": 257, "box": 20}
    p = datos["pacientes"][0]
    assert isinstance(p[2], int) and isinstance(p[7], bool)
    assert all(f[8] is None for f in datos["pacientes"] if f[7] is False)          # vacío → NULL
    assert isinstance(datos["mediciones"][0][3], Decimal)
    assert datos["agenda_box"][0][3] == time(8, 30)
    assert isinstance(datos["lista_espera"][0][7], date)
    asistio = [f for f in datos["citaciones"] if f[5] == "asistio"]
    assert all(f[6] is not None for f in asistio)
    assert all(f[6] is None for f in datos["citaciones"] if f[5] != "asistio")


def test_cabecera_distinta_falla(tmp_path):
    (tmp_path / "pacientes.csv").write_text("id_paciente,edad\nPAC-1,30\n", encoding="utf-8")
    with pytest.raises(carga.ErrorCarga, match="columnas"):
        carga.leer_tabla(carga.TABLAS[0], tmp_path)


def test_booleano_invalido_falla():
    with pytest.raises(ValueError):
        carga.CONVERSORES["bool"]("si")


def test_url_sin_clave_al_mostrar():
    assert conexion.describir("postgresql://u:secreta@h:5432/b") == "postgresql://u:****@h:5432/b"


URL = os.environ.get("HLF_TEST_DATABASE_URL")
integracion = pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")


@integracion
def test_restaurar_es_repetible_y_verifica():
    from db import verificacion
    with conexion.conectar(URL) as conn:
        carga.borrar(conn)
        carga.cargar(conn, DATA_DIR, progreso=lambda *_: None)
        with pytest.raises(carga.ErrorCarga, match="--reemplazar"):
            carga.cargar(conn, DATA_DIR, progreso=lambda *_: None)
        res = carga.cargar(conn, DATA_DIR, reemplazar=True, progreso=lambda *_: None)
        assert res["filas"]["mediciones"] == 2487
        chequeos = verificacion.verificar(conn)
        assert all(c.ok for c in chequeos if not c.informativo)


@integracion
def test_error_en_un_csv_no_deja_carga_parcial(tmp_path):
    for t in carga.TABLAS:
        if t.archivo:
            shutil.copy(DATA_DIR / t.archivo, tmp_path / t.archivo)
    lineas = (tmp_path / "citaciones.csv").read_text(encoding="utf-8").splitlines()
    lineas.append(lineas[1])                      # id_cita duplicado → viola la PK al final de la carga
    (tmp_path / "citaciones.csv").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    with conexion.conectar(URL) as conn:
        carga.cargar(conn, DATA_DIR, reemplazar=True, progreso=lambda *_: None)
        antes = carga.filas_en_base(conn)
        with pytest.raises(Exception):
            carga.cargar(conn, tmp_path, reemplazar=True, progreso=lambda *_: None)
        conn.rollback()
        assert carga.filas_en_base(conn) == antes          # la transacción revirtió todo
