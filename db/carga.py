"""Carga de los CSV del HLF al esquema raw de PostgreSQL.

Todo ocurre en una sola transacción: si algo falla (archivo faltante, tipo inválido, llave duplicada,
restricción violada), la base queda como estaba. Se puede repetir cuantas veces haga falta con
--reemplazar, por ejemplo si la base se borra al final del día.

Primera carga: COPY directo. Recarga (--reemplazar con datos previos): sincronización por llave primaria
contra tablas temporales. Inserta lo nuevo, actualiza lo que cambió y borra lo que ya no está en los CSV.
Los esquemas priorizacion y canal referencian raw, así que no se puede vaciar con TRUNCATE: si una fila que
desaparece del CSV está referenciada por datos de la app, la carga falla y no se borra nada.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path

import psycopg

from . import esquema


class ErrorCarga(RuntimeError):
    pass


def _texto(v: str):
    return v if v != "" else None


def _entero(v: str):
    return int(Decimal(v)) if v != "" else None


def _booleano(v: str):
    v = v.strip().lower()
    if v not in ("true", "false"):
        raise ValueError(f"booleano inválido: {v!r}")
    return v == "true"


def _fecha(v: str):
    return date.fromisoformat(v) if v != "" else None


def _hora(v: str):
    return time.fromisoformat(v) if v != "" else None


def _numero(v: str):
    return Decimal(v) if v != "" else None


CONVERSORES = {"text": _texto, "int": _entero, "bool": _booleano, "date": _fecha, "time": _hora, "numeric": _numero}


@dataclass(frozen=True)
class Tabla:
    nombre: str
    archivo: str | None          # None = tabla derivada
    columnas: tuple[tuple[str, str], ...]
    llave: tuple[str, ...]       # PK, igual que en el DDL


# Orden de carga respetando las llaves foráneas. Debe coincidir con db/sql/raw/001_esquema_raw.sql
TABLAS: tuple[Tabla, ...] = (
    Tabla("pacientes", "pacientes.csv", (
        ("id_paciente", "text"), ("nombre_fantasia", "text"), ("edad", "int"), ("sexo", "text"),
        ("comuna", "text"), ("prevision", "text"), ("nivel_socioeconomico", "text"),
        ("fallecido", "bool"), ("fecha_defuncion", "date")), ("id_paciente",)),
    Tabla("lista_espera", "lista_espera.csv", (
        ("id_paciente", "text"), ("id_solicitud", "text"), ("especialidad", "text"), ("sub_especialidad", "text"),
        ("diagnostico_cie10", "text"), ("diagnostico_texto", "text"), ("prioridad_inicial", "text"),
        ("fecha_ingreso_lista", "date"), ("origen_derivacion", "text"), ("estado", "text")), ("id_solicitud",)),
    Tabla("eventos_clinicos", "eventos_clinicos.csv", (
        ("id_paciente", "text"), ("id_evento", "text"), ("fecha_evento", "date"), ("tipo_evento", "text"),
        ("subtipo", "text"), ("severidad", "text"), ("detalle", "text")), ("id_evento",)),
    Tabla("mediciones", "mediciones.csv", (
        ("id_paciente", "text"), ("fecha_medicion", "date"), ("tipo_medicion", "text"), ("valor", "numeric"),
        ("unidad", "text"), ("fuera_de_rango", "bool")), ("id_paciente", "fecha_medicion", "tipo_medicion")),
    Tabla("box", None, (("id_box", "text"),), ("id_box",)),
    Tabla("agenda_box", "agenda_box.csv", (
        ("id_box", "text"), ("fecha", "date"), ("especialidad", "text"), ("bloque_inicio", "time"),
        ("bloque_fin", "time"), ("capacidad_cupos", "int"), ("cupos_usados", "int"), ("minutos_sobretiempo", "int")),
        ("id_box", "fecha")),
    Tabla("citaciones", "citaciones.csv", (
        ("id_paciente", "text"), ("id_cita", "text"), ("id_box", "text"), ("fecha_cita", "date"),
        ("especialidad", "text"), ("estado_cita", "text"), ("minutos_atencion_real", "int")), ("id_cita",)),
)


def leer_tabla(tabla: Tabla, data_dir: Path) -> list[tuple]:
    """Lee un CSV, valida la cabecera y convierte cada valor al tipo de PostgreSQL."""
    ruta = data_dir / tabla.archivo
    if not ruta.exists():
        raise ErrorCarga(f"No existe {ruta}")
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        esperadas = [c for c, _ in tabla.columnas]
        if sorted(lector.fieldnames or []) != sorted(esperadas):
            raise ErrorCarga(f"{tabla.archivo}: columnas {lector.fieldnames}, se esperaban {esperadas}")
        filas = []
        for n, registro in enumerate(lector, start=2):
            try:
                filas.append(tuple(CONVERSORES[tipo](registro[col].strip()) for col, tipo in tabla.columnas))
            except (ValueError, ArithmeticError) as e:
                raise ErrorCarga(f"{tabla.archivo}, línea {n}: {e}") from e
    return filas


def leer_todo(data_dir: Path) -> dict[str, list[tuple]]:
    datos = {t.nombre: leer_tabla(t, data_dir) for t in TABLAS if t.archivo}
    # box: todos los id_box de la agenda y de las citas
    boxes = {f[0] for f in datos["agenda_box"]} | {f[2] for f in datos["citaciones"]}
    datos["box"] = [(b,) for b in sorted(boxes)]
    return datos


def huellas(data_dir: Path) -> dict[str, str]:
    return {t.archivo: hashlib.sha256((data_dir / t.archivo).read_bytes()).hexdigest() for t in TABLAS if t.archivo}


def filas_en_base(conn: psycopg.Connection) -> dict[str, int]:
    existentes = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'raw'").fetchall()}
    return {t.nombre: conn.execute(f"SELECT count(*) FROM raw.{t.nombre}").fetchone()[0]
            for t in TABLAS if t.nombre in existentes}


def _copiar(conn: psycopg.Connection, destino: str, t: Tabla, filas: list[tuple]):
    cols = ", ".join(c for c, _ in t.columnas)
    with conn.cursor().copy(f"COPY {destino} ({cols}) FROM STDIN") as copia:
        for fila in filas:
            copia.write_row(fila)


def _sincronizar(conn: psycopg.Connection, t: Tabla, filas: list[tuple]) -> dict[str, int]:
    """Inserta y actualiza raw.<tabla> desde `filas` sin vaciarla. El borrado de ausentes va aparte."""
    stg = f"stg_{t.nombre}"
    conn.execute(f"CREATE TEMP TABLE {stg} (LIKE raw.{t.nombre} INCLUDING DEFAULTS) ON COMMIT DROP")
    _copiar(conn, stg, t, filas)
    cols = [c for c, _ in t.columnas]
    resto = [c for c in cols if c not in t.llave]
    lista, llave = ", ".join(cols), ", ".join(t.llave)
    if resto:
        actualizar = (f"DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in resto)} "
                      f"WHERE ({', '.join(f'raw.{t.nombre}.{c}' for c in resto)}) "
                      f"IS DISTINCT FROM ({', '.join(f'EXCLUDED.{c}' for c in resto)})")
    else:
        actualizar = "DO NOTHING"
    # xmax = 0 distingue una fila insertada de una actualizada
    cambios = conn.execute(f"INSERT INTO raw.{t.nombre} ({lista}) SELECT {lista} FROM {stg} "
                           f"ON CONFLICT ({llave}) {actualizar} RETURNING (xmax = 0)").fetchall()
    return {"insertadas": sum(1 for (nueva,) in cambios if nueva),
            "actualizadas": sum(1 for (nueva,) in cambios if not nueva)}


def _borrar_ausentes(conn: psycopg.Connection, t: Tabla) -> int:
    """Borra de raw las filas que ya no están en los CSV. Falla si la app las referencia."""
    igual = " AND ".join(f"s.{c} = r.{c}" for c in t.llave)
    try:
        with conn.transaction():          # savepoint, para traducir el error a uno legible
            return conn.execute(f"DELETE FROM raw.{t.nombre} r WHERE NOT EXISTS "
                                f"(SELECT 1 FROM stg_{t.nombre} s WHERE {igual})").rowcount
    except psycopg.errors.ForeignKeyViolation as e:
        raise ErrorCarga(
            f"raw.{t.nombre}: hay filas que ya no están en los CSV pero las referencian datos de la app "
            f"({e.diag.message_detail or e}). No se borró nada: revisa el CSV o esos datos.") from e


def cargar(conn: psycopg.Connection, data_dir: Path, reemplazar: bool = False, progreso=print) -> dict:
    """Crea el esquema raw si falta y carga (o sincroniza) todas las tablas en una transacción."""
    inicio = datetime.now(timezone.utc)
    progreso(f"Leyendo CSV desde {data_dir}")
    datos = leer_todo(data_dir)
    cambios: dict[str, dict[str, int]] = {}
    with conn.transaction():
        esquema.aplicar(conn, "raw")
        previas = filas_en_base(conn)
        if not any(previas.values()):
            for t in TABLAS:
                _copiar(conn, f"raw.{t.nombre}", t, datos[t.nombre])
                cambios[t.nombre] = {"insertadas": len(datos[t.nombre]), "actualizadas": 0, "borradas": 0}
                progreso(f"  raw.{t.nombre:<17} {len(datos[t.nombre]):>6} filas")
        elif not reemplazar:
            raise ErrorCarga(f"El esquema raw ya tiene datos {previas}. Usa --reemplazar para recargarlo.")
        else:
            progreso("Sincronizando raw con los CSV (sin TRUNCATE: priorizacion y canal referencian raw)")
            for t in TABLAS:                          # padres primero
                cambios[t.nombre] = _sincronizar(conn, t, datos[t.nombre])
            for t in reversed(TABLAS):                # hijos primero
                cambios[t.nombre]["borradas"] = _borrar_ausentes(conn, t)
            for t in TABLAS:
                c = cambios[t.nombre]
                progreso(f"  raw.{t.nombre:<17} {len(datos[t.nombre]):>6} filas  "
                         f"(+{c['insertadas']} ~{c['actualizadas']} -{c['borradas']})")
        cargadas = filas_en_base(conn)
        esperadas = {t.nombre: len(datos[t.nombre]) for t in TABLAS}
        if cargadas != esperadas:
            raise ErrorCarga(f"Conteos no coinciden: base {cargadas} vs CSV {esperadas}")
        conn.execute("INSERT INTO raw.carga_lote (inicio, origen, filas, archivos) VALUES (%s, %s, %s, %s)",
                     (inicio, str(data_dir), json.dumps(cargadas), json.dumps(huellas(data_dir))))
    return {"filas": cargadas, "cambios": cambios,
            "segundos": round((datetime.now(timezone.utc) - inicio).total_seconds(), 1)}


def borrar(conn: psycopg.Connection, nombre: str) -> list[str]:
    """Elimina un esquema, o todos con nombre="todos" (DROP SCHEMA ... CASCADE).

    No borra un esquema del que depende otro que existe (canal → priorizacion → raw): el CASCADE
    eliminaría en silencio las llaves foráneas y los triggers de ese otro esquema.
    """
    with conn.transaction():
        existentes = esquema.existentes(conn)
        if nombre == "todos":
            objetivo = [e for e in reversed(esquema.ESQUEMAS) if e in existentes]
        else:
            dependientes = [e for e in esquema.dependientes(nombre) if e in existentes]
            if dependientes:
                varios = len(dependientes) > 1
                raise ErrorCarga(f"No se borra {nombre}: {' y '.join(dependientes)} "
                                 f"{'dependen' if varios else 'depende'} de él. "
                                 f"{'Bórralos' if varios else 'Bórralo'} antes o usa --esquema todos.")
            objetivo = [nombre] if nombre in existentes else []
        for e in objetivo:
            conn.execute(f"DROP SCHEMA {e} CASCADE")
    return objetivo
