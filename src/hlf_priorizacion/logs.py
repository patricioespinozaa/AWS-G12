"""Logging estructurado JSON (SECURITY-03).

Cada línea lleva ``timestamp``, ``nivel``, ``id_ejecucion`` y ``mensaje``. Solo se agregan campos de
una lista permitida (IDs, conteos, códigos y tipos de error): nunca valores clínicos ni datos
personales. Las excepciones se registran por tipo, sin su mensaje ni traza (podrían contener datos).
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Final

_id_ejecucion: ContextVar[str] = ContextVar("id_ejecucion", default="-")

CAMPOS_PERMITIDOS: Final = frozenset(
    {
        "id_solicitud",
        "id_paciente",
        "fecha_corte",
        "fecha_extraccion",
        "version_reglas",
        "version_contrato",
        "codigo",
        "tipo_error",
        "etapa",
        "ruta",
        "conteos",
        "cobertura_pct",
        "tablas",
        "n",
        # U2 (copiloto): solo identificadores, conteos, tokens, latencia y códigos (C7.2).
        "model_id",
        "request_id",
        "version_prompt",
        "tokens_entrada",
        "tokens_salida",
        "latencia_ms",
        "intento",
        "motivo",
        "desde",
        "hasta",
        "llamadas",
        "segundos",
    }
)
_TIPOS_SEGUROS = (str, int, float, bool, type(None))

NOMBRE_LOGGER: Final = "hlf_priorizacion"


def fijar_id_ejecucion(valor: str) -> None:
    _id_ejecucion.set(valor)


def _seguro(valor: Any) -> Any:
    if isinstance(valor, _TIPOS_SEGUROS):
        return valor
    if isinstance(valor, dict):
        return {str(k): v for k, v in valor.items() if isinstance(v, _TIPOS_SEGUROS)}
    if isinstance(valor, list | tuple):
        return [v for v in valor if isinstance(v, _TIPOS_SEGUROS)]
    return str(type(valor).__name__)


class FormatoJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        datos: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "nivel": record.levelname,
            "id_ejecucion": _id_ejecucion.get(),
            "mensaje": record.getMessage(),
        }
        campos = getattr(record, "campos", None)
        if isinstance(campos, dict):
            for clave, valor in campos.items():
                if clave in CAMPOS_PERMITIDOS:
                    datos[clave] = _seguro(valor)
        if record.exc_info and record.exc_info[0] is not None:
            datos["tipo_error"] = record.exc_info[0].__name__
        return json.dumps(datos, ensure_ascii=False, sort_keys=True)


def configurar_logging(nivel: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(NOMBRE_LOGGER)
    logger.handlers.clear()
    manejador = logging.StreamHandler(sys.stderr)
    manejador.setFormatter(FormatoJSON())
    logger.addHandler(manejador)
    logger.setLevel(nivel)
    logger.propagate = False
    return logger


def obtener_logger() -> logging.Logger:
    return logging.getLogger(NOMBRE_LOGGER)
