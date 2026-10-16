"""Lambda del escaneo de exámenes (F0012): EventBridge (GuardDuty Malware Protection for S3) → API.

Recibe el evento "GuardDuty Malware Protection Object Scan Result" y avisa a la API
(`/api/interno/examenes/escaneo`): limpio → lectura asistida; amenaza → la evidencia queda bloqueada. Sin VPC ni
dependencias; mismas variables que las Lambdas del asistente (HLF_API_PARAMETRO, HLF_SERVICIO_SECRET_ID).
"""
import json
import logging
import os
import urllib.request

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)
_cache = {}


def _valor(clave, carga):
    if clave not in _cache:
        _cache[clave] = carga()
    return _cache[clave]


def handler(event, context):
    detalle = event.get("detail", {})
    objeto = detalle.get("s3ObjectDetails", {})
    resultado = detalle.get("scanResultDetails", {}).get("scanResultStatus", "")
    url = _valor("url", lambda: (os.environ.get("HLF_API_URL") or boto3.client("ssm").get_parameter(
        Name=os.environ["HLF_API_PARAMETRO"])["Parameter"]["Value"]).rstrip("/"))
    secreto = _valor("secreto", lambda: boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["HLF_SERVICIO_SECRET_ID"])["SecretString"])
    cuerpo = {"bucket": objeto.get("bucketName", ""), "clave": objeto.get("objectKey", ""), "resultado": resultado}
    req = urllib.request.Request(url + "/api/interno/examenes/escaneo", method="POST", data=json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json", "X-HLF-Servicio": secreto,
                                          "X-Correlation-Id": getattr(context, "aws_request_id", "")})
    with urllib.request.urlopen(req, timeout=20) as r:
        respuesta = json.loads(r.read())
    log.info(json.dumps({"evento": "escaneo_examen", "resultado": resultado, "id_evidencia": respuesta.get("id_evidencia")}))
    return respuesta
