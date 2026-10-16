"""Ruta de conteo (F0009): Claude genera el SQL; aquí se valida antes de ejecutarlo en Athena.

El validador es determinista y no confía en el modelo:
- una sola sentencia, sin comentarios, que empieza con SELECT o WITH;
- sin palabras de escritura o administración (INSERT, DROP, UNLOAD, …);
- solo lee tablas de hlf_raw y hlf_historial (o CTE definidas en la misma consulta), nunca catálogos del sistema;
- nunca nombra columnas que identifican a una persona (nombre_fantasia);
- si no agrega (COUNT, SUM, AVG…), exige LIMIT de a lo más 50 filas.
Después, el SQL pasa por EXPLAIN en Athena (que rechaza tablas o columnas inexistentes) y recién entonces se ejecuta,
en el workgroup con límite de bytes escaneados por consulta.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..comun import bedrock, diccionario

VERSION_PROMPT = "sql-v1"
MAX_FILAS = 50
PROHIBIDAS = ("insert", "update", "delete", "merge", "drop", "create", "alter", "truncate", "grant", "revoke",
              "call", "unload", "msck", "vacuum", "optimize", "prepare", "execute", "deallocate", "set", "reset",
              "use", "show", "describe", "explain", "analyze", "comment", "refresh")
AGREGADAS = ("count", "sum", "avg", "min", "max", "approx_distinct", "approx_percentile", "array_agg",
             "count_if", "stddev", "variance", "percentile")
_CTE = re.compile(r"(?:\bwith\b|,)\s*([a-z_][a-z0-9_]*)\s+as\s*\(", re.IGNORECASE)
_TABLA = re.compile(r"\b(?:from|join)\s+(\"?[a-z_][\w\"]*(?:\.\"?[\w]+\"?){0,2})", re.IGNORECASE)
_LIMIT = re.compile(r"\blimit\s+(\d+)\s*$", re.IGNORECASE)


class SQLRechazado(ValueError):
    pass


def _sin_literales(sql: str) -> str:
    """Quita los textos entre comillas simples: una palabra prohibida dentro de un literal ('drop') no cuenta."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def validar(sql: str) -> str:
    """Devuelve el SQL normalizado (sin `;` final) o lanza SQLRechazado con el motivo."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise SQLRechazado("no se generó SQL")
    codigo = _sin_literales(sql)
    if ";" in codigo:
        raise SQLRechazado("tiene más de una sentencia")
    if "--" in codigo or "/*" in codigo:
        raise SQLRechazado("tiene comentarios")
    minus = codigo.lower()
    if not re.match(r"^\s*(select|with)\b", minus):
        raise SQLRechazado("no es una consulta SELECT")
    for palabra in PROHIBIDAS:
        if re.search(rf"\b{palabra}\b", minus):
            raise SQLRechazado(f"contiene una operación no permitida ({palabra.upper()})")
    if re.search(r"\b(information_schema|system|pg_catalog|\$path|\$file_size)\b", minus):
        raise SQLRechazado("consulta catálogos del sistema")
    for col in diccionario.IDENTIFICATORIAS:
        if re.search(rf"\b{col}\b", minus):
            raise SQLRechazado(f"usa una columna que identifica a la persona ({col})")
    ctes = {m.lower() for m in _CTE.findall(codigo)}
    permitidas = diccionario.nombres_permitidos()
    # EXTRACT(YEAR FROM x), SUBSTRING(x FROM 1), TRIM(… FROM x) llevan FROM pero no leen tablas
    sin_funciones = re.sub(r"\b(?:extract|substring|trim)\s*\([^()]*\)", "f()", codigo, flags=re.IGNORECASE)
    tablas = [t.replace('"', "").lower() for t in _TABLA.findall(sin_funciones)]
    if not tablas:
        raise SQLRechazado("no lee ninguna tabla")
    for t in tablas:
        if t not in permitidas and t not in ctes:
            raise SQLRechazado(f"lee una tabla no permitida ({t}); solo hlf_raw.* y hlf_historial.*")
    agrega = any(re.search(rf"\b{f}\s*\(", minus) for f in AGREGADAS) or re.search(r"\bgroup\s+by\b", minus)
    if not agrega:
        m = _LIMIT.search(codigo)
        if not m or int(m.group(1)) > MAX_FILAS:
            raise SQLRechazado(f"no agrega y no tiene LIMIT de a lo más {MAX_FILAS} filas")
    return sql


SISTEMA = """Generas SQL para Amazon Athena (Trino) que responde preguntas de conteo y agregados sobre la lista de espera de especialidad de un hospital público.

Reglas:
- Usa solo estas tablas, siempre con el nombre completo base.tabla: {tablas}.
- Solo una sentencia SELECT (o WITH … SELECT). Nunca modifiques datos.
- Nunca selecciones ni filtres por nombre_fantasia ni por datos que identifiquen a una persona; usa id_paciente.
- Si la respuesta no es un agregado (COUNT, SUM, AVG…), agrega LIMIT 50.
- La fecha de corte es {fecha_corte}: es el "hoy" de los datos. Usa DATE '{fecha_corte}' para calcular días o ventanas ("últimos 30 días").
- "En espera" significa lista_espera.estado = 'en_espera'. Un evento grave es eventos_clinicos.severidad = 'grave'.
- Las especialidades se escriben con mayúscula inicial y tildes (por ejemplo 'Cardiología', 'Salud Mental').
- hlf_historial.serie_nocturna y estimacion_espera están particionadas por fecha: filtra siempre por fecha (por ejemplo fecha = DATE '{fecha_corte}').
- Cuenta personas con COUNT(DISTINCT id_paciente) cuando la pregunta habla de pacientes.
- Si la pregunta no se puede responder con estas tablas, deja sql vacío y explica por qué en `descripcion`.

Esquema (tabla: descripción, y sus columnas):
{esquema}"""

HERRAMIENTA = {
    "name": "consulta_sql",
    "description": "Entrega el SQL que responde la pregunta y una descripción breve de lo que cuenta.",
    "schema": {"type": "object", "properties": {
        "sql": {"type": "string", "description": "Una sola sentencia SELECT para Athena, o vacío si no se puede"},
        "descripcion": {"type": "string",
                        "description": "Qué cuenta el resultado, en una frase (p. ej. 'pacientes de Cardiología en espera con al menos un evento grave')"},
    }, "required": ["sql", "descripcion"]},
}


@dataclass
class SQLGenerado:
    sql: str
    descripcion: str
    medida: dict


def generar(pregunta: str, fecha_corte: str) -> SQLGenerado:
    sistema = SISTEMA.format(tablas=", ".join(sorted(diccionario.nombres_permitidos())), fecha_corte=fecha_corte,
                             esquema=diccionario.como_texto())
    salida, medida = bedrock.converse_herramienta(sistema, pregunta, HERRAMIENTA, max_tokens=1200)
    return SQLGenerado((salida.get("sql") or "").strip(), (salida.get("descripcion") or "").strip(), medida)
