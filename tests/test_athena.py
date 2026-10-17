"""Capa S3 + Athena (db/athena.py) con clientes AWS simulados en memoria.

No necesita credenciales de AWS. La exportación del historial se prueba contra PostgreSQL si hay base de prueba
(HLF_TEST_DATABASE_URL, igual que tests/test_db.py).
"""
import io
import json
import os
from datetime import date
from decimal import Decimal

import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402

from db import athena, carga  # noqa: E402
from db.__main__ import main as cli  # noqa: E402
from priorizacion.config import DATA_DIR  # noqa: E402

CFG = athena.Config(bucket="hlf-prueba", prefijo="hlf", workgroup="wg", base_prefijo="hlf")


class S3Falso:
    def __init__(self):
        self.objetos: dict[str, dict] = {}
        self.subidas = 0

    def put_object(self, Bucket, Key, Body, ContentType, Metadata=None):
        self.objetos[Key] = {"Body": Body, "Metadata": Metadata or {}, "ContentType": ContentType}
        self.subidas += 1

    def head_object(self, Bucket, Key):
        if Key not in self.objetos:
            raise Exception("An error occurred (404) when calling the HeadObject operation: Not Found")
        return {"Metadata": self.objetos[Key]["Metadata"]}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objetos[Key]["Body"])}


class AthenaFalsa:
    """Responde según el inicio del SQL. `respuestas`: lista de (prefijo, columnas[(nombre, tipo)], filas, estado)."""

    def __init__(self, respuestas=(), filas_por_pagina=2):
        self.respuestas = list(respuestas)
        self.pedidos: list[dict] = []
        self.filas_por_pagina = filas_por_pagina

    def _respuesta(self, sql):
        for prefijo, cols, filas, estado in self.respuestas:
            if sql.startswith(prefijo):
                return cols, filas, estado
        return [], [], "SUCCEEDED"

    def start_query_execution(self, **pedido):
        self.pedidos.append(pedido)
        return {"QueryExecutionId": f"q{len(self.pedidos)}"}

    def get_query_execution(self, QueryExecutionId):
        sql = self.pedidos[int(QueryExecutionId[1:]) - 1]["QueryString"]
        _, _, estado = self._respuesta(sql)
        tipo = "DML" if athena.es_solo_lectura(sql) else "DDL"
        return {"QueryExecution": {"Status": {"State": estado, "StateChangeReason": "SYNTAX_ERROR"},
                                   "StatementType": tipo,
                                   "Statistics": {"DataScannedInBytes": 1234, "TotalExecutionTimeInMillis": 56}}}

    def get_paginator(self, _):
        falsa = self

        class Paginador:
            def paginate(self, QueryExecutionId):
                sql = falsa.pedidos[int(QueryExecutionId[1:]) - 1]["QueryString"]
                cols, filas, _ = falsa._respuesta(sql)
                info = [{"Name": n, "Type": t} for n, t in cols]
                celdas = [[{"VarCharValue": n} for n, _ in cols]] + [
                    [{} if v is None else {"VarCharValue": v} for v in f] for f in filas]
                for i in range(0, max(len(celdas), 1), falsa.filas_por_pagina):
                    yield {"ResultSet": {"ResultSetMetadata": {"ColumnInfo": info},
                                         "Rows": [{"Data": c} for c in celdas[i:i + falsa.filas_por_pagina]]}}
        return Paginador()

    def stop_query_execution(self, QueryExecutionId):
        pass


def _leer_parquet(datos: bytes):
    return pq.read_table(io.BytesIO(datos))


# -- Parquet ------------------------------------------------------------------------------------------
@pytest.mark.datos
def test_parquet_con_tipos_exactos():
    datos = carga.leer_todo(DATA_DIR)
    tablas = {t.nombre: t for t in carga.TABLAS}
    med = _leer_parquet(athena.parquet(tablas["mediciones"], datos["mediciones"]))
    assert med.schema.field("valor").type == pa.decimal128(12, 3)
    assert med.num_rows == 2487
    assert med.column("valor").to_pylist() == [f[3] for f in datos["mediciones"]]     # Decimal exacto
    agenda = _leer_parquet(athena.parquet(tablas["agenda_box"], datos["agenda_box"]))
    assert agenda.column("bloque_inicio")[0].as_py() == "08:30"                      # Athena no tiene time
    pac = _leer_parquet(athena.parquet(tablas["pacientes"], datos["pacientes"]))
    vivos = [d for d, f in zip(pac.column("fecha_defuncion").to_pylist(), pac.column("fallecido").to_pylist()) if not f]
    assert vivos and all(d is None for d in vivos)                                    # NULL, no cadena vacía
    assert pac.schema.field("id_paciente").nullable is False


def test_valor_que_no_cabe_exacto_falla():
    with pytest.raises(carga.ErrorCarga, match="exacto"):
        athena._valor("numeric", Decimal("1.2345"), "mediciones", "valor")


# -- S3 -----------------------------------------------------------------------------------------------
@pytest.mark.datos
def test_descargar_csv_verificados(tmp_path):
    s3 = S3Falso()
    athena.subir(s3, CFG, DATA_DIR, progreso=lambda *_: None)
    bajados = athena.descargar_csv(s3, CFG, tmp_path / "dataset", progreso=lambda *_: None)
    assert sorted(bajados) == sorted(t.archivo for t in carga.TABLAS if t.archivo)
    assert (tmp_path / "dataset" / "lista_espera.csv").read_bytes() == (DATA_DIR / "lista_espera.csv").read_bytes()
    assert carga.leer_todo(tmp_path / "dataset")["mediciones"] == carga.leer_todo(DATA_DIR)["mediciones"]


@pytest.mark.datos
def test_descargar_csv_alterado_no_deja_nada(tmp_path):
    s3 = S3Falso()
    athena.subir(s3, CFG, DATA_DIR, progreso=lambda *_: None)
    s3.objetos["hlf/csv/pacientes.csv"]["Body"] += b"PAC-HLF-99999,Intruso,30,F,X,Y,Z,false,\n"
    with pytest.raises(carga.ErrorCarga, match="sha256"):
        athena.descargar_csv(s3, CFG, tmp_path / "dataset", progreso=lambda *_: None)
    assert not (tmp_path / "dataset").exists() or not any((tmp_path / "dataset").iterdir())


@pytest.mark.datos
def test_descargar_csv_manifiesto_incompleto(tmp_path):
    s3 = S3Falso()
    athena.subir(s3, CFG, DATA_DIR, progreso=lambda *_: None)
    manifiesto = athena.leer_manifiesto(s3, CFG)
    del manifiesto["csv_sha256"]["citaciones.csv"]
    s3.objetos["hlf/parquet/_manifiesto.json"]["Body"] = json.dumps(manifiesto).encode()
    with pytest.raises(carga.ErrorCarga, match="citaciones.csv"):
        athena.descargar_csv(s3, CFG, tmp_path / "dataset", progreso=lambda *_: None)


@pytest.mark.datos
def test_subir_es_idempotente():
    s3 = S3Falso()
    res = athena.subir(s3, CFG, DATA_DIR, progreso=lambda *_: None)
    assert "hlf/parquet/mediciones/mediciones.parquet" in s3.objetos
    assert "hlf/csv/pacientes.csv" in s3.objetos
    assert res["manifiesto"]["filas"]["citaciones"] == 257
    assert len(res["subidos"]) == 13                                  # 6 CSV + 7 Parquet
    otra = athena.subir(s3, CFG, DATA_DIR, progreso=lambda *_: None)
    assert otra["subidos"] == []                                      # nada cambió: no se resube
    assert athena.leer_manifiesto(s3, CFG)["filas"] == res["manifiesto"]["filas"]


# -- DDL ----------------------------------------------------------------------------------------------
def test_ddl_raw_e_historial():
    sql = "\n".join(athena.ddl(CFG))
    assert "CREATE EXTERNAL TABLE hlf_raw.mediciones" in sql and "valor decimal(12,3)" in sql
    assert "LOCATION 's3://hlf-prueba/hlf/parquet/mediciones/'" in sql
    assert "bloque_inicio string" in sql
    assert "CREATE EXTERNAL TABLE hlf_historial.serie_nocturna" in sql
    assert "PARTITIONED BY (fecha date)" in sql
    assert "'storage.location.template' = 's3://hlf-prueba/hlf/historial/serie_nocturna/fecha=${fecha}/'" in sql
    assert sql.count("'projection.enabled' = 'true'") == len(athena.HISTORIAL)


# -- Consultas ----------------------------------------------------------------------------------------
def test_literales_para_parametros():
    assert athena.literal("O'Higgins") == "'O''Higgins'"
    assert athena.literal(date(2026, 6, 1)) == "DATE '2026-06-01'"
    assert athena.literal(None) == "NULL" and athena.literal(True) == "true"
    assert athena.literal(Decimal("7.2")) == "7.2" and athena.literal(3) == "3"


@pytest.mark.parametrize("sql,ok", [
    ("SELECT 1", True), ("  -- comentario\nWITH x AS (SELECT 1) SELECT * FROM x", True),
    ("/* bloque */ show tables", True), ("DROP TABLE hlf_raw.pacientes", False),
    ("/* SELECT */ INSERT INTO x VALUES (1)", False), ("", False),
])
def test_solo_lectura(sql, ok):
    assert athena.es_solo_lectura(sql) is ok


def test_resultados_tipados_y_paginados():
    cols = [("id", "varchar"), ("n", "bigint"), ("valor", "decimal"), ("fecha", "date"), ("activo", "boolean")]
    filas = [("PAC-1", "3", "7.200", "2026-06-01", "true"), ("PAC-2", "5", None, "2026-06-02", "false"),
             ("PAC-3", "8", "10.100", None, "true")]
    cliente = AthenaFalsa([("SELECT", cols, filas, "SUCCEEDED")], filas_por_pagina=2)
    res = athena.Athena(CFG, cliente).ejecutar("SELECT * FROM t WHERE id = ? AND fecha <= ?",
                                               ["PAC-1", date(2026, 6, 1)])
    assert res.columnas == ["id", "n", "valor", "fecha", "activo"]
    assert res.filas[0] == ("PAC-1", 3, Decimal("7.200"), date(2026, 6, 1), True)
    assert res.filas[1][2] is None and res.filas[2][3] is None
    assert len(res.filas) == 3                                        # la cabecera solo se salta en la 1.ª página
    pedido = cliente.pedidos[0]
    assert pedido["ExecutionParameters"] == ["'PAC-1'", "DATE '2026-06-01'"]
    assert pedido["WorkGroup"] == "wg" and pedido["QueryExecutionContext"] == {"Database": "hlf_raw"}


def test_consulta_fallida():
    cliente = AthenaFalsa([("SELECT", [], [], "FAILED")])
    with pytest.raises(RuntimeError, match="SYNTAX_ERROR"):
        athena.Athena(CFG, cliente).ejecutar("SELECT x FROM nada")


@pytest.mark.datos
def test_publicar_y_verificar_de_punta_a_punta():
    s3 = S3Falso()
    conteos = [(t.nombre, "bigint") for t in carga.TABLAS]
    filas = {"pacientes": 500, "lista_espera": 500, "eventos_clinicos": 786, "mediciones": 2487, "box": 20,
             "agenda_box": 2188, "citaciones": 257}
    cliente = AthenaFalsa([
        ("SELECT (SELECT count(*) FROM hlf_raw.pacientes)", conteos, [tuple(str(filas[n]) for n, _ in conteos)], "SUCCEEDED"),
        ("SELECT (SELECT count(*) FROM hlf_raw.lista_espera x", [(f"h{i}", "bigint") for i in range(6)],
         [tuple("0" for _ in range(6))], "SUCCEEDED"),
        ("SELECT valor", [("valor", "decimal")], [("4.000",)], "SUCCEEDED"),
        ("SELECT count(DISTINCT fecha)", [("n", "bigint"), ("min", "date"), ("max", "date")],
         [("0", None, None)], "SUCCEEDED"),
    ])
    chequeos = athena.publicar(CFG, DATA_DIR, progreso=lambda *_: None, s3=s3, athena=athena.Athena(CFG, cliente))
    assert all(c.ok for c in chequeos if not c.informativo), [c for c in chequeos if not c.ok]
    ddl = [p["QueryString"] for p in cliente.pedidos if p["QueryString"].startswith("CREATE EXTERNAL")]
    assert len(ddl) == len(carga.TABLAS) + len(athena.HISTORIAL)


def test_cli_rechaza_sql_de_escritura(monkeypatch, capsys):
    monkeypatch.setenv("HLF_S3_BUCKET", "hlf-prueba")
    monkeypatch.setattr(athena, "clientes", lambda cfg: (S3Falso(), AthenaFalsa()))
    assert cli(["athena", "consultar", "DROP TABLE hlf_raw.pacientes"]) == 2
    assert "Solo se permiten" in capsys.readouterr().err


# -- Exportación del historial (requiere PostgreSQL) --------------------------------------------------
URL = os.environ.get("HLF_TEST_DATABASE_URL")


@pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")
@pytest.mark.datos
def test_exportar_historial_particionado():
    from db import conexion, esquema
    with conexion.conectar(URL) as conn:
        carga.borrar(conn, "todos")
        with conn.transaction():
            for nombre in esquema.ESQUEMAS:
                esquema.aplicar(conn, nombre)
        carga.cargar(conn, DATA_DIR, progreso=lambda *_: None)
        for dia, pos in ((date(2026, 6, 1), 9), (date(2026, 6, 2), 3)):
            conn.execute("""INSERT INTO priorizacion.serie_nocturna VALUES ('IC-HLF-00001', %s, NULL, 72.5, 70,
                            'alta', 'media', 'sube', true, 'urgencia', %s, 12, 120)""", (dia, pos))
        conn.execute("""INSERT INTO priorizacion.estimacion_espera VALUES ('IC-HLF-00001', '2026-06-02', NULL, 'alta',
                        3, 120, 14, 35, 'media', 'm', 'v1', true)""")
        conn.commit()
        s3 = S3Falso()
        res = athena.exportar_historial(conn, s3, CFG, date(2026, 1, 1), date(2026, 12, 31), progreso=lambda *_: None)
        assert res == {"serie_nocturna": 2, "estimacion_espera": 1}
        clave = "hlf/historial/serie_nocturna/fecha=2026-06-02/serie_nocturna.parquet"
        tabla = _leer_parquet(s3.objetos[clave]["Body"])
        fila = tabla.to_pylist()[0]
        assert fila["posicion_dinamica"] == 3 and fila["puntaje"] == Decimal("72.500")
        assert fila["especialidad"] and fila["prioridad_inicial"] in ("alta", "media", "baja")   # desnormalizado
        assert "fecha" not in tabla.column_names                    # la fecha va en la ruta (partición)
        antes = s3.subidas
        athena.exportar_historial(conn, s3, CFG, date(2026, 1, 1), date(2026, 12, 31), progreso=lambda *_: None)
        assert s3.subidas == antes                                  # repetir no resube lo que no cambió
