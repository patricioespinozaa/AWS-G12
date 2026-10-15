"""Aplica los scripts SQL de db/sql/<esquema>/ en orden. Todos son idempotentes.

Los archivos 0xx_* crean tablas; los 9xx_* (permisos) se aplican aparte porque requieren CREATEROLE.
"""
from __future__ import annotations

from pathlib import Path

import psycopg

SQL_DIR = Path(__file__).resolve().parent / "sql"
# En orden de dependencia: priorizacion referencia raw; canal referencia ambos
ESQUEMAS = ("raw", "priorizacion", "canal")


def _ejecutar(conn: psycopg.Connection, archivos: list[Path]) -> list[str]:
    for archivo in archivos:
        conn.execute(archivo.read_text(encoding="utf-8"))
    return [a.name for a in archivos]


def aplicar(conn: psycopg.Connection, esquema: str = "raw") -> list[str]:
    return _ejecutar(conn, sorted(a for a in (SQL_DIR / esquema).glob("*.sql") if not a.name.startswith("9")))


def aplicar_permisos(conn: psycopg.Connection, esquema: str = "raw") -> list[str]:
    return _ejecutar(conn, sorted((SQL_DIR / esquema).glob("9*.sql")))
