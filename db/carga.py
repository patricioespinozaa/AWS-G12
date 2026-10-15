"""Carga de los CSV del HLF al esquema raw de PostgreSQL.

Todo ocurre en una sola transacción: si algo falla (archivo faltante, tipo inválido, llave duplicada,
restricción violada), la base queda como estaba. Se puede repetir cuantas veces haga falta con
--reemplazar, por ejemplo si la base se borra al final del día.
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


# Orden de carga respetando las llaves foráneas. Debe coincidir con db/sql/raw/001_esquema_raw.sql
TABLAS: tuple[Tabla, ...] = (
    Tabla("pacientes", "pacientes.csv", (
        ("id_paciente", "text"), ("nombre_fantasia", "text"), ("edad", "int"), ("sexo", "text"),
        ("comuna", "text"), ("prevision", "text"), ("nivel_socioeconomico", "text"),
        ("fallecido", "bool"), ("fecha_defuncion", "date"))),
    Tabla("lista_espera", "lista_espera.csv", (
        ("id_paciente", "text"), ("id_solicitud", "text"), ("especialidad", "text"), ("sub_especialidad", "text"),
        ("diagnostico_cie10", "text"), ("diagnostico_texto", "text"), ("prioridad_inicial", "text"),
        ("fecha_ingreso_lista", "date"), ("origen_derivacion", "text"), ("estado", "text"))),
    Tabla("eventos_clinicos", "eventos_clinicos.csv", (
        ("id_paciente", "text"), ("id_evento", "text"), ("fecha_evento", "date"), ("tipo_evento", "text"),
        ("subtipo", "text"), ("severidad", "text"), ("detalle", "text"))),
    Tabla("mediciones", "mediciones.csv", (
        ("id_paciente", "text"), ("fecha_medicion", "date"), ("tipo_medicion", "text"), ("valor", "numeric"),
        ("unidad", "text"), ("fuera_de_rango", "bool"))),
    Tabla("box", None, (("id_box", "text"),)),
    Tabla("agenda_box", "agenda_box.csv", (
        ("id_box", "text"), ("fecha", "date"), ("especialidad", "text"), ("bloque_inicio", "time"),
        ("bloque_fin", "time"), ("capacidad_cupos", "int"), ("cupos_usados", "int"), ("minutos_sobretiempo", "int"))),
    Tabla("citaciones", "citaciones.csv", (
        ("id_paciente", "text"), ("id_cita", "text"), ("id_box", "text"), ("fecha_cita", "date"),
        ("especialidad", "text"), ("estado_cita", "text"), ("minutos_atencion_real", "int"))),
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


def cargar(conn: psycopg.Connection, data_dir: Path, reemplazar: bool = False, progreso=print) -> dict:
    """Crea el esquema si falta y carga todas las tablas en una transacción."""
    inicio = datetime.now(timezone.utc)
    progreso(f"Leyendo CSV desde {data_dir}")
    datos = leer_todo(data_dir)
    with conn.transaction():
        esquema.aplicar(conn, "raw")
        previas = filas_en_base(conn)
        if any(previas.values()):
            if not reemplazar:
                raise ErrorCarga(f"El esquema raw ya tiene datos {previas}. Usa --reemplazar para recargarlo.")
            progreso("Vaciando el esquema raw (TRUNCATE)")
            # Sin CASCADE: si otro esquema referencia raw, falla en vez de borrar datos ajenos
            conn.execute("TRUNCATE " + ", ".join(f"raw.{t.nombre}" for t in reversed(TABLAS)))
        for t in TABLAS:
            cols = ", ".join(c for c, _ in t.columnas)
            with conn.cursor().copy(f"COPY raw.{t.nombre} ({cols}) FROM STDIN") as copia:
                for fila in datos[t.nombre]:
                    copia.write_row(fila)
            progreso(f"  raw.{t.nombre:<17} {len(datos[t.nombre]):>6} filas")
        cargadas = filas_en_base(conn)
        esperadas = {t.nombre: len(datos[t.nombre]) for t in TABLAS}
        if cargadas != esperadas:
            raise ErrorCarga(f"Conteos no coinciden: base {cargadas} vs CSV {esperadas}")
        conn.execute("INSERT INTO raw.carga_lote (inicio, origen, filas, archivos) VALUES (%s, %s, %s, %s)",
                     (inicio, str(data_dir), json.dumps(cargadas), json.dumps(huellas(data_dir))))
    return {"filas": cargadas, "segundos": round((datetime.now(timezone.utc) - inicio).total_seconds(), 1)}


def borrar(conn: psycopg.Connection):
    """Elimina el esquema raw completo (DROP SCHEMA ... CASCADE)."""
    with conn.transaction():
        conn.execute("DROP SCHEMA IF EXISTS raw CASCADE")
