"""Consolidación nocturna con buzón (F0006): las exportaciones que llegan solas se suman y se consolidan.

Las pruebas del buzón (carpeta local y S3 simulado) no necesitan base ni dataset. Las de la noche completa usan
PostgreSQL (HLF_TEST_DATABASE_URL) y el dataset partido en tres exportaciones (scripts/exportaciones_demo.py).
"""
import csv
import importlib.util
import io
import json
import os
from datetime import date

import pytest

from servicios.nocturno import buzon as B

URL = os.environ.get("HLF_TEST_DATABASE_URL")
CORTES = [date(2026, 6, 30), date(2026, 9, 30), date(2026, 10, 13)]


# -- buzón ----------------------------------------------------------------------------------------------
def _entrega(raiz, nombre, periodo=None, archivos=("eventos_clinicos.csv",)):
    carpeta = raiz / nombre
    carpeta.mkdir(parents=True)
    for a in archivos:
        (carpeta / a).write_text("id\n1\n", encoding="utf-8")
    if periodo is not None:
        (carpeta / B.PERIODO).write_text(json.dumps(periodo), encoding="utf-8")
    return carpeta


def test_buzon_local_en_orden_y_con_periodo(tmp_path):
    _entrega(tmp_path, "2026-09-30", {"desde": "2026-07-01", "hasta": "2026-09-30"})
    _entrega(tmp_path, "2026-06-30")
    (tmp_path / "vacia").mkdir()                                  # sin CSV: no es una entrega
    buzon = B.BuzonLocal(tmp_path)
    entregas = buzon.entregas()
    assert [e.nombre for e in entregas] == ["2026-06-30", "2026-09-30"]
    d = buzon.descargar(entregas[1])
    try:
        assert d.periodo == (date(2026, 7, 1), date(2026, 9, 30))
        assert set(d.huellas) == {"eventos_clinicos.csv"} and d.carpeta != tmp_path / "2026-09-30"
    finally:
        d.limpiar()
    assert buzon.descargar(entregas[0]).periodo == (None, None)
    assert B.BuzonLocal(tmp_path / "no-existe").entregas() == []


def test_periodo_invalido(tmp_path):
    _entrega(tmp_path, "x", {"desde": "2026-09-30", "hasta": "2026-07-01"})
    with pytest.raises(B.ErrorBuzon, match="termina antes"):
        B.BuzonLocal(tmp_path).descargar(B.BuzonLocal(tmp_path).entregas()[0])


class S3Listable:
    def __init__(self, objetos: dict[str, bytes]):
        self.objetos = objetos

    def get_paginator(self, _):
        return self

    def paginate(self, Bucket, Prefix, Delimiter=None):
        claves = sorted(k for k in self.objetos if k.startswith(Prefix))
        if Delimiter:
            prefijos = sorted({Prefix + k[len(Prefix):].split("/")[0] + "/" for k in claves if "/" in k[len(Prefix):]})
            return [{"CommonPrefixes": [{"Prefix": p} for p in prefijos]}]
        return [{"Contents": [{"Key": k} for k in claves]}]

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objetos[Key])}


class S3Guardado:
    """S3 en memoria para la publicación (put/head/get)."""

    def __init__(self):
        self.objetos: dict[str, dict] = {}

    def put_object(self, Bucket, Key, Body, ContentType, Metadata=None):
        self.objetos[Key] = {"Body": Body, "Metadata": Metadata or {}}

    def head_object(self, Bucket, Key):
        if Key not in self.objetos:
            raise Exception("An error occurred (404) when calling the HeadObject operation: Not Found")
        return {"Metadata": self.objetos[Key]["Metadata"]}

    def get_object(self, Bucket, Key):
        if Key not in self.objetos:
            raise Exception("NoSuchKey")
        return {"Body": io.BytesIO(self.objetos[Key]["Body"])}


def test_buzon_s3():
    s3 = S3Listable({"hlf/entrada/2026-09-30/eventos_clinicos.csv": b"a\n1\n",
                     "hlf/entrada/2026-09-30/periodo.json": b'{"desde": null, "hasta": "2026-09-30"}',
                     "hlf/entrada/2026-09-30/viejo/eventos_clinicos.csv": b"no se lee",
                     "hlf/entrada/2026-06-30/pacientes.csv": b"b\n2\n",
                     "hlf/cargas/1/pacientes.csv": b"fuera del buzon"})
    buzon = B.BuzonS3("bucket", "hlf", cliente=s3)
    entregas = buzon.entregas()
    assert [(e.nombre, e.uri) for e in entregas] == [("2026-06-30", "s3://bucket/hlf/entrada/2026-06-30/"),
                                                      ("2026-09-30", "s3://bucket/hlf/entrada/2026-09-30/")]
    d = buzon.descargar(entregas[1])
    try:
        assert d.periodo == (None, date(2026, 9, 30))
        assert [p.name for p in d.carpeta.iterdir()] == ["eventos_clinicos.csv"]   # solo el primer nivel
    finally:
        d.limpiar()


def test_buzon_desde_config(monkeypatch, tmp_path):
    from priorizacion import config
    monkeypatch.setattr(config, "BUZON_LOCAL", str(tmp_path))
    assert isinstance(B.desde_config(), B.BuzonLocal)
    monkeypatch.setattr(config, "BUZON_LOCAL", "")
    monkeypatch.setattr(config, "S3_BUCKET", "b")
    assert str(B.desde_config()) == "s3://b/hlf/entrada/"
    monkeypatch.setattr(config, "S3_BUCKET", "")
    assert B.desde_config() is None


def test_cli_requiere_la_base(monkeypatch, capsys):
    from servicios.nocturno.__main__ import main
    monkeypatch.delenv("HLF_DATABASE_URL", raising=False)
    monkeypatch.delenv("HLF_DB_SECRET_ID", raising=False)
    assert main([]) == 2
    assert "requiere la base" in capsys.readouterr().err


# -- una noche completa (PostgreSQL + dataset) ------------------------------------------------------------
def _partir(destino):
    from priorizacion.config import DATA_DIR, RAIZ
    spec = importlib.util.spec_from_file_location("exportaciones_demo", RAIZ / "scripts" / "exportaciones_demo.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.partir(DATA_DIR, CORTES, destino)


def _vaciar():
    from db import carga, conexion
    with conexion.conectar(URL) as c:
        carga.borrar(c, "todos")


@pytest.fixture(scope="module")
def noche(tmp_path_factory):
    """Tres exportaciones en el buzón y una base vacía: la primera noche las suma todas y consolida."""
    from servicios.nocturno.proceso import correr
    raiz = tmp_path_factory.mktemp("buzon")
    _partir(raiz)
    _vaciar()
    buzon = B.BuzonLocal(raiz)
    return {"buzon": buzon, "raiz": raiz, "primera": correr(buzon, url=URL, autoconfirmar=True)}


@pytest.mark.datos
@pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")
def test_la_noche_suma_las_entregas_en_orden_y_consolida(noche):
    from db import carga, conexion
    res = noche["primera"]
    assert [(e["entrega"], e["estado"], e["version"]) for e in res["exportaciones"]] == \
        [(c.isoformat(), "aplicada", i) for i, c in enumerate(CORTES, start=1)]
    assert res["fecha_corte"] == CORTES[-1].isoformat() and not res["con_errores"]
    assert res["modo"] == "completo" and res["estimaciones"] > 0         # base vacía: historia completa
    with conexion.conectar(URL) as c:
        h = carga.historial(c)
        assert {x["cargado_por"] for x in h} == {"consolidacion_nocturna"}
        assert h[0]["periodo_hasta"] == CORTES[-1]


@pytest.mark.datos
@pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")
def test_sin_entregas_nuevas_igual_queda_en_la_bitacora(noche):
    from priorizacion.registro_postgres import RegistroPostgres
    from servicios.nocturno.proceso import correr
    res = correr(noche["buzon"], url=URL, autoconfirmar=True)
    assert res["sin_exportaciones_nuevas"] and res["exportaciones"] == []
    assert res["modo"] == "incremental" and res["evaluaciones"] == 0       # nada nuevo que simular
    ultima = RegistroPostgres(URL).corridas().sort_values("id_corrida").iloc[-1]
    assert ultima["origen"] == "nocturno" and ultima["estado"] == "completa"


@pytest.mark.datos
@pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")
def test_entrega_con_errores_queda_fallida_y_detiene_las_siguientes(noche, tmp_path):
    from db import carga, conexion
    from servicios.nocturno.proceso import correr
    with (noche["raiz"] / "2026-10-13" / "eventos_clinicos.csv").open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        columnas, fila = lector.fieldnames, next(lector)
    mala = _entrega(tmp_path, "2026-10-20", {"desde": "2026-10-14", "hasta": "2026-10-20"}, archivos=())
    with (mala / "eventos_clinicos.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerow(dict(fila, id_evento="EV-999999", id_paciente="PAC-NO-EXISTE"))
    siguiente = _entrega(tmp_path, "2026-10-27")
    res = correr(B.BuzonLocal(tmp_path), url=URL, autoconfirmar=True)
    assert [e["estado"] for e in res["exportaciones"]] == ["fallida"]       # la siguiente no se intentó
    assert res["con_errores"] and "PAC-NO-EXISTE" in json.dumps(res["exportaciones"])
    assert res["fecha_corte"] == CORTES[-1].isoformat()                    # la fecha de corte no avanzó
    with conexion.conectar(URL) as c:
        assert carga.historial(c)[0]["estado"] == "fallida"
    # La noche siguiente no repite la entrega fallida (mismos archivos): espera que el HLF la corrija
    otra = correr(B.BuzonLocal(tmp_path), url=URL, autoconfirmar=True)
    assert [e["entrega"] for e in otra["exportaciones"]] == [siguiente.name]


@pytest.mark.datos
@pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")
def test_publicacion_en_athena_desde_rds(noche):
    pytest.importorskip("pyarrow")
    from db import athena, conexion
    s3 = S3Guardado()
    cfg = athena.Config(bucket="hlf-prueba")
    with conexion.conectar(URL) as c:
        res = athena.subir_desde_rds(c, s3, cfg, progreso=lambda *_: None)
        assert res["manifiesto"]["filas"]["lista_espera"] == c.execute("SELECT count(*) FROM raw.lista_espera").fetchone()[0]
        assert athena.subir_desde_rds(c, s3, cfg, progreso=lambda *_: None)["subidos"] == []   # idempotente
        n = athena.exportar_noches(c, s3, cfg, {"2026-10-12", "2026-10-13"}, CORTES[-1], progreso=lambda *_: None)
    assert n == {"serie_nocturna": 2, "estimacion_espera": 1}
    assert "hlf/historial/serie_nocturna/fecha=2026-10-13/serie_nocturna.parquet" in s3.objetos
