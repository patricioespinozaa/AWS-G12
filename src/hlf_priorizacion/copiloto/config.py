"""Configuración del modelo (``ConfigModelo``) desde variables de entorno, con validación estricta.

Variables:
- ``HLF_BEDROCK_MODEL_ID``: modelo de Bedrock; solo se aceptan los de ``MODELOS_PERMITIDOS`` (la cuenta
  del workshop tiene una lista de modelos permitidos y deniega el resto).
- ``HLF_COPILOTO_CONCURRENCIA``: llamadas simultáneas, entero de 1 a 8 (por defecto 4).
- ``HLF_BEDROCK_REGION``: región de Bedrock Runtime (por defecto ``us-east-1``).

Las credenciales nunca se configuran aquí: boto3 usa la cadena estándar de AWS (C7.1).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

MODELO_POR_DEFECTO: Final = "us.anthropic.claude-sonnet-5"
MODELO_RESPALDO: Final = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
MODELOS_PERMITIDOS: Final = frozenset({MODELO_POR_DEFECTO, MODELO_RESPALDO, "us.amazon.nova-pro-v1:0"})
# Bedrock rechaza ``temperature`` para estos modelos (ValidationException "temperature is deprecated").
# Decisión T-1 = A: a ellos no se les envía; al resto, temperatura 0 (C4.2).
MODELOS_SIN_TEMPERATURA: Final = frozenset({MODELO_POR_DEFECTO})
REGION_POR_DEFECTO: Final = "us-east-1"
CONCURRENCIA_POR_DEFECTO: Final = 4
CONCURRENCIA_MIN, CONCURRENCIA_MAX = 1, 8
TIMEOUT_S: Final = 60
# 4096 truncaba 33 de 173 respuestas reales de Sonnet 5 (stop_reason max_tokens) y se perdía
# nota_preconsulta, el último campo. 8192 ratificado por el usuario (C4.2, desviación 6).
MAX_TOKENS: Final = 8192
_RE_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")
_RE_ENTERO = re.compile(r"^\d{1,2}$")


class ErrorConfiguracion(ValueError):
    """Variable de entorno inválida: el copiloto no arranca (fail-closed)."""


class ErrorModeloNoPermitido(ErrorConfiguracion):
    """``HLF_BEDROCK_MODEL_ID`` fuera de la lista permitida: mismo código que un AccessDenied (exit 4)."""


@dataclass(frozen=True)
class ConfigModelo:
    model_id: str = MODELO_POR_DEFECTO
    region: str = REGION_POR_DEFECTO
    concurrencia: int = CONCURRENCIA_POR_DEFECTO
    temperatura: float = 0.0
    max_tokens: int = MAX_TOKENS
    timeout_s: int = TIMEOUT_S

    @property
    def envia_temperatura(self) -> bool:
        return self.model_id not in MODELOS_SIN_TEMPERATURA

    def inference_config(self) -> dict[str, float | int]:
        cfg: dict[str, float | int] = {"maxTokens": self.max_tokens}
        if self.envia_temperatura:
            cfg["temperature"] = self.temperatura
        return cfg


def config_desde_entorno(entorno: Mapping[str, str]) -> ConfigModelo:
    model_id = entorno.get("HLF_BEDROCK_MODEL_ID", "").strip() or MODELO_POR_DEFECTO
    if model_id not in MODELOS_PERMITIDOS:
        raise ErrorModeloNoPermitido(
            f"HLF_BEDROCK_MODEL_ID no está en la lista de modelos permitidos: {sorted(MODELOS_PERMITIDOS)}"
        )
    region = entorno.get("HLF_BEDROCK_REGION", "").strip() or REGION_POR_DEFECTO
    if not _RE_REGION.match(region):
        raise ErrorConfiguracion("HLF_BEDROCK_REGION no tiene formato de región de AWS (p. ej. us-east-1)")
    texto = entorno.get("HLF_COPILOTO_CONCURRENCIA", "").strip()
    if texto:
        if not _RE_ENTERO.match(texto) or not CONCURRENCIA_MIN <= int(texto) <= CONCURRENCIA_MAX:
            raise ErrorConfiguracion(
                f"HLF_COPILOTO_CONCURRENCIA debe ser un entero entre {CONCURRENCIA_MIN} y {CONCURRENCIA_MAX}"
            )
        concurrencia = int(texto)
    else:
        concurrencia = CONCURRENCIA_POR_DEFECTO
    return ConfigModelo(model_id=model_id, region=region, concurrencia=concurrencia)
