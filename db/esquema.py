"""Aplica los scripts SQL de db/sql/<esquema>/ en orden. Todos son idempotentes.

Los archivos 0xx_* crean tablas; los 9xx_* (permisos) se aplican aparte porque requieren CREATEROLE.
Modelo: raw en docs/feature/F0001-subida-datos-aws.md; priorizacion y canal en docs/feature/F0002-modelo-datos-canales.md;
consulta en docs/feature/F0003-flujos-aws-datos.md.
"""
from __future__ import annotations

from pathlib import Path

import psycopg

SQL_DIR = Path(__file__).resolve().parent / "sql"
# Qué esquema referencia a cuál (llaves foráneas, funciones y triggers). ESQUEMAS sale en orden de dependencia.
DEPENDE_DE = {
    "raw": (),
    "priorizacion": ("raw",),
    "canal": ("raw", "priorizacion"),
    "consulta": ("raw", "priorizacion"),
}
ESQUEMAS = tuple(DEPENDE_DE)


def _ejecutar(conn: psycopg.Connection, archivos: list[Path]) -> list[str]:
    for archivo in archivos:
        conn.execute(archivo.read_text(encoding="utf-8"))
    return [a.name for a in archivos]


def resolver(opcion: str) -> tuple[str, ...]:
    """'todos' → los tres esquemas en orden de dependencia; si no, el esquema pedido."""
    if opcion == "todos":
        return ESQUEMAS
    if opcion not in ESQUEMAS:
        raise ValueError(f"Esquema desconocido: {opcion}")
    return (opcion,)


def dependientes(nombre: str) -> tuple[str, ...]:
    """Esquemas que dependen de `nombre`, directa o indirectamente."""
    directos = [e for e, deps in DEPENDE_DE.items() if nombre in deps]
    todos = list(directos)
    for e in directos:
        todos += [x for x in dependientes(e) if x not in todos]
    return tuple(e for e in ESQUEMAS if e in todos)


def existentes(conn: psycopg.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)", (list(ESQUEMAS),)).fetchall()}


def aplicar(conn: psycopg.Connection, esquema: str = "raw") -> list[str]:
    faltan = [e for e in DEPENDE_DE[esquema] if e not in existentes(conn)]
    if faltan:
        raise psycopg.errors.InvalidSchemaName(f"{esquema} requiere antes el esquema {', '.join(faltan)}")
    return _ejecutar(conn, sorted(a for a in (SQL_DIR / esquema).glob("*.sql") if not a.name.startswith("9")))


def aplicar_permisos(conn: psycopg.Connection, esquema: str = "raw") -> list[str]:
    return _ejecutar(conn, sorted((SQL_DIR / esquema).glob("9*.sql")))
