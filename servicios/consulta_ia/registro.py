"""Registro de la consulta en RDS (esquema consulta, F0003/F0009). Solo inserciones: la auditoría no se edita."""
from __future__ import annotations

import psycopg

AUDIENCIA = "equipo_clinico"


def kb_vigente(conn: psycopg.Connection, knowledge_base_id: str) -> dict | None:
    fila = conn.execute("SELECT id_ingesta, fecha_corte, sincronizada_en, n_documentos FROM consulta.v_kb_vigente "
                        "WHERE knowledge_base_id = %s", (knowledge_base_id,)).fetchone()
    if not fila:
        return None
    return {"id_ingesta": fila[0], "fecha_corte": fila[1], "sincronizada_en": fila[2], "n_documentos": fila[3]}


def ultima_ingesta(conn: psycopg.Connection, knowledge_base_id: str) -> dict | None:
    fila = conn.execute("SELECT id_ingesta, estado, fecha_corte, inicio, fin, n_documentos, error FROM consulta.ingesta_kb "
                        "WHERE knowledge_base_id = %s ORDER BY id_ingesta DESC LIMIT 1", (knowledge_base_id,)).fetchone()
    cols = ("id_ingesta", "estado", "fecha_corte", "inicio", "fin", "n_documentos", "error")
    return dict(zip(cols, fila)) if fila else None


def documentos_por_uri(conn: psycopg.Connection, id_ingesta: int, uris: list[str]) -> dict[str, dict]:
    if not uris:
        return {}
    filas = conn.execute("SELECT s3_uri, id_documento, tipo, clave FROM consulta.documento_kb "
                         "WHERE id_ingesta = %s AND s3_uri = ANY(%s)", (id_ingesta, list(uris))).fetchall()
    return {u: {"id_documento": i, "tipo": t, "clave": k} for u, i, t, k in filas}


def registrar(conn: psycopg.Connection, *, id_usuario: str, texto: str, ruta: str, respuesta: str, modelo_ia: str,
              version_prompt: str, latencia_ms: int, id_ingesta: int | None = None, sql: str | None = None,
              id_consulta_athena: str | None = None, bytes_escaneados: int | None = None,
              guardrail_intervino: bool = False, fuentes: list[dict] | None = None) -> int:
    """Inserta la pregunta y sus fuentes en una transacción. Devuelve id_pregunta."""
    with conn.transaction():
        id_pregunta = conn.execute(
            "INSERT INTO consulta.pregunta (id_usuario, texto, ruta, id_ingesta, sql_generado, id_consulta_athena, "
            "bytes_escaneados, respuesta, modelo_ia, version_prompt, guardrail_intervino, latencia_ms) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id_pregunta",
            (id_usuario, texto, ruta, id_ingesta, sql, id_consulta_athena, bytes_escaneados, respuesta, modelo_ia,
             version_prompt, guardrail_intervino, latencia_ms)).fetchone()[0]
        for f in fuentes or []:
            conn.execute("INSERT INTO consulta.fuente_respuesta (id_pregunta, orden, id_documento, fragmento) "
                         "VALUES (%s, %s, %s, %s)", (id_pregunta, f["orden"], f["id_documento"], f["fragmento"]))
    return id_pregunta


def historial(conn: psycopg.Connection, id_usuario: str, limite: int = 20) -> list[dict]:
    filas = conn.execute(
        "SELECT id_pregunta, texto, ruta, respuesta, sql_generado, latencia_ms, creada_en, fecha_corte "
        "FROM consulta.pregunta WHERE id_usuario = %s ORDER BY creada_en DESC LIMIT %s", (id_usuario, limite)).fetchall()
    cols = ("id_pregunta", "texto", "ruta", "respuesta", "sql", "latencia_ms", "creada_en", "fecha_corte")
    return [dict(zip(cols, f)) for f in filas]
