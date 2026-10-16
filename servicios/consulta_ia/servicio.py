"""Orquesta una consulta (F0009): clasificar → conteo (SQL en Athena) o texto (RAG) o rechazada → registrar.

No depende de FastAPI ni de Lambda: la API lo llama en la tarea ECS y un handler de Lambda podría hacer lo mismo.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import date

from priorizacion import config

from ..comun import bedrock
from . import clasificador, rag, sql

FILAS_EN_RESPUESTA = 50
MAX_FRAGMENTO = 2000
SIN_KB = "La base de conocimiento todavía no está lista (aún no se sincronizan los documentos)."
SIN_FUENTES = "No encontré información sobre eso en los documentos de la base de conocimiento."
BLOQUEO = "La respuesta fue bloqueada por el guardrail (pedía un diagnóstico, un tratamiento u otro contenido no permitido)."


@dataclass
class Respuesta:
    ruta: str                                   # texto | conteo | rechazada
    respuesta: str
    motivo: str = ""
    sql: str | None = None
    columnas: list[str] = field(default_factory=list)
    filas: list[list] = field(default_factory=list)
    n_filas: int | None = None
    id_consulta_athena: str | None = None
    bytes_escaneados: int | None = None
    fuentes: list[dict] = field(default_factory=list)
    filtros: dict = field(default_factory=dict)
    guardrail_intervino: bool = False
    latencia_ms: int = 0
    modelo: str = ""
    fecha_corte: str = ""
    id_pregunta: int | None = None
    version_prompt: str = ""
    id_ingesta: int | None = None

    def a_dict(self) -> dict:
        return asdict(self)


def _formatear_conteo(descripcion: str, columnas: list[str], filas: list[tuple]) -> str:
    if len(filas) == 1 and len(columnas) == 1:
        valor = filas[0][0]
        return f"{valor} {descripcion}".strip() if descripcion else str(valor)
    if not filas:
        return f"La consulta no devolvió filas ({descripcion})." if descripcion else "La consulta no devolvió filas."
    return f"{descripcion}: {len(filas)} fila(s); ver la tabla." if descripcion else f"{len(filas)} fila(s); ver la tabla."


def _conteo(pregunta: str, fecha_corte: str, athena, r: Respuesta) -> None:
    generado = sql.generar(pregunta, fecha_corte)
    r.version_prompt = f"{clasificador.VERSION_PROMPT}+{sql.VERSION_PROMPT}"
    if not generado.sql:
        r.ruta, r.respuesta = "rechazada", generado.descripcion or "La pregunta no se puede responder con los datos disponibles."
        r.motivo = "sin SQL"
        return
    r.sql = generado.sql
    try:
        r.sql = sql.validar(generado.sql)
    except sql.SQLRechazado as e:
        r.ruta, r.motivo = "rechazada", f"SQL rechazado: {e}"
        r.respuesta = f"No ejecuté la consulta: el SQL generado {e}."
        return
    try:
        athena.ejecutar(f"EXPLAIN {r.sql}")                    # tablas y columnas existen; no lee datos
        res = athena.ejecutar(r.sql)
    except Exception as e:  # noqa: BLE001 — error de Athena: se informa, no se adivina
        r.ruta, r.motivo = "rechazada", f"Athena: {str(e)[:300]}"
        r.respuesta = "Athena no pudo ejecutar la consulta generada; reformula la pregunta."
        return
    r.columnas = res.columnas
    r.filas = [[v.isoformat() if hasattr(v, "isoformat") else (float(v) if hasattr(v, "as_tuple") else v)
                for v in f] for f in res.filas[:FILAS_EN_RESPUESTA]]
    r.n_filas, r.id_consulta_athena, r.bytes_escaneados = len(res.filas), res.id_consulta, res.bytes_escaneados
    r.respuesta = _formatear_conteo(generado.descripcion, res.columnas, r.filas)


def _texto(pregunta: str, c: clasificador.Clasificacion, kb_id: str | None, kb: dict | None, documentos, r: Respuesta) -> None:
    r.version_prompt = f"{clasificador.VERSION_PROMPT}+{rag.VERSION_PROMPT}"
    if not kb_id or not kb:
        r.ruta, r.respuesta, r.motivo = "rechazada", SIN_KB, "sin KB vigente"
        return
    r.id_ingesta = kb["id_ingesta"]
    salida = rag.responder(pregunta, kb_id, c.id_paciente, c.especialidad)
    r.guardrail_intervino = salida.guardrail_intervino
    if salida.guardrail_intervino:
        r.ruta, r.respuesta, r.motivo = "rechazada", BLOQUEO, "guardrail"
        return
    conocidos = documentos([c.s3_uri for c in salida.citas])
    fuentes = []
    for cita in salida.citas:
        doc = conocidos.get(cita.s3_uri)
        if doc is None:                                         # cita a un documento que no está registrado: no cuenta
            continue
        fuentes.append({"orden": len(fuentes), "id_documento": doc["id_documento"], "tipo": doc["tipo"],
                        "clave": doc["clave"], "s3_uri": cita.s3_uri, "fragmento": cita.fragmento[:MAX_FRAGMENTO]})
    if not fuentes or not salida.texto:
        r.ruta, r.respuesta, r.motivo = "rechazada", SIN_FUENTES, "sin fuentes citadas"
        return
    r.respuesta, r.fuentes = salida.texto, fuentes


def responder(pregunta: str, *, fecha_corte: date, athena=None, kb_id: str | None = None, kb: dict | None = None,
              documentos=lambda uris: {}) -> Respuesta:
    """Responde sin registrar (el registro lo hace quien llama, con la conexión a la base).

    `documentos(uris)` cruza las URIs citadas con consulta.documento_kb de la ingesta vigente (`kb`).
    """
    t0 = time.perf_counter()
    pregunta = pregunta.strip()
    r = Respuesta(ruta="rechazada", respuesta="", modelo=config.BEDROCK_MODEL_ID, fecha_corte=fecha_corte.isoformat(),
                  version_prompt=clasificador.VERSION_PROMPT)
    try:
        c = clasificador.clasificar(pregunta)
        r.filtros = {k: v for k, v in (("id_paciente", c.id_paciente), ("especialidad", c.especialidad)) if v}
        r.motivo = c.motivo
        if c.ruta == "rechazada":
            r.respuesta = f"No puedo responder esa pregunta: {c.motivo}"
        elif c.ruta == "conteo":
            r.ruta = "conteo"
            if athena is None:
                r.ruta, r.respuesta, r.motivo = "rechazada", "La consulta con Athena no está configurada.", "sin Athena"
            else:
                _conteo(pregunta, fecha_corte.isoformat(), athena, r)
        else:
            r.ruta = "texto"
            _texto(pregunta, c, kb_id, kb, documentos, r)
    except bedrock.ErrorModelo as e:
        r.ruta, r.respuesta, r.motivo = "rechazada", "No pude interpretar la pregunta; reformúlala.", str(e)[:300]
    except Exception as e:  # noqa: BLE001 — Bedrock sin permiso, red… se registra como rechazada con el motivo
        r.ruta, r.respuesta, r.motivo = "rechazada", "La consulta no está disponible en este momento.", f"{type(e).__name__}: {str(e)[:250]}"
    # Una respuesta de conteo siempre tiene SQL y su ejecución; si no, no es conteo
    if r.ruta == "conteo" and not r.id_consulta_athena:
        r.ruta = "rechazada"
    r.latencia_ms = round((time.perf_counter() - t0) * 1000)
    bedrock.registrar("consulta_ia", ruta=r.ruta, motivo=r.motivo, latencia_ms=r.latencia_ms, modelo=r.modelo,
                      filtros=r.filtros, n_fuentes=len(r.fuentes), n_filas=r.n_filas, bytes=r.bytes_escaneados,
                      guardrail=r.guardrail_intervino)
    return r
