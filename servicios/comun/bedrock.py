"""Cliente de Amazon Bedrock para los servicios con IA (F0009, F0010). Solo AWS: boto3 y credenciales IAM.

- `converse_herramienta`: pide al modelo que responda llenando una herramienta (JSON con esquema): clasificación y
  generación de SQL sin tener que interpretar texto libre.
- `registrar`: una línea JSON por llamada (tokens, latencia, resultado) en CloudWatch, sin el texto clínico.
"""
from __future__ import annotations

import json
import logging
import threading
import time

from priorizacion import config

log = logging.getLogger("hlf.ia")
_clientes: dict[str, object] = {}
_lock = threading.Lock()


def cliente(servicio: str = "bedrock-runtime"):
    """bedrock-runtime o bedrock-agent-runtime, con tiempos de espera acotados (CloudFront corta a los 60 s)."""
    with _lock:
        if servicio not in _clientes:
            import boto3
            from botocore.config import Config
            _clientes[servicio] = boto3.client(
                servicio, region_name=config.BEDROCK_REGION,
                config=Config(connect_timeout=5, read_timeout=40, retries={"max_attempts": 2, "mode": "standard"}))
        return _clientes[servicio]


def registrar(evento: str, **campos) -> None:
    log.info(json.dumps({"evento": evento, **campos}, ensure_ascii=False, default=str))


class ErrorModelo(RuntimeError):
    pass


def converse_herramienta(sistema: str, texto: str, herramienta: dict, *, max_tokens: int = 1200,
                         modelo: str | None = None) -> tuple[dict, dict]:
    """Respuesta estructurada: el modelo debe usar `herramienta` ({name, description, schema}). Devuelve
    (entrada de la herramienta, {tokens_entrada, tokens_salida, latencia_ms})."""
    t0 = time.perf_counter()
    respuesta = cliente().converse(
        modelId=modelo or config.BEDROCK_MODEL_ID,
        system=[{"text": sistema}],
        messages=[{"role": "user", "content": [{"text": texto}]}],
        inferenceConfig={"maxTokens": max_tokens},
        toolConfig={"tools": [{"toolSpec": {"name": herramienta["name"], "description": herramienta["description"],
                                            "inputSchema": {"json": herramienta["schema"]}}}],
                    "toolChoice": {"tool": {"name": herramienta["name"]}}},
    )
    uso = respuesta.get("usage", {})
    medida = {"tokens_entrada": uso.get("inputTokens"), "tokens_salida": uso.get("outputTokens"),
              "latencia_ms": round((time.perf_counter() - t0) * 1000)}
    for bloque in respuesta.get("output", {}).get("message", {}).get("content", []):
        if "toolUse" in bloque and bloque["toolUse"].get("name") == herramienta["name"]:
            return bloque["toolUse"].get("input") or {}, medida
    raise ErrorModelo(f"El modelo no usó la herramienta {herramienta['name']} (stopReason={respuesta.get('stopReason')})")
