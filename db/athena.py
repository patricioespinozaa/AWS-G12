"""Copia de consulta del esquema raw en S3 + Athena (docs/feature/F0003-consultas-s3-athena.md).

RDS sigue siendo la base operativa (priorizacion y canal necesitan transacciones, llaves y triggers).
Aquí se publican los mismos datos de raw como Parquet tipado en S3 para consultarlos con SQL en Athena:
EDA, KPIs y consultas puntuales sin depender de que la instancia RDS esté encendida.

Por qué Parquet y no el CSV directo: Athena sobre CSV interpreta los tipos al leer y deja NULL lo que no
puede convertir, sin avisar. El Parquet se genera con los mismos conversores y validaciones que la carga a
RDS (db/carga.py), así que los tipos son exactos: fechas como date y valores como decimal, nunca float.

Organización en el bucket (HLF_S3_BUCKET, prefijo HLF_S3_PREFIJO):
    <prefijo>/csv/<archivo>.csv                  CSV originales (el versionado del bucket guarda la historia)
    <prefijo>/parquet/<tabla>/<tabla>.parquet    una carpeta por tabla: es la LOCATION de la tabla en Athena
    <prefijo>/parquet/_manifiesto.json           filas por tabla y sha256 de cada CSV y Parquet
    <prefijo>/historial/<tabla>/fecha=AAAA-MM-DD/<tabla>.parquet
                                                 serie nocturna y estimación de espera exportadas desde RDS,
                                                 una partición por noche (flujo D)
    <prefijo>/kb/…                               documentos de la Knowledge Base (los escribe la Lambda de
                                                 preparación; quedan registrados en consulta.documento_kb)
Los resultados de Athena van a la ubicación del workgroup (db/infra/crear_s3_athena.sh).

Bases en el Glue Data Catalog: <HLF_ATHENA_DB>_raw (tablas de raw) y <HLF_ATHENA_DB>_historial (particionadas por
fecha con partition projection: Athena encuentra cada noche nueva sin MSCK REPAIR ni crawlers).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time as reloj
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from .carga import TABLAS, ErrorCarga, Tabla, huellas, leer_todo
from .conexion import ErrorConfiguracion
from .verificacion import Chequeo

# mediciones.valor: decimal exacto. El dataset tiene a lo más 1 decimal y valores < 1000.
PRECISION, ESCALA = 12, 3
TIPOS_ATHENA = {"text": "string", "int": "int", "bool": "boolean", "date": "date",
                "time": "string",                 # Athena no tiene tipo time: se guarda 'HH:MM'
                "numeric": f"decimal({PRECISION},{ESCALA})"}
# Relaciones de raw (las mismas FK del DDL de PostgreSQL), para buscar huérfanos en Athena
RELACIONES = (("lista_espera", "id_paciente", "pacientes"), ("eventos_clinicos", "id_paciente", "pacientes"),
              ("mediciones", "id_paciente", "pacientes"), ("citaciones", "id_paciente", "pacientes"),
              ("agenda_box", "id_box", "box"), ("citaciones", "id_box", "box"))
SOLO_LECTURA = ("select", "with", "show", "describe", "explain", "values")
INICIO_PROYECCION = "2025-01-01"            # primera fecha posible del historial (el dataset parte en 2025-04)


@dataclass(frozen=True)
class Historial:
    """Una tabla de priorizacion exportada a S3 por noche. `sql` recibe %(fecha)s y devuelve `columnas` en orden."""
    nombre: str
    sql: str
    columnas: tuple[tuple[str, str], ...]     # tipos: text, int, bool, dec (decimal(8,3))


# Se desnormaliza especialidad y prioridad_inicial: en la capa de análisis evita un join por consulta
HISTORIAL = (
    Historial("serie_nocturna", """
        SELECT s.id_solicitud, le.id_paciente, le.especialidad, le.prioridad_inicial, s.puntaje, s.puntaje_nivel,
               s.nivel_propuesto, s.prioridad_vigente, s.cambio, s.alerta, s.motivo_principal,
               s.posicion_dinamica, s.posicion_estatica, s.total_cola
        FROM priorizacion.serie_nocturna s JOIN raw.lista_espera le USING (id_solicitud)
        WHERE s.fecha = %(fecha)s ORDER BY le.especialidad, s.posicion_dinamica""",
              (("id_solicitud", "text"), ("id_paciente", "text"), ("especialidad", "text"),
               ("prioridad_inicial", "text"), ("puntaje", "dec"), ("puntaje_nivel", "dec"),
               ("nivel_propuesto", "text"), ("prioridad_vigente", "text"), ("cambio", "text"), ("alerta", "bool"),
               ("motivo_principal", "text"), ("posicion_dinamica", "int"), ("posicion_estatica", "int"),
               ("total_cola", "int"))),
    Historial("estimacion_espera", """
        SELECT e.id_solicitud, le.especialidad, e.prioridad_vigente, e.posicion_vigente, e.total_cola,
               e.dias_estimados_min, e.dias_estimados_max, e.confianza, e.metodo, e.version_metodo, e.publicable
        FROM priorizacion.estimacion_espera e JOIN raw.lista_espera le USING (id_solicitud)
        WHERE e.fecha_calculo = %(fecha)s ORDER BY le.especialidad, e.posicion_vigente""",
              (("id_solicitud", "text"), ("especialidad", "text"), ("prioridad_vigente", "text"),
               ("posicion_vigente", "int"), ("total_cola", "int"), ("dias_estimados_min", "int"),
               ("dias_estimados_max", "int"), ("confianza", "text"), ("metodo", "text"),
               ("version_metodo", "text"), ("publicable", "bool"))),
)
TIPOS_HISTORIAL_ATHENA = {"text": "string", "int": "int", "bool": "boolean", "dec": "decimal(8,3)"}


@dataclass(frozen=True)
class Config:
    bucket: str
    prefijo: str = "hlf"
    workgroup: str = "hlf-priorizacion"
    base_prefijo: str = "hlf"
    region: str | None = None

    @classmethod
    def desde_entorno(cls) -> "Config":
        bucket = os.environ.get("HLF_S3_BUCKET")
        if not bucket:
            raise ErrorConfiguracion("Define HLF_S3_BUCKET (lo imprime db/infra/crear_s3_athena.sh)")
        return cls(bucket=bucket, prefijo=os.environ.get("HLF_S3_PREFIJO", "hlf").strip("/"),
                   workgroup=os.environ.get("HLF_ATHENA_WORKGROUP", "hlf-priorizacion"),
                   base_prefijo=os.environ.get("HLF_ATHENA_DB", "hlf"),
                   region=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))

    @property
    def base(self) -> str:
        return f"{self.base_prefijo}_raw"

    @property
    def base_historial(self) -> str:
        return f"{self.base_prefijo}_historial"

    def clave(self, *partes: str) -> str:
        return "/".join([self.prefijo, *partes])

    def ubicacion(self, tabla: str) -> str:
        return f"s3://{self.bucket}/{self.clave('parquet', tabla)}/"

    def ubicacion_historial(self, tabla: str) -> str:
        return f"s3://{self.bucket}/{self.clave('historial', tabla)}/"


def clientes(cfg: Config):
    try:
        import boto3
    except ImportError as e:
        raise ErrorConfiguracion("S3 y Athena requieren boto3: pip install boto3") from e
    sesion = boto3.Session(region_name=cfg.region)
    return sesion.client("s3"), sesion.client("athena")


# -- Parquet -----------------------------------------------------------------------------------------
def _esquema_arrow(t: Tabla):
    import pyarrow as pa
    tipos = {"text": pa.string(), "int": pa.int32(), "bool": pa.bool_(), "date": pa.date32(),
             "time": pa.string(), "numeric": pa.decimal128(PRECISION, ESCALA)}
    return pa.schema([pa.field(c, tipos[tipo], nullable=c not in t.llave) for c, tipo in t.columnas])


def _valor(tipo: str, v, tabla: str, col: str):
    if v is None:
        return None
    if tipo == "time":
        return v.strftime("%H:%M")
    if tipo == "numeric":
        if -v.as_tuple().exponent > ESCALA or abs(v) >= Decimal(10) ** (PRECISION - ESCALA):
            raise ErrorCarga(f"{tabla}.{col}: {v} no cabe exacto en decimal({PRECISION},{ESCALA})")
        return v
    return v


def parquet(t: Tabla, filas: list[tuple]) -> bytes:
    """Una tabla de raw como Parquet con tipos exactos (mismos datos que se cargan en RDS)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    columnas = {c: [_valor(tipo, f[i], t.nombre, c) for f in filas] for i, (c, tipo) in enumerate(t.columnas)}
    tabla = pa.Table.from_pydict(columnas, schema=_esquema_arrow(t))
    salida = io.BytesIO()
    pq.write_table(tabla, salida, compression="snappy")
    return salida.getvalue()


def _sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


# -- S3 ----------------------------------------------------------------------------------------------
def _subir_si_cambio(s3, cfg: Config, clave: str, datos: bytes, tipo: str) -> bool:
    """Sube solo si el contenido cambió (sha256 en los metadatos del objeto). Devuelve True si subió."""
    huella = _sha256(datos)
    try:
        actual = s3.head_object(Bucket=cfg.bucket, Key=clave).get("Metadata", {}).get("sha256")
    except Exception as e:  # noqa: BLE001 — 404 de botocore: el objeto no existe
        if "404" not in str(e) and "Not Found" not in str(e) and "NoSuchKey" not in str(e):
            raise
        actual = None
    if actual == huella:
        return False
    s3.put_object(Bucket=cfg.bucket, Key=clave, Body=datos, ContentType=tipo, Metadata={"sha256": huella})
    return True


def subir(s3, cfg: Config, data_dir: Path, progreso=print) -> dict:
    """Valida los CSV, genera el Parquet y sube ambos a S3. Idempotente: no resube lo que no cambió."""
    progreso(f"Leyendo y validando CSV desde {data_dir}")
    datos = leer_todo(data_dir)                  # mismas conversiones y errores que la carga a RDS
    manifiesto = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "origen": str(data_dir),
                  "filas": {}, "csv_sha256": huellas(data_dir), "parquet_sha256": {}}
    subidos = []
    for t in TABLAS:
        if t.archivo and _subir_si_cambio(s3, cfg, cfg.clave("csv", t.archivo),
                                          (data_dir / t.archivo).read_bytes(), "text/csv"):
            subidos.append(t.archivo)
        cuerpo = parquet(t, datos[t.nombre])
        manifiesto["filas"][t.nombre] = len(datos[t.nombre])
        manifiesto["parquet_sha256"][t.nombre] = _sha256(cuerpo)
        cambio = _subir_si_cambio(s3, cfg, cfg.clave("parquet", t.nombre, f"{t.nombre}.parquet"), cuerpo,
                                  "application/vnd.apache.parquet")
        if cambio:
            subidos.append(f"{t.nombre}.parquet")
        progreso(f"  {t.nombre:<17} {len(datos[t.nombre]):>6} filas  {'subido' if cambio else 'sin cambios'}")
    # El manifiesto se sube al final: si algo falla antes, sigue describiendo los archivos anteriores
    s3.put_object(Bucket=cfg.bucket, Key=cfg.clave("parquet", "_manifiesto.json"),
                  Body=json.dumps(manifiesto, ensure_ascii=False, indent=2).encode("utf-8"),
                  ContentType="application/json")
    return {"manifiesto": manifiesto, "subidos": subidos}


def leer_manifiesto(s3, cfg: Config) -> dict:
    cuerpo = s3.get_object(Bucket=cfg.bucket, Key=cfg.clave("parquet", "_manifiesto.json"))["Body"].read()
    return json.loads(cuerpo)


def descargar_csv(s3, cfg: Config, destino: Path, progreso=print) -> list[str]:
    """Baja los CSV publicados a `destino` y verifica cada uno contra el sha256 del manifiesto.

    Lo usa el contenedor del backend al arrancar (docker/backend/entrypoint.sh): los datos del hospital
    nunca van dentro de la imagen. Primero verifica todos los archivos y solo entonces escribe: si uno no
    coincide con el manifiesto, no queda en disco un dataset a medias.
    """
    huellas_publicadas = leer_manifiesto(s3, cfg)["csv_sha256"]
    esperados = {t.archivo for t in TABLAS if t.archivo}
    if faltan := esperados - set(huellas_publicadas):
        raise ErrorCarga(f"El manifiesto no incluye {', '.join(sorted(faltan))}: vuelve a correr athena publicar")
    verificados: dict[str, bytes] = {}
    for archivo, huella in sorted(huellas_publicadas.items()):
        cuerpo = s3.get_object(Bucket=cfg.bucket, Key=cfg.clave("csv", archivo))["Body"].read()
        if _sha256(cuerpo) != huella:
            raise ErrorCarga(f"{archivo}: el sha256 no coincide con el manifiesto publicado")
        verificados[archivo] = cuerpo
    destino.mkdir(parents=True, exist_ok=True)
    for archivo, cuerpo in verificados.items():
        (destino / archivo).write_bytes(cuerpo)
        progreso(f"  {archivo:<22} {len(cuerpo) / 1024:>8.1f} KB")
    return list(verificados)


# -- DDL de Athena -----------------------------------------------------------------------------------
def ddl(cfg: Config) -> list[str]:
    """Base y tablas externas sobre el Parquet. DROP de una tabla externa no borra datos en S3."""
    sentencias = [f"CREATE DATABASE IF NOT EXISTS {cfg.base} "
                  f"COMMENT 'Copia de consulta del esquema raw del HLF (Parquet en S3). Origen: python -m db athena publicar'"]
    for t in TABLAS:
        cols = ",\n  ".join(f"{c} {TIPOS_ATHENA[tipo]}" for c, tipo in t.columnas)
        sentencias.append(f"DROP TABLE IF EXISTS {cfg.base}.{t.nombre}")
        sentencias.append(f"CREATE EXTERNAL TABLE {cfg.base}.{t.nombre} (\n  {cols}\n)\n"
                          f"STORED AS PARQUET\nLOCATION '{cfg.ubicacion(t.nombre)}'\n"
                          f"TBLPROPERTIES ('parquet.compression' = 'SNAPPY')")
    sentencias.append(f"CREATE DATABASE IF NOT EXISTS {cfg.base_historial} "
                      f"COMMENT 'Historial nocturno exportado desde RDS, particionado por fecha'")
    for h in HISTORIAL:
        cols = ",\n  ".join(f"{c} {TIPOS_HISTORIAL_ATHENA[tipo]}" for c, tipo in h.columnas)
        ubic = cfg.ubicacion_historial(h.nombre)
        sentencias.append(f"DROP TABLE IF EXISTS {cfg.base_historial}.{h.nombre}")
        sentencias.append(
            f"CREATE EXTERNAL TABLE {cfg.base_historial}.{h.nombre} (\n  {cols}\n)\n"
            f"PARTITIONED BY (fecha date)\nSTORED AS PARQUET\nLOCATION '{ubic}'\n"
            f"TBLPROPERTIES (\n"
            f"  'projection.enabled' = 'true',\n"
            f"  'projection.fecha.type' = 'date',\n"
            f"  'projection.fecha.format' = 'yyyy-MM-dd',\n"
            f"  'projection.fecha.range' = '{INICIO_PROYECCION},NOW',\n"
            f"  'projection.fecha.interval' = '1',\n"
            f"  'projection.fecha.interval.unit' = 'DAYS',\n"
            f"  'storage.location.template' = '{ubic}fecha=${{fecha}}/',\n"
            f"  'parquet.compression' = 'SNAPPY'\n)")
    return sentencias


# -- Exportación del historial (flujo D) -------------------------------------------------------------
def _parquet_historial(h: Historial, filas: list[tuple]) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq
    tipos = {"text": pa.string(), "int": pa.int32(), "bool": pa.bool_(), "dec": pa.decimal128(8, 3)}
    esquema = pa.schema([pa.field(c, tipos[t]) for c, t in h.columnas])
    datos = {c: [f[i] for f in filas] for i, (c, _) in enumerate(h.columnas)}
    salida = io.BytesIO()
    pq.write_table(pa.Table.from_pydict(datos, schema=esquema), salida, compression="snappy")
    return salida.getvalue()


def exportar_historial(conn, s3, cfg: Config, desde: date, hasta: date, progreso=print) -> dict[str, int]:
    """Exporta desde RDS una partición por noche y tabla. Idempotente: repetir una fecha la reemplaza."""
    exportadas: dict[str, int] = {}
    for h in HISTORIAL:
        col_fecha = "fecha" if h.nombre == "serie_nocturna" else "fecha_calculo"
        fechas = [r[0] for r in conn.execute(
            f"SELECT DISTINCT {col_fecha} FROM priorizacion.{h.nombre} WHERE {col_fecha} BETWEEN %s AND %s ORDER BY 1",
            (desde, hasta)).fetchall()]
        for f in fechas:
            filas = conn.execute(h.sql, {"fecha": f}).fetchall()
            _subir_si_cambio(s3, cfg, cfg.clave("historial", h.nombre, f"fecha={f.isoformat()}", f"{h.nombre}.parquet"),
                             _parquet_historial(h, filas), "application/vnd.apache.parquet")
        exportadas[h.nombre] = len(fechas)
        progreso(f"  {h.nombre:<18} {len(fechas):>4} noches ({desde} a {hasta})")
    return exportadas


# -- Publicación desde RDS (F0006) -------------------------------------------------------------------
def leer_rds(conn) -> dict[str, list[tuple]]:
    """raw tal como está en RDS (la suma de todas las versiones), en el orden de columnas de cada Tabla."""
    return {t.nombre: conn.execute(f"SELECT {', '.join(c for c, _ in t.columnas)} FROM raw.{t.nombre} "
                                   f"ORDER BY {', '.join(t.llave)}").fetchall() for t in TABLAS}


def subir_desde_rds(conn, s3, cfg: Config, progreso=print) -> dict:
    """Publica el Parquet de raw desde RDS. Con cargas por periodo (F0005) los CSV de una exportación son solo
    un periodo: la copia de consulta se arma con lo que hay en la base, no con un archivo. Idempotente."""
    datos = leer_rds(conn)
    try:
        previo = leer_manifiesto(s3, cfg)
    except Exception:  # noqa: BLE001 — primera publicación
        previo = {}
    version = conn.execute("SELECT coalesce(max(version), 0) FROM raw.carga_lote WHERE estado = 'aplicada'").fetchone()[0]
    manifiesto = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "origen": f"rds (versión de datos {version})", "filas": {},
                  # los CSV publicados (si los hay) siguen siendo los de la última publicación desde archivos
                  "csv_sha256": previo.get("csv_sha256", {}), "parquet_sha256": {}}
    subidos = []
    for t in TABLAS:
        cuerpo = parquet(t, datos[t.nombre])
        manifiesto["filas"][t.nombre] = len(datos[t.nombre])
        manifiesto["parquet_sha256"][t.nombre] = _sha256(cuerpo)
        if _subir_si_cambio(s3, cfg, cfg.clave("parquet", t.nombre, f"{t.nombre}.parquet"), cuerpo,
                            "application/vnd.apache.parquet"):
            subidos.append(t.nombre)
    s3.put_object(Bucket=cfg.bucket, Key=cfg.clave("parquet", "_manifiesto.json"),
                  Body=json.dumps(manifiesto, ensure_ascii=False, indent=2).encode("utf-8"),
                  ContentType="application/json")
    progreso(f"  raw desde RDS: {len(subidos)} tablas cambiaron ({', '.join(subidos) or 'ninguna'})")
    return {"manifiesto": manifiesto, "subidos": subidos}


def exportar_noches(conn, s3, cfg: Config, noches: set, fecha_corte: date, progreso=print) -> dict[str, int]:
    """Exporta solo las particiones que cambiaron: las noches tocadas por la consolidación y la estimación del
    corte. Exportar el historial completo cada noche subiría cientos de particiones iguales."""
    fechas = {"serie_nocturna": sorted(date.fromisoformat(str(n)) for n in noches),
              "estimacion_espera": [fecha_corte]}
    exportadas: dict[str, int] = {}
    for h in HISTORIAL:
        n = 0
        for f in fechas[h.nombre]:
            filas = conn.execute(h.sql, {"fecha": f}).fetchall()
            if filas and _subir_si_cambio(s3, cfg, cfg.clave("historial", h.nombre, f"fecha={f.isoformat()}",
                                                              f"{h.nombre}.parquet"),
                                          _parquet_historial(h, filas), "application/vnd.apache.parquet"):
                n += 1
        exportadas[h.nombre] = n
        progreso(f"  {h.nombre:<18} {n:>4} particiones subidas")
    return exportadas


def publicador_consolidacion(cfg: Config | None = None, url: str | None = None):
    """La función `publicar(noches, fecha_corte)` del pipeline de consolidación (priorizacion/consolidacion.py).
    Las tablas de Athena ya existen (python -m db athena publicar); el historial usa partition projection, así
    que cada noche nueva se ve sin DDL."""
    from .conexion import conectar
    cfg = cfg or Config.desde_entorno()

    def publicar(noches: set, fecha_corte: date) -> dict:
        s3, _ = clientes(cfg)
        with conectar(url) as conn:
            raw = subir_desde_rds(conn, s3, cfg, progreso=lambda *_: None)
            historial = exportar_noches(conn, s3, cfg, noches, fecha_corte, progreso=lambda *_: None)
        return {"raw_subidas": raw["subidos"], "particiones": historial}
    return publicar


# -- Consultas ---------------------------------------------------------------------------------------
@dataclass
class Resultado:
    columnas: list[str]
    filas: list[tuple]
    id_consulta: str
    bytes_escaneados: int = 0
    milisegundos: int = 0
    tipos: list[str] = field(default_factory=list)

    def como_dicts(self) -> list[dict]:
        return [dict(zip(self.columnas, f)) for f in self.filas]


def literal(v) -> str:
    """Valor de Python como literal SQL de Athena, para ExecutionParameters (consultas parametrizadas)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, Decimal)):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, datetime):
        return f"TIMESTAMP '{v.isoformat(sep=' ')}'"
    if isinstance(v, date):
        return f"DATE '{v.isoformat()}'"
    return "'" + str(v).replace("'", "''") + "'"


_CONVERTIR = {
    "varchar": str, "char": str, "string": str,
    "integer": int, "bigint": int, "smallint": int, "tinyint": int,
    "boolean": lambda s: s == "true", "date": date.fromisoformat, "decimal": Decimal,
    "double": float, "float": float, "real": float,
    "timestamp": lambda s: datetime.fromisoformat(s.replace(" ", "T")),
}


def _convertir(tipo: str, v):
    if v is None:
        return None
    return _CONVERTIR.get(tipo.split("(")[0].lower(), str)(v)


def es_solo_lectura(sql: str) -> bool:
    limpio = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip().lower()
    return limpio.split(None, 1)[0] in SOLO_LECTURA if limpio else False


class Athena:
    def __init__(self, cfg: Config, cliente=None, espera_max: float = 300):
        self.cfg = cfg
        self.cliente = cliente if cliente is not None else clientes(cfg)[1]
        self.espera_max = espera_max

    def ejecutar(self, sql: str, parametros: list | tuple | None = None) -> Resultado:
        pedido = {"QueryString": sql, "WorkGroup": self.cfg.workgroup,
                  "QueryExecutionContext": {"Database": self.cfg.base}}
        if parametros:
            pedido["ExecutionParameters"] = [literal(p) for p in parametros]
        id_consulta = self.cliente.start_query_execution(**pedido)["QueryExecutionId"]
        espera, inicio = 0.25, reloj.monotonic()
        while True:
            ejec = self.cliente.get_query_execution(QueryExecutionId=id_consulta)["QueryExecution"]
            estado = ejec["Status"]["State"]
            if estado == "SUCCEEDED":
                break
            if estado in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"Athena {estado}: {ejec['Status'].get('StateChangeReason', '')}")
            if reloj.monotonic() - inicio > self.espera_max:
                self.cliente.stop_query_execution(QueryExecutionId=id_consulta)
                raise TimeoutError(f"La consulta {id_consulta} superó {self.espera_max} s y se canceló")
            reloj.sleep(espera)
            espera = min(espera * 2, 2)
        stats = ejec.get("Statistics", {})
        res = Resultado([], [], id_consulta, stats.get("DataScannedInBytes", 0),
                        stats.get("TotalExecutionTimeInMillis", 0))
        if ejec.get("StatementType") != "DML":         # DDL y utilidades no devuelven filas
            return res
        primera = True
        for pagina in self.cliente.get_paginator("get_query_results").paginate(QueryExecutionId=id_consulta):
            info = pagina["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
            if not res.columnas:
                res.columnas = [c["Name"] for c in info]
                res.tipos = [c["Type"] for c in info]
            filas = pagina["ResultSet"]["Rows"]
            if primera:                                # en un SELECT, la primera fila son los nombres
                filas, primera = filas[1:], False
            for fila in filas:
                res.filas.append(tuple(_convertir(tipo, celda.get("VarCharValue"))
                                       for tipo, celda in zip(res.tipos, fila["Data"])))
        return res


def crear_tablas(athena: Athena, progreso=print) -> list[str]:
    hechas = []
    for sql in ddl(athena.cfg):
        athena.ejecutar(sql)
        if sql.startswith("CREATE EXTERNAL"):
            hechas.append(sql.split()[3])
    for base in (athena.cfg.base, athena.cfg.base_historial):
        progreso(f"  {base}: {', '.join(t.split('.')[1] for t in hechas if t.startswith(base + '.'))}")
    return hechas


def verificar(athena: Athena, manifiesto: dict) -> list[Chequeo]:
    """Conteos contra el manifiesto y huérfanos, en 3 consultas para no pagar el mínimo por consulta 13 veces."""
    b = athena.cfg.base
    chequeos = [Chequeo("Publicación", True, f"{manifiesto['generado']} desde {manifiesto['origen']}", informativo=True)]
    conteos = athena.ejecutar("SELECT " + ", ".join(
        f"(SELECT count(*) FROM {b}.{t.nombre}) AS {t.nombre}" for t in TABLAS)).como_dicts()[0]
    for t in TABLAS:
        esperadas = manifiesto["filas"].get(t.nombre)
        chequeos.append(Chequeo(f"Filas {b}.{t.nombre}", conteos[t.nombre] == esperadas,
                                f"{conteos[t.nombre]} (esperadas {esperadas})"))
    huerfanos = athena.ejecutar("SELECT " + ", ".join(
        f"(SELECT count(*) FROM {b}.{h} x WHERE NOT EXISTS "
        f"(SELECT 1 FROM {b}.{p} y WHERE y.{c} = x.{c})) AS h{i}"
        for i, (h, c, p) in enumerate(RELACIONES))).filas[0]
    for (h, c, p), n in zip(RELACIONES, huerfanos):
        chequeos.append(Chequeo(f"Huérfanos {h}.{c} → {p}", n == 0, str(n)))
    tipos = athena.ejecutar(f"SELECT valor FROM {b}.mediciones LIMIT 1")
    chequeos.append(Chequeo("Tipo exacto de mediciones.valor", tipos.tipos[:1] == ["decimal"],
                            ", ".join(tipos.tipos) or "sin filas"))
    noches = athena.ejecutar(f"SELECT count(DISTINCT fecha), min(fecha), max(fecha) "
                             f"FROM {athena.cfg.base_historial}.serie_nocturna").filas[0]
    chequeos.append(Chequeo("Historial nocturno en S3", True,
                            f"{noches[0]} noches ({noches[1]} a {noches[2]})" if noches[0] else
                            "vacío: python -m db athena exportar", informativo=True))
    return chequeos


def publicar(cfg: Config, data_dir: Path | None, progreso=print, s3=None, athena: Athena | None = None,
             conn_rds=None) -> list[Chequeo]:
    """Sube CSV y Parquet a S3, (re)crea las tablas en Athena y verifica. Con `conn_rds`, el Parquet sale de lo
    que hay en RDS (la suma de las cargas por periodo) en vez de una carpeta de CSV."""
    if s3 is None or athena is None:
        s3_def, athena_def = clientes(cfg)
        s3 = s3 or s3_def
        athena = athena or Athena(cfg, athena_def)
    res = subir_desde_rds(conn_rds, s3, cfg, progreso) if conn_rds is not None else subir(s3, cfg, data_dir, progreso)
    progreso("Tablas en Athena:")
    crear_tablas(athena, progreso)
    return verificar(athena, res["manifiesto"])
