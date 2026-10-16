"""Exámenes externos con lectura asistida (F0012).

1. `POST /api/canal/evidencias/subida`: URL prefirmada de S3 (POST, 5 minutos, PDF/JPG/PNG, ≤ 10 MB, SSE-KMS). El archivo
   va directo del navegador a S3: no pasa por la API ni por CloudFront.
2. `POST /api/canal/evidencias/completar`: comprueba el objeto, calcula su sha256 (en memoria, sin copia en disco) y
   crea la evidencia `pendiente`, sin tipo ni valor.
3. El escaneo de malware (GuardDuty) llega por `POST /api/interno/examenes/escaneo`. Limpio → lectura (Textract + Claude);
   infectado → bloqueada. Sin escaneo configurado (solo desarrollo), se lee de inmediato.
4. `GET /api/canal/evidencias/{id}/lectura`: la propuesta con sus citas y un enlace temporal al documento, para que la
   Administradora confirme o corrija al validar (`/api/canal/evidencias/{id}/revision`).
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from priorizacion import config

from .. import estado as E
from ..seguridad import Persona, administradora
from .asistente import exigir_servicio

log = logging.getLogger("hlf.examenes")
router = APIRouter()
router_interno = APIRouter()
TIPOS = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
MAX_BYTES = 10 * 1024 * 1024
VIGENCIA_S = 300


def _exigir():
    if not (config.usa_rds() and config.S3_BUCKET):
        raise HTTPException(409, "La subida directa de exámenes requiere la base (RDS) y el bucket de S3.")


def _s3():
    import boto3
    return boto3.client("s3", region_name=config.AWS_REGION)


def _prefijo(id_paciente: str) -> str:
    return f"{config.S3_PREFIJO}/canal/evidencias/{id_paciente}/"


def _nombre_seguro(nombre: str) -> str:
    limpio = re.sub(r"[^A-Za-z0-9._-]", "_", nombre.rsplit("/", 1)[-1])[:80]
    return limpio or "examen"


class SubidaIn(BaseModel):
    id_paciente: str = Field(pattern=r"^PAC-HLF-\d{5}$")
    nombre: str = Field(min_length=1, max_length=120)
    tipo_mime: str


@router.post("/api/canal/evidencias/subida")
def subida(s: SubidaIn):
    _exigir()
    E.paciente(s.id_paciente)
    if s.tipo_mime not in TIPOS:
        raise HTTPException(422, "Se aceptan PDF, JPG y PNG.")
    clave = f"{_prefijo(s.id_paciente)}{uuid.uuid4().hex}/{_nombre_seguro(s.nombre)}"
    campos = {"Content-Type": s.tipo_mime}
    condiciones = [{"Content-Type": s.tipo_mime}, ["content-length-range", 1, MAX_BYTES]]
    if config.EXAMENES_KMS_KEY_ID:
        campos.update({"x-amz-server-side-encryption": "aws:kms",
                       "x-amz-server-side-encryption-aws-kms-key-id": config.EXAMENES_KMS_KEY_ID})
        condiciones += [{"x-amz-server-side-encryption": "aws:kms"},
                        {"x-amz-server-side-encryption-aws-kms-key-id": config.EXAMENES_KMS_KEY_ID}]
    firmado = _s3().generate_presigned_post(Bucket=config.S3_BUCKET, Key=clave, Fields=campos,
                                            Conditions=condiciones, ExpiresIn=VIGENCIA_S)
    return {"url": firmado["url"], "campos": firmado["fields"], "clave": clave, "expira_s": VIGENCIA_S}


class CompletarIn(BaseModel):
    id_paciente: str = Field(pattern=r"^PAC-HLF-\d{5}$")
    clave: str = Field(max_length=400)
    lugar: str = Field(default="", max_length=120)


def crear_evidencia(conn, id_paciente: str, clave: str, canal_origen: str = "web", lugar: str = "",
                    id_conversacion: int | None = None, s3=None) -> dict:
    """Comprueba el objeto subido y crea la evidencia pendiente. Lo usan la app y WhatsApp."""
    if not clave.startswith(_prefijo(id_paciente)) or ".." in clave:
        raise HTTPException(422, "El archivo no corresponde a este paciente.")
    s3 = s3 or _s3()
    try:
        cabecera = s3.head_object(Bucket=config.S3_BUCKET, Key=clave)
    except Exception:
        raise HTTPException(404, "No se encontró el archivo subido.")
    tipo = cabecera.get("ContentType", "")
    if tipo not in TIPOS or cabecera.get("ContentLength", 0) > MAX_BYTES:
        raise HTTPException(422, "Archivo no admitido (PDF, JPG o PNG de hasta 10 MB).")
    cuerpo = s3.get_object(Bucket=config.S3_BUCKET, Key=clave)["Body"].read()     # en memoria: sin copia en disco
    sha = hashlib.sha256(cuerpo).hexdigest()
    con_escaneo = config.EXAMENES_ESCANEO
    fila = conn.execute(
        "INSERT INTO canal.evidencia_externa (id_paciente, id_conversacion, canal_origen, lugar, uri_archivo, "
        "sha256_archivo, tipo_mime, tamano_bytes, fecha_recepcion, escaneo_malware, estado_lectura) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, priorizacion.fecha_corte(), %s, %s) RETURNING id_evidencia",
        (id_paciente, id_conversacion, canal_origen, lugar, f"s3://{config.S3_BUCKET}/{clave}", sha, tipo, len(cuerpo),
         "pendiente" if con_escaneo else "sin_escaneo", "esperando_escaneo" if con_escaneo else "leyendo")).fetchone()
    return {"id_evidencia": fila[0], "sha256": sha, "escaneo": "pendiente" if con_escaneo else "sin_escaneo"}


def leer_en_segundo_plano(id_evidencia: int) -> None:
    def correr():
        from db.conexion import conectar
        from servicios.ocr_examenes import proceso
        try:
            with conectar() as conn:
                conn.autocommit = True
                proceso.leer(conn, id_evidencia)
        except Exception as e:  # noqa: BLE001 — queda en estado_lectura = 'fallida'
            log.warning("Lectura del examen %s fallida: %s", id_evidencia, type(e).__name__)
    threading.Thread(target=correr, daemon=True, name=f"ocr-{id_evidencia}").start()


EXAMEN_RECIBIDO = ("Recibimos su examen. Se leerá y una persona del equipo lo revisará antes de usarlo; esto no cambia por "
                   "sí solo su prioridad.")
EXAMEN_SIN_IDENTIDAD = ("Para recibir exámenes necesitamos que este número esté registrado. Puede llevarlo a su próxima "
                        "cita o pedir hablar con una persona.")


def recibir_de_whatsapp(id_conversacion: int, id_media: str, tipo_mime: str | None, s3=None, social=None) -> str:
    """Un adjunto de WhatsApp (F0010 → F0012): End User Messaging Social lo deja directo en S3 y sigue el mismo camino
    que un examen subido por la app. Solo para un paciente identificado. Devuelve el texto para el paciente."""
    if not (config.S3_BUCKET and config.WHATSAPP_ORIGEN):
        return "En este momento no podemos recibir archivos por este medio; llévelo a su próxima cita."
    with E.registro.sin_version() as conn:
        fila = conn.execute("SELECT id_paciente FROM canal.conversacion WHERE id_conversacion = %s AND "
                            "nivel_verificacion <> 'ninguna'", (id_conversacion,)).fetchone()
    if not fila or tipo_mime not in TIPOS:
        return EXAMEN_SIN_IDENTIDAD if not fila else "Solo podemos recibir exámenes en PDF, JPG o PNG."
    clave = f"{_prefijo(fila[0])}{uuid.uuid4().hex}/whatsapp{TIPOS[tipo_mime]}"
    if social is None:
        import boto3
        social = boto3.client("socialmessaging", region_name=config.AWS_REGION)
    social.get_whatsapp_message_media(mediaId=id_media, originationPhoneNumberId=config.WHATSAPP_ORIGEN,
                                      destinationS3File={"bucketName": config.S3_BUCKET, "key": clave})
    with E.registro.conexion() as conn:
        r = crear_evidencia(conn, fila[0], clave, canal_origen="whatsapp", id_conversacion=id_conversacion, s3=s3)
    if r["escaneo"] == "sin_escaneo":
        leer_en_segundo_plano(r["id_evidencia"])
    return EXAMEN_RECIBIDO


@router.post("/api/canal/evidencias/completar")
def completar(c: CompletarIn):
    _exigir()
    E.paciente(c.id_paciente)
    with E.registro.conexion() as conn:              # sube la versión: la bandeja de validación la ve
        r = crear_evidencia(conn, c.id_paciente, c.clave, lugar=c.lugar)
    if r["escaneo"] == "sin_escaneo":
        leer_en_segundo_plano(r["id_evidencia"])
    return {**r, "respuesta": "Recibimos el examen. Se leerá automáticamente y una persona lo validará antes de usarlo; "
                              "esto no cambia por sí solo la prioridad."}


@router.get("/api/canal/evidencias/{id_evidencia}/lectura")
def lectura(id_evidencia: int, quien: Persona = Depends(administradora)):
    _exigir()
    from servicios.ocr_examenes import proceso
    with E.registro.sin_version() as conn:
        fila = conn.execute("SELECT uri_archivo, escaneo_malware, estado_lectura, tipo_mime, estado FROM "
                            "canal.evidencia_externa WHERE id_evidencia = %s", (id_evidencia,)).fetchone()
        if fila is None:
            raise HTTPException(404, f"No existe la evidencia {id_evidencia}")
        campos = proceso.ultima_lectura(conn, id_evidencia)
    url = None
    if fila[0] and fila[1] in ("limpio", "sin_escaneo"):             # nunca se ofrece un archivo infectado o sin escanear
        bucket, _, clave = fila[0][len("s3://"):].partition("/")
        url = _s3().generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": clave}, ExpiresIn=VIGENCIA_S)
    return {"id_evidencia": id_evidencia, "escaneo_malware": fila[1], "estado_lectura": fila[2], "tipo_mime": fila[3],
            "estado": fila[4], "propuesta": campos, "documento_url": url}


class EscaneoIn(BaseModel):
    bucket: str
    clave: str
    resultado: str                                    # NO_THREATS_FOUND | THREATS_FOUND | UNSUPPORTED | …


@router_interno.post("/api/interno/examenes/escaneo")
def escaneo(e: EscaneoIn, x_hlf_servicio: str | None = Header(default=None)):
    """Resultado de GuardDuty Malware Protection for S3 (vía EventBridge y la Lambda de escaneo)."""
    exigir_servicio(x_hlf_servicio)
    _exigir()
    uri = f"s3://{e.bucket}/{e.clave}"
    if e.resultado == "NO_THREATS_FOUND":
        escaneo, estado_lectura = "limpio", "leyendo"
    elif e.resultado == "THREATS_FOUND":
        escaneo, estado_lectura = "infectado", "bloqueada"
    else:                                           # no soportado, sin acceso o error: no se lee (sigue sin escanear)
        escaneo, estado_lectura = "pendiente", "fallida"
    with E.registro.conexion() as conn:
        fila = conn.execute(
            "UPDATE canal.evidencia_externa SET escaneo_malware = %s, estado_lectura = %s "
            "WHERE uri_archivo = %s AND escaneo_malware = 'pendiente' RETURNING id_evidencia",
            (escaneo, estado_lectura, uri)).fetchone()
    if fila and escaneo == "limpio":
        leer_en_segundo_plano(fila[0])
    return {"id_evidencia": fila[0] if fila else None, "escaneo": escaneo}
