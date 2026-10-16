"""Asistente del paciente (F0010): simulador en la app, derivaciones a una persona y la entrada interna de WhatsApp.

- `router` (sesión de la Administradora): POST /api/asistente/simulador, GET /api/asistente/derivaciones, …
- `router_interno` (secreto de servicio, sin sesión): POST /api/interno/asistente/whatsapp, que llama la Lambda de
  WhatsApp. Se autentica con la cabecera X-HLF-Servicio (secreto en Secrets Manager, comparación en tiempo constante).
El simulador y WhatsApp usan el mismo núcleo (servicios/asistente/nucleo.py): misma respuesta para la misma
conversación. Requiere RDS (el esquema canal).
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from priorizacion import config

from .. import estado as E

log = logging.getLogger("hlf.asistente")
router = APIRouter()
router_interno = APIRouter()
_nucleo = None
_lock = threading.Lock()
_secreto: str | None = None


def _exigir_rds():
    if not config.usa_rds():
        raise HTTPException(409, "El asistente del paciente requiere la base de datos (RDS): el esquema canal.")


@contextmanager
def _conexion():
    with E.registro.sin_version() as conn:
        yield conn


def _buscar_faq(pregunta: str) -> list[str]:
    """Fragmentos de la KB de preguntas frecuentes (F0010), si está configurada."""
    if not config.KB_PACIENTE_ID:
        return []
    from servicios.comun import bedrock
    r = bedrock.cliente("bedrock-agent-runtime").retrieve(
        knowledgeBaseId=config.KB_PACIENTE_ID, retrievalQuery={"text": pregunta[:500]},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}})
    return [x["content"]["text"] for x in r.get("retrievalResults", []) if x.get("content", {}).get("text")]


def _enviar_sms(telefono: str, codigo: str) -> bool:
    """Código de verificación por SMS (AWS End User Messaging SMS), si hay una identidad de origen configurada."""
    origen = os.environ.get("HLF_SMS_ORIGEN")
    if not origen:
        return False
    import boto3
    boto3.client("pinpoint-sms-voice-v2", region_name=config.AWS_REGION).send_text_message(
        DestinationPhoneNumber=telefono, OriginationIdentity=origen, MessageType="TRANSACTIONAL",
        MessageBody=f"Hospital Dra. Eloísa Díaz: su código de verificación es {codigo}. Vence en 5 minutos.")
    return True


def nucleo():
    global _nucleo
    with _lock:
        if _nucleo is None:
            from servicios.asistente.nucleo import Nucleo
            _nucleo = Nucleo(_conexion, enviar_sms=_enviar_sms, buscar_faq=_buscar_faq)
        return _nucleo


# -- simulador y derivaciones (Administradora) --------------------------------------------------------------
class MensajeSimulador(BaseModel):
    sesion: str = Field(min_length=6, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    telefono: str = Field(min_length=8, max_length=20)
    texto: str = Field(min_length=1, max_length=1000)


@router.post("/api/asistente/simulador")
def simulador(m: MensajeSimulador):
    """Una conversación de prueba con el mismo núcleo que WhatsApp (canal 'simulador')."""
    _exigir_rds()
    from servicios.asistente.nucleo import Entrada
    s = nucleo().procesar(Entrada("simulador", f"sim:{m.sesion}", m.texto, telefono=m.telefono))
    return s.__dict__


@router.get("/api/asistente/contactos-demo")
def contactos_demo():
    """Los números ficticios de los 6 casos de referencia (contactos_demo.py), para elegir en el simulador."""
    _exigir_rds()
    from servicios.asistente.contactos_demo import CASOS, numero_ficticio
    return [{"id_paciente": pid, "telefono": numero_ficticio(i), "patron": E.CASOS_REFERENCIA.get(pid)}
            for i, pid in enumerate(CASOS)]


@router.get("/api/asistente/derivaciones")
def derivaciones():
    _exigir_rds()
    with _conexion() as c:
        filas = c.execute(
            "SELECT d.id_derivacion, d.motivo, d.urgencia, d.estado, d.creada_en, c.canal, c.id_paciente, d.nota, "
            "(SELECT texto FROM canal.turno t WHERE t.id_conversacion = c.id_conversacion AND t.emisor = 'paciente' "
            " ORDER BY n_turno DESC LIMIT 1) AS ultimo_mensaje "
            "FROM canal.derivacion_humana d JOIN canal.conversacion c USING (id_conversacion) "
            "ORDER BY (d.estado IN ('pendiente', 'en_gestion')) DESC, "
            "array_position(ARRAY['inmediata', 'mismo_dia', 'normal'], d.urgencia), d.creada_en DESC LIMIT 100").fetchall()
    cols = ("id_derivacion", "motivo", "urgencia", "estado", "creada_en", "canal", "id_paciente", "nota", "ultimo_mensaje")
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in zip(cols, f)} for f in filas]


class Resolucion(BaseModel):
    estado: Literal["en_gestion", "resuelta", "sin_contacto"]
    nota: str = Field(default="", max_length=1000)


@router.post("/api/asistente/derivaciones/{id_derivacion}")
def resolver_derivacion(id_derivacion: int, r: Resolucion):
    _exigir_rds()
    with _conexion() as c:
        n = c.execute("UPDATE canal.derivacion_humana SET estado = %s, nota = nullif(%s, ''), "
                      "resuelta_en = CASE WHEN %s IN ('resuelta', 'sin_contacto') THEN now() END "
                      "WHERE id_derivacion = %s", (r.estado, r.nota, r.estado, id_derivacion)).rowcount
    if not n:
        raise HTTPException(404, f"No existe la derivación {id_derivacion}")
    return {"ok": True}


# -- entrada interna (Lambda de WhatsApp) -----------------------------------------------------------------
def _secreto_servicio() -> str | None:
    global _secreto
    if _secreto is None:
        if valor := os.environ.get("HLF_SERVICIO_SECRETO"):
            _secreto = valor
        elif secreto_id := os.environ.get("HLF_SERVICIO_SECRET_ID"):
            import boto3
            _secreto = boto3.client("secretsmanager", region_name=config.AWS_REGION).get_secret_value(
                SecretId=secreto_id)["SecretString"]
    return _secreto


def exigir_servicio(x_hlf_servicio: str | None):
    esperado = _secreto_servicio()
    if not esperado:
        raise HTTPException(503, "La entrada interna del asistente no está configurada.")
    if not x_hlf_servicio or not hmac.compare_digest(x_hlf_servicio.encode(), esperado.encode()):
        raise HTTPException(401, "Servicio no autorizado.")


class EventoVoz(BaseModel):
    evento_lex: dict


@router_interno.post("/api/interno/asistente/voz")
def entrada_voz(e: EventoVoz, x_hlf_servicio: str | None = Header(default=None)):
    """Code hook de Lex V2 (F0011): devuelve la respuesta para Lex. La grabación solo con consentimiento."""
    exigir_servicio(x_hlf_servicio)
    _exigir_rds()
    from servicios.asistente import voz
    respuesta = voz.atender(e.evento_lex, nucleo().procesar)
    atributos = respuesta["sessionState"]["sessionAttributes"]
    if (atributos.get("grabacion") == "si" and atributos.get("grabacion_registrada") != "true"
            and atributos.get("id_conversacion") and config.S3_BUCKET):
        uri = f"s3://{config.S3_BUCKET}/{config.S3_PREFIJO}/connect/grabaciones"
        if voz.registrar_grabacion(_conexion, int(atributos["id_conversacion"]),
                                   atributos.get("contactId") or e.evento_lex.get("sessionId", ""), uri):
            atributos["grabacion_registrada"] = "true"
    return respuesta


class EventoWhatsApp(BaseModel):
    evento_sns: str = Field(max_length=200_000)


@router_interno.post("/api/interno/asistente/whatsapp")
def entrada_whatsapp(e: EventoWhatsApp, x_hlf_servicio: str | None = Header(default=None)):
    """Procesa el evento de SNS y devuelve los mensajes que la Lambda debe enviar."""
    exigir_servicio(x_hlf_servicio)
    _exigir_rds()
    from servicios.asistente import whatsapp
    from servicios.asistente.nucleo import Entrada
    try:
        mensajes = whatsapp.leer_evento_sns(e.evento_sns)
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(422, "Evento de WhatsApp inválido.")
    salidas = []
    for m in mensajes:
        texto = m.texto or ("[archivo adjunto]" if m.id_media else "")
        if not texto:
            continue
        s = nucleo().procesar(Entrada("whatsapp", whatsapp.clave_sesion(m.telefono), texto, telefono=m.telefono))
        respuesta = s.texto
        if m.id_media:                              # F0012: el examen va a S3 y a la lectura asistida
            from .examenes import recibir_de_whatsapp
            try:
                respuesta = recibir_de_whatsapp(s.id_conversacion, m.id_media, m.tipo_mime)
            except Exception as ex:  # noqa: BLE001
                log.warning("No se pudo recibir el adjunto de WhatsApp: %s", type(ex).__name__)
                respuesta = "No pudimos recibir el archivo. Intente de nuevo o llévelo a su próxima cita."
        salidas.append({"cuerpo": whatsapp.mensaje_texto(m.telefono, respuesta).decode(), "nivel": s.nivel,
                        "derivacion": s.derivacion})
    return {"salidas": salidas}
