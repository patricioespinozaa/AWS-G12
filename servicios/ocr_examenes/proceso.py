"""Lectura de una evidencia (F0012): S3 → Textract → Claude → validación de citas → canal.lectura_examen.

Solo lee archivos limpios (escaneo de malware) o, sin escaneo configurado (desarrollo), `sin_escaneo`. Nunca toca los
valores de canal.evidencia_externa: esos los confirma una persona al validar.
"""
from __future__ import annotations

import logging
import time

from priorizacion import config

from . import extraccion, texto

log = logging.getLogger("hlf.ocr")


def _uri_a_bucket_clave(uri: str) -> tuple[str, str]:
    bucket, _, clave = uri[len("s3://"):].partition("/")
    return bucket, clave


def leer(conn, id_evidencia: int, textract=None, proponer=None) -> dict:
    """Lee y deja la propuesta. `textract` y `proponer(texto) → (propuesta, medida)` se reemplazan en las pruebas."""
    fila = conn.execute("SELECT uri_archivo, escaneo_malware, estado_lectura FROM canal.evidencia_externa "
                        "WHERE id_evidencia = %s", (id_evidencia,)).fetchone()
    if fila is None or not fila[0]:
        raise ValueError(f"La evidencia {id_evidencia} no tiene archivo")
    uri, escaneo, estado = fila
    if escaneo not in ("limpio", "sin_escaneo"):
        raise PermissionError(f"La evidencia {id_evidencia} no está declarada limpia (escaneo: {escaneo})")
    conn.execute("UPDATE canal.evidencia_externa SET estado_lectura = 'leyendo' WHERE id_evidencia = %s", (id_evidencia,))
    t0 = time.perf_counter()
    try:
        if textract is None:
            import boto3
            textract = boto3.client("textract", region_name=config.AWS_REGION)
        bucket, clave = _uri_a_bucket_clave(uri)
        contenido = texto.extraer(textract, bucket, clave)
        propuesta, medida = (proponer or extraccion.proponer)(contenido)
        lectura = extraccion.validar(propuesta, contenido)
        modelo = config.BEDROCK_MODEL_ID if proponer is None else "simulado"
        with conn.transaction():
            for c in lectura.campos.values():
                conn.execute("INSERT INTO canal.lectura_examen (id_evidencia, campo, valor_propuesto, cita, confianza, "
                             "nota, modelo, version_prompt) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                             (id_evidencia, c.campo, c.valor, c.cita[:1000] if c.cita else None, c.confianza,
                              c.nota, modelo, extraccion.VERSION_PROMPT))
            conn.execute("UPDATE canal.evidencia_externa SET estado_lectura = 'leida' WHERE id_evidencia = %s",
                         (id_evidencia,))
        leidos = [c.campo for c in lectura.campos.values() if c.valor is not None]
        log.info('{"evento": "ocr_examen", "id_evidencia": %s, "leidos": %s, "ms": %d, "tokens_salida": %s}',
                 id_evidencia, len(leidos), (time.perf_counter() - t0) * 1000, medida.get("tokens_salida"))
        return {"id_evidencia": id_evidencia, "leidos": leidos, "caracteres": len(contenido)}
    except Exception:
        conn.execute("UPDATE canal.evidencia_externa SET estado_lectura = 'fallida' WHERE id_evidencia = %s",
                     (id_evidencia,))
        raise


def ultima_lectura(conn, id_evidencia: int) -> dict[str, dict]:
    """La propuesta más reciente de cada campo."""
    filas = conn.execute(
        "SELECT DISTINCT ON (campo) campo, valor_propuesto, cita, confianza, nota, modelo, creada_en "
        "FROM canal.lectura_examen WHERE id_evidencia = %s ORDER BY campo, creada_en DESC, id_lectura DESC",
        (id_evidencia,)).fetchall()
    return {f[0]: {"valor": f[1], "cita": f[2], "confianza": float(f[3]) if f[3] is not None else None, "nota": f[4],
                   "modelo": f[5]} for f in filas}
