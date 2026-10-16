"""Adaptador de WhatsApp (F0010) con AWS End User Messaging Social.

Entrada: End User Messaging Social publica cada mensaje entrante en un tema SNS. Una Lambda (lambda_whatsapp.py, sin
dependencias) lo recibe, lo pasa a la API (`POST /api/interno/asistente`) y envía la respuesta con
SendWhatsAppMessage. Aquí está lo que comparten la Lambda y la API: leer el evento y armar los mensajes salientes.

La sesión de WhatsApp no tiene un id de conversación propio: la clave es el HMAC del número y el día, así una
conversación dura a lo más un día y nunca se guarda el número en claro.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from ..comun import cifrado

API_META = "v20.0"


@dataclass
class MensajeEntrante:
    telefono: str            # E.164
    id_mensaje: str          # wamid…
    tipo: str                # text | image | document | …
    texto: str
    id_media: str | None = None
    tipo_mime: str | None = None
    id_numero_meta: str | None = None   # phone_number_id de Meta que recibió el mensaje


def leer_evento_sns(mensaje_sns: str) -> list[MensajeEntrante]:
    """El `Message` de SNS que publica End User Messaging Social: {"context": …, "whatsAppWebhookEntry": "<json>"}."""
    cuerpo = json.loads(mensaje_sns)
    entrada = cuerpo.get("whatsAppWebhookEntry")
    entrada = json.loads(entrada) if isinstance(entrada, str) else (entrada or {})
    salida = []
    for cambio in entrada.get("changes", []):
        valor = cambio.get("value", {})
        id_numero = valor.get("metadata", {}).get("phone_number_id")
        for m in valor.get("messages", []):
            tipo = m.get("type", "")
            texto, id_media, mime = "", None, None
            if tipo == "text":
                texto = m.get("text", {}).get("body", "")
            elif tipo in ("image", "document"):
                adjunto = m.get(tipo, {})
                texto, id_media, mime = adjunto.get("caption", ""), adjunto.get("id"), adjunto.get("mime_type")
            elif tipo == "interactive":
                inter = m.get("interactive", {})
                texto = (inter.get("button_reply") or inter.get("list_reply") or {}).get("title", "")
            elif tipo == "button":
                texto = m.get("button", {}).get("text", "")
            if not m.get("from"):
                continue
            salida.append(MensajeEntrante(cifrado.normalizar(m["from"]), m.get("id", ""), tipo, texto, id_media, mime,
                                          id_numero))
    return salida


def clave_sesion(telefono: str, dia: date | None = None) -> str:
    return f"wa:{cifrado.hmac_telefono(telefono)[:24]}:{(dia or date.today()).isoformat()}"


def mensaje_texto(telefono: str, texto: str) -> bytes:
    """Cuerpo de SendWhatsAppMessage (formato de la API de Meta) para un texto libre (ventana de 24 h)."""
    return json.dumps({"messaging_product": "whatsapp", "to": telefono.lstrip("+"), "type": "text",
                       "text": {"preview_url": False, "body": texto[:4096]}}).encode()


def mensaje_plantilla(telefono: str, plantilla: str, parametros: list[str], idioma: str = "es") -> bytes:
    """Mensaje con plantilla aprobada: lo único que WhatsApp permite para iniciar una conversación (recordatorios)."""
    return json.dumps({"messaging_product": "whatsapp", "to": telefono.lstrip("+"), "type": "template",
                       "template": {"name": plantilla, "language": {"code": idioma},
                                    "components": [{"type": "body", "parameters": [
                                        {"type": "text", "text": p} for p in parametros]}]}}).encode()


def enviar(cliente, origen: str, cuerpo: bytes) -> str:
    """SendWhatsAppMessage. `origen` = originationPhoneNumberId (phone-number-id-… de End User Messaging Social)."""
    return cliente.send_whatsapp_message(originationPhoneNumberId=origen, message=cuerpo,
                                         metaApiVersion=API_META)["messageId"]
