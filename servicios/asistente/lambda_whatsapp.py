"""Lambda de WhatsApp (F0010): SNS (End User Messaging Social) → API del asistente → SendWhatsAppMessage.

Sin dependencias fuera de la biblioteca estándar y boto3 (incluido en el runtime de Lambda). No toca la base: el
núcleo del asistente corre en la API (ECS), que tiene la conexión a RDS. Se autentica ante la API con un secreto de
servicio (Secrets Manager) en la cabecera X-HLF-Servicio. Variables:
    HLF_API_PARAMETRO         parámetro de SSM con la URL de la API (https://<cloudfront>); o HLF_API_URL
    HLF_SERVICIO_SECRET_ID    secreto compartido con la API
    HLF_WHATSAPP_ORIGEN       phone-number-id-… (originationPhoneNumberId de End User Messaging Social)
Nunca registra el texto ni el número en los logs.
"""
import json
import logging
import os
import urllib.request

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)
_secreto = None
_api_url = None


def _secreto_servicio():
    global _secreto
    if _secreto is None:
        _secreto = boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["HLF_SERVICIO_SECRET_ID"])["SecretString"]
    return _secreto


def _url_api():
    global _api_url
    if _api_url is None:
        _api_url = os.environ.get("HLF_API_URL") or boto3.client("ssm").get_parameter(
            Name=os.environ["HLF_API_PARAMETRO"])["Parameter"]["Value"]
    return _api_url.rstrip("/")


def _api(ruta, cuerpo):
    req = urllib.request.Request(_url_api() + ruta, method="POST",
                                 data=json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json", "X-HLF-Servicio": _secreto_servicio()})
    with urllib.request.urlopen(req, timeout=50) as r:
        return json.loads(r.read())


def handler(event, context):
    procesados = 0
    for registro in event.get("Records", []):
        mensaje = registro.get("Sns", {}).get("Message", "{}")
        try:
            respuesta = _api("/api/interno/asistente/whatsapp", {"evento_sns": mensaje})
        except Exception as e:  # noqa: BLE001 — se reintenta por SNS si falla la API
            log.error(json.dumps({"evento": "whatsapp_error_api", "error": type(e).__name__}))
            raise
        cliente = boto3.client("socialmessaging")
        if not os.environ.get("HLF_WHATSAPP_ORIGEN"):
            log.warning(json.dumps({"evento": "whatsapp_sin_origen", "respuestas": len(respuesta.get("salidas", []))}))
            continue
        for salida in respuesta.get("salidas", []):
            cliente.send_whatsapp_message(originationPhoneNumberId=os.environ["HLF_WHATSAPP_ORIGEN"],
                                          message=salida["cuerpo"].encode(), metaApiVersion="v20.0")
            procesados += 1
    log.info(json.dumps({"evento": "whatsapp_respuestas", "enviadas": procesados}))
    return {"enviadas": procesados}
