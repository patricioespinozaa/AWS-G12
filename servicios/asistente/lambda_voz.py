"""Lambda de voz (F0011): code hook de Lex V2 → API del asistente (`/api/interno/asistente/voz`) → respuesta para Lex.

Igual que la de WhatsApp: sin VPC ni dependencias; el núcleo corre en la API. Variables: HLF_API_PARAMETRO (o
HLF_API_URL) y HLF_SERVICIO_SECRET_ID. Si la API no responde a tiempo, Lex recibe un mensaje de disculpa y el flujo
de Connect transfiere a una persona. Nunca registra lo que dijo el paciente.
"""
import json
import logging
import os
import time
import urllib.request

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)
_cache = {}
DISCULPA = "Disculpe, tengo un problema para responder. Le comunico con una persona del equipo del hospital."


def _valor(clave, carga):
    if clave not in _cache:
        _cache[clave] = carga()
    return _cache[clave]


def _url_api():
    return _valor("url", lambda: (os.environ.get("HLF_API_URL") or boto3.client("ssm").get_parameter(
        Name=os.environ["HLF_API_PARAMETRO"])["Parameter"]["Value"]).rstrip("/"))


def _secreto():
    return _valor("secreto", lambda: boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["HLF_SERVICIO_SECRET_ID"])["SecretString"])


def handler(event, context):
    t0 = time.time()
    try:
        req = urllib.request.Request(_url_api() + "/api/interno/asistente/voz", method="POST",
                                     data=json.dumps({"evento_lex": event}).encode(),
                                     headers={"Content-Type": "application/json", "X-HLF-Servicio": _secreto(),
                                              "X-Correlation-Id": getattr(context, "aws_request_id", "")})
        with urllib.request.urlopen(req, timeout=25) as r:
            respuesta = json.loads(r.read())
    except Exception as e:  # noqa: BLE001 — nunca dejar al paciente sin respuesta: se transfiere
        log.error(json.dumps({"evento": "voz_error_api", "error": type(e).__name__}))
        atributos = dict((event.get("sessionState") or {}).get("sessionAttributes") or {})
        atributos.update(transferir="true", motivo_transferencia="baja_confianza",
                         resumen_transferencia="El asistente no pudo responder (error técnico).")
        intencion = dict((event.get("sessionState") or {}).get("intent") or {"name": "FallbackIntent"})
        intencion["state"] = "Fulfilled"
        respuesta = {"sessionState": {"dialogAction": {"type": "Close"}, "intent": intencion,
                                      "sessionAttributes": atributos},
                     "messages": [{"contentType": "PlainText", "content": DISCULPA}]}
    log.info(json.dumps({"evento": "voz_turno", "ms": round((time.time() - t0) * 1000),
                         "transferir": respuesta["sessionState"]["sessionAttributes"].get("transferir") == "true"}))
    return respuesta
