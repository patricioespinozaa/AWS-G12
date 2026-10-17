"""Una preparación de la Knowledge Base del equipo clínico (F0009).

1. Registra la ingesta en consulta.ingesta_kb (una sola en curso por KB: lo garantiza un índice único).
2. Genera los documentos con los datos hasta la fecha de corte (documentos.py).
3. Los sube a s3://<bucket>/<prefijo>/kb/equipo/ con su <documento>.metadata.json (solo los que cambiaron).
4. Los registra en consulta.documento_kb (URI, sha256 y metadatos): así cada cita de una respuesta es verificable.
5. Lanza la ingesta de Bedrock (StartIngestionJob) y espera su fin; deja el resultado en la ingesta.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time

from db import esquema
from db.conexion import conectar
from priorizacion import config
from priorizacion.datos import Repositorio
from priorizacion.registro_postgres import RegistroPostgres

from . import documentos as D

log = logging.getLogger("hlf.preparacion_kb")
AUDIENCIA = "equipo_clinico"
ESPERA_MAX_S = 30 * 60


class ErrorPreparacion(RuntimeError):
    pass


def prefijo_kb() -> str:
    return f"{config.S3_PREFIJO}/kb/equipo"


def _subir_si_cambio(s3, clave: str, cuerpo: bytes, tipo: str) -> bool:
    huella = hashlib.sha256(cuerpo).hexdigest()
    try:
        if s3.head_object(Bucket=config.S3_BUCKET, Key=clave).get("Metadata", {}).get("sha256") == huella:
            return False
    except Exception as e:  # noqa: BLE001 — 404: no existe
        if "404" not in str(e) and "Not Found" not in str(e):
            raise
    s3.put_object(Bucket=config.S3_BUCKET, Key=clave, Body=cuerpo, ContentType=tipo, Metadata={"sha256": huella})
    return True


def _cerrar(conn, id_ingesta: int, estado: str, **campos) -> None:
    sets = ", ".join(f"{k} = %s" for k in campos)
    conn.execute(f"UPDATE consulta.ingesta_kb SET estado = %s, fin = now(){', ' + sets if sets else ''} "
                 "WHERE id_ingesta = %s", (estado, *campos.values(), id_ingesta))


def preparar(url: str | None = None, s3=None, agente=None, esperar: bool = True) -> dict:
    """Genera, sube, registra y sincroniza. Devuelve el resumen de la ingesta."""
    if not (config.KB_ID and config.KB_DATA_SOURCE_ID and config.S3_BUCKET):
        raise ErrorPreparacion("Falta HLF_KB_ID, HLF_KB_DATA_SOURCE_ID o HLF_S3_BUCKET")
    import boto3
    s3 = s3 or boto3.client("s3", region_name=config.AWS_REGION)
    agente = agente or boto3.client("bedrock-agent", region_name=config.BEDROCK_REGION)
    registro = RegistroPostgres(url)
    t0 = time.time()
    with conectar(url) as conn:
        conn.autocommit = True
        esquema.migrar(conn)
        corte = registro.fecha_corte()
        try:
            id_ingesta = conn.execute(
                "INSERT INTO consulta.ingesta_kb (knowledge_base_id, data_source_id, audiencia, fecha_corte, "
                "version_plantilla) VALUES (%s, %s, %s, %s, %s) RETURNING id_ingesta",
                (config.KB_ID, config.KB_DATA_SOURCE_ID, AUDIENCIA, corte, D.VERSION_PLANTILLA)).fetchone()[0]
        except Exception as e:
            if "ingesta_en_curso_uq" in str(e):
                raise ErrorPreparacion("Ya hay una preparación de la KB en curso") from e
            raise
        try:
            repo = Repositorio.desde_postgres(url)
            repo.aplicar_registro(registro.evidencias(), registro.mensajes())
            docs = D.generar(repo, corte, registro.serie(), registro.decisiones_por_solicitud())
            subidos = 0
            for d in docs:
                clave = f"{prefijo_kb()}/{d.ruta}"
                subidos += _subir_si_cambio(s3, clave, d.contenido.encode("utf-8"), "text/markdown; charset=utf-8")
                _subir_si_cambio(s3, f"{clave}.metadata.json", d.metadata_json().encode("utf-8"), "application/json")
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO consulta.documento_kb (id_ingesta, tipo, clave, id_paciente, s3_uri, sha256, "
                        "metadatos) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        [(id_ingesta, d.tipo, d.clave, d.id_paciente, f"s3://{config.S3_BUCKET}/{prefijo_kb()}/{d.ruta}",
                          d.sha256, json.dumps(d.metadatos, ensure_ascii=False)) for d in docs])
            log.info("KB: %s documentos (%s cambiaron) a la fecha de corte %s", len(docs), subidos, corte)
            job = agente.start_ingestion_job(knowledgeBaseId=config.KB_ID, dataSourceId=config.KB_DATA_SOURCE_ID,
                                             description=f"HLF ingesta {id_ingesta} · corte {corte}")["ingestionJob"]
            conn.execute("UPDATE consulta.ingesta_kb SET estado = 'sincronizando', ingestion_job_id = %s, "
                         "n_documentos = %s WHERE id_ingesta = %s", (job["ingestionJobId"], len(docs), id_ingesta))
            resumen = {"id_ingesta": id_ingesta, "fecha_corte": corte.isoformat(), "documentos": len(docs),
                       "subidos": subidos, "ingestion_job_id": job["ingestionJobId"]}
            if not esperar:
                return resumen
            estado, stats = _esperar(agente, job["ingestionJobId"])
            fallidos = int(stats.get("numberOfDocumentsFailed", 0) or 0)
            if estado == "COMPLETE":
                _cerrar(conn, id_ingesta, "completa", n_fallidos=fallidos)
            else:
                _cerrar(conn, id_ingesta, "fallida", n_fallidos=fallidos, error=f"ingesta {estado}")
            return {**resumen, "estado": "completa" if estado == "COMPLETE" else "fallida", "estadisticas": stats,
                    "segundos": round(time.time() - t0, 1)}
        except Exception as e:
            log.exception("La preparación de la KB falló")
            _cerrar(conn, id_ingesta, "fallida", error=f"{type(e).__name__}: {str(e)[:400]}")
            raise


def _esperar(agente, job_id: str) -> tuple[str, dict]:
    inicio, espera = time.time(), 5
    while True:
        job = agente.get_ingestion_job(knowledgeBaseId=config.KB_ID, dataSourceId=config.KB_DATA_SOURCE_ID,
                                       ingestionJobId=job_id)["ingestionJob"]
        if job["status"] in ("COMPLETE", "FAILED", "STOPPED"):
            return job["status"], job.get("statistics", {})
        if time.time() - inicio > ESPERA_MAX_S:
            return "TIMEOUT", job.get("statistics", {})
        time.sleep(espera)
        espera = min(espera * 1.5, 30)
