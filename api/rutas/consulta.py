"""Consulta en lenguaje natural (F0009): la Administradora pregunta y recibe una respuesta trazable.

- conteo → SQL validado en Athena (se devuelve el SQL y la tabla);
- texto  → Knowledge Base del equipo clínico (se devuelven los fragmentos citados);
- rechazada → no se ejecuta nada.
Cada pregunta queda en consulta.pregunta con la persona autenticada. Requiere RDS, Athena y la KB (en AWS).
"""
from __future__ import annotations

import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from priorizacion import config

from .. import estado as E
from ..seguridad import Persona, administradora

router = APIRouter()
_athena = None
_athena_lock = threading.Lock()
_preparacion: dict = {"hilo": None, "inicio": None, "resultado": None, "error": None}


class PreguntaIn(BaseModel):
    texto: str = Field(min_length=3, max_length=500)


def _exigir_rds():
    if not config.usa_rds():
        raise HTTPException(409, "La consulta en lenguaje natural requiere la base de datos (RDS) y AWS.")


def _motor_athena():
    global _athena
    with _athena_lock:
        if _athena is None and config.S3_BUCKET:
            from db import athena
            _athena = athena.Athena(athena.Config.desde_entorno(), espera_max=40)
        return _athena


def _db(funcion):
    with E.registro.sin_version() as conn:
        return funcion(conn)


@router.get("/api/consulta/estado")
def estado():
    _exigir_rds()
    from servicios.consulta_ia import registro as RC
    kb = _db(lambda c: RC.kb_vigente(c, config.KB_ID)) if config.KB_ID else None
    ultima = _db(lambda c: RC.ultima_ingesta(c, config.KB_ID)) if config.KB_ID else None
    hilo = _preparacion["hilo"]
    return {"kb_configurada": bool(config.KB_ID), "athena_configurada": bool(config.S3_BUCKET),
            "modelo": config.BEDROCK_MODEL_ID, "kb_vigente": kb, "ultima_ingesta": ultima,
            "preparando": bool(hilo and hilo.is_alive()) or bool(ultima and ultima["estado"] in ("preparando", "sincronizando")),
            "fecha_corte": config.FECHA_REFERENCIA.isoformat()}


@router.post("/api/consulta")
def preguntar(p: PreguntaIn, quien: Persona = Depends(administradora)):
    _exigir_rds()
    from servicios.consulta_ia import registro as RC
    from servicios.consulta_ia import servicio
    kb = _db(lambda c: RC.kb_vigente(c, config.KB_ID)) if config.KB_ID else None
    r = servicio.responder(
        p.texto, fecha_corte=config.FECHA_REFERENCIA, athena=_motor_athena(), kb_id=config.KB_ID or None, kb=kb,
        documentos=lambda uris: _db(lambda c: RC.documentos_por_uri(c, kb["id_ingesta"], uris)) if kb else {})
    r.id_pregunta = _db(lambda c: RC.registrar(
        c, id_usuario=quien.id_usuario, texto=p.texto.strip(), ruta=r.ruta, respuesta=r.respuesta,
        modelo_ia=r.modelo, version_prompt=r.version_prompt, latencia_ms=r.latencia_ms,
        id_ingesta=r.id_ingesta if r.ruta == "texto" else None, sql=r.sql,
        id_consulta_athena=r.id_consulta_athena if r.ruta == "conteo" else None,
        bytes_escaneados=r.bytes_escaneados, guardrail_intervino=r.guardrail_intervino,
        fuentes=r.fuentes if r.ruta == "texto" else None))
    return r.a_dict()


@router.get("/api/consulta/historial")
def historial(quien: Persona = Depends(administradora)):
    _exigir_rds()
    from servicios.consulta_ia import registro as RC
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in f.items()}
            for f in _db(lambda c: RC.historial(c, quien.id_usuario))]


@router.post("/api/consulta/preparar", status_code=202)
def preparar_kb():
    """Vuelve a generar y sincronizar la KB con los datos a la fecha de corte (tarda unos minutos, en segundo plano).
    La consolidación nocturna también lo hace cuando entran datos nuevos."""
    _exigir_rds()
    if not config.KB_ID:
        raise HTTPException(409, "La Knowledge Base no está configurada en este entorno.")
    hilo = _preparacion["hilo"]
    if hilo and hilo.is_alive():
        raise HTTPException(409, "Ya hay una preparación en curso.")

    def correr():
        from servicios.preparacion_kb.proceso import preparar
        try:
            _preparacion["resultado"] = preparar()
        except Exception as e:  # noqa: BLE001 — queda en consulta.ingesta_kb y en el estado
            _preparacion["error"] = f"{type(e).__name__}: {e}"

    _preparacion.update(hilo=threading.Thread(target=correr, daemon=True, name="preparacion_kb"),
                        inicio=datetime.now().isoformat(timespec="seconds"), resultado=None, error=None)
    _preparacion["hilo"].start()
    return {"preparando": True, "inicio": _preparacion["inicio"]}
