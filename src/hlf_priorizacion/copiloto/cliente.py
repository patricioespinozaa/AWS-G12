"""Cliente del modelo (C4): interfaz ``ClienteModelo``, ``ClienteBedrock`` (Converse) y ``ClienteFalso``.

- Una sola herramienta ``registrar_analisis`` cuyo esquema es ``analisis-v1`` sin ``metadatos`` y
  ``toolChoice`` forzado a ella (C4.1); temperatura 0 y timeout de lectura de 60 s (C4.2).
- Los reintentos de botocore se desactivan: los hace ``con_reintentos`` (hasta 3, espera exponencial con
  jitter) solo ante limitación, servicio no disponible o timeout (C4.4).
- Permisos denegados, modelo no permitido o credenciales vencidas son fatales (fail-closed).

Las credenciales salen de la cadena estándar de AWS; este módulo nunca las lee ni las registra (C7.1).
"""

from __future__ import annotations

import copy
import json
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol

from hlf_priorizacion.copiloto.config import MODELO_RESPALDO, ConfigModelo
from hlf_priorizacion.modelos import AnalisisIA

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime.client import BedrockRuntimeClient

NOMBRE_HERRAMIENTA: Final = "registrar_analisis"
DESCRIPCION_HERRAMIENTA: Final = (
    "Registra el análisis estructurado y citado de la solicitud (esquema analisis-v1). "
    "Es la única forma de responder."
)
CODIGOS_REINTENTABLES: Final = frozenset(
    {"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"}
)
CODIGOS_PERMISOS: Final = frozenset(
    {
        "AccessDeniedException",
        "UnrecognizedClientException",
        "ExpiredTokenException",
        "ExpiredToken",
        "InvalidSignatureException",
        "ResourceNotFoundException",
    }
)
CODIGOS_CREDENCIALES: Final = frozenset(
    {"UnrecognizedClientException", "ExpiredTokenException", "ExpiredToken", "InvalidSignatureException"}
)
MAX_REINTENTOS: Final = 3


# --------------------------------------------------------------------------- errores


class ErrorModelo(Exception):
    """Fallo de una llamada al modelo. ``codigo`` es seguro para logs (sin texto del modelo ni datos)."""

    def __init__(self, codigo: str, mensaje: str = "") -> None:
        super().__init__(mensaje or codigo)
        self.codigo = codigo


class ErrorReintentable(ErrorModelo):
    """Limitación, servicio no disponible o timeout."""


class ErrorPermisos(ErrorModelo):
    """Permiso denegado, modelo no permitido o credenciales inválidas: el comando se detiene (exit 4)."""

    @property
    def sugerencia(self) -> str:
        if self.codigo in CODIGOS_CREDENCIALES or self.codigo == "sin_credenciales":
            return "Renueve las credenciales de AWS (cadena estándar: perfil o variables de entorno) y reintente."
        return (
            "El modelo no está permitido para esta cuenta o rol. Pruebe con el modelo de respaldo: "
            f"HLF_BEDROCK_MODEL_ID={MODELO_RESPALDO}"
        )


# --------------------------------------------------------------------------- petición y respuesta


@dataclass(frozen=True)
class PeticionModelo:
    id_solicitud: str  # solo para trazas y para el cliente falso; no se envía al modelo
    sistema: str
    usuario: str
    herramienta: dict[str, Any]
    intento: int = 1


@dataclass(frozen=True)
class RespuestaModelo:
    entrada_herramienta: dict[str, Any] | None
    stop_reason: str
    request_id: str | None
    tokens_entrada: int
    tokens_salida: int
    latencia_ms: int
    crudo: str  # JSON del mensaje de salida, solo para salidas/ (nunca a logs)


class ClienteModelo(Protocol):
    def converse(self, peticion: PeticionModelo, config: ConfigModelo) -> RespuestaModelo: ...


# --------------------------------------------------------------------------- herramienta


def _inline(nodo: Any, defs: dict[str, Any]) -> Any:
    if isinstance(nodo, dict):
        if "$ref" in nodo:
            nombre = str(nodo["$ref"]).rsplit("/", 1)[-1]
            resto = {k: v for k, v in nodo.items() if k != "$ref"}
            return {**_inline(copy.deepcopy(defs[nombre]), defs), **_inline(resto, defs)}
        return {k: _inline(v, defs) for k, v in nodo.items() if k != "$defs"}
    if isinstance(nodo, list):
        return [_inline(v, defs) for v in nodo]
    return nodo


def esquema_herramienta() -> dict[str, Any]:
    """JSON Schema de ``AnalisisIA`` sin ``metadatos`` (los escribe el sistema), con ``$defs`` en línea."""
    esquema = AnalisisIA.model_json_schema()
    defs = esquema.get("$defs", {})
    propiedades = {k: v for k, v in esquema["properties"].items() if k not in {"metadatos", "version_esquema"}}
    requeridos = [r for r in esquema.get("required", []) if r not in {"metadatos", "version_esquema"}]
    salida = {
        "type": "object",
        "properties": _inline(propiedades, defs),
        "required": requeridos,
        "additionalProperties": False,
    }
    resultado: dict[str, Any] = _inline(salida, defs)
    return resultado


def especificacion_herramienta() -> dict[str, Any]:
    return {
        "toolSpec": {
            "name": NOMBRE_HERRAMIENTA,
            "description": DESCRIPCION_HERRAMIENTA,
            "inputSchema": {"json": esquema_herramienta()},
        }
    }


# --------------------------------------------------------------------------- Bedrock


def _clasificar_codigo(codigo: str, mensaje: str) -> ErrorModelo:
    if codigo in CODIGOS_REINTENTABLES:
        return ErrorReintentable(codigo)
    if codigo in CODIGOS_PERMISOS:
        return ErrorPermisos(codigo)
    if codigo == "ValidationException" and "model" in mensaje.lower() and (
        "access" in mensaje.lower() or "invalid" in mensaje.lower() or "not supported" in mensaje.lower()
    ):
        return ErrorPermisos("modelo_no_permitido")
    return ErrorModelo(codigo)


def _extraer_herramienta(contenido: list[Any]) -> dict[str, Any] | None:
    for bloque in contenido:
        if isinstance(bloque, dict):
            uso = bloque.get("toolUse")
            if isinstance(uso, dict) and uso.get("name") == NOMBRE_HERRAMIENTA and isinstance(uso.get("input"), dict):
                entrada: dict[str, Any] = uso["input"]
                return entrada
    return None


class ClienteBedrock:
    """Bedrock Runtime ``Converse`` con ``toolChoice`` forzado."""

    def __init__(self, config: ConfigModelo, cliente: BedrockRuntimeClient | None = None) -> None:
        if cliente is None:
            import boto3
            from botocore.config import Config

            cliente = boto3.client(
                "bedrock-runtime",
                region_name=config.region,
                config=Config(
                    read_timeout=config.timeout_s,
                    connect_timeout=10,
                    retries={"max_attempts": 1, "mode": "standard"},
                ),
            )
        self._cliente = cliente

    def converse(self, peticion: PeticionModelo, config: ConfigModelo) -> RespuestaModelo:
        from botocore.exceptions import (
            ClientError,
            ConnectTimeoutError,
            EndpointConnectionError,
            NoCredentialsError,
            ReadTimeoutError,
        )

        inicio = time.monotonic()
        try:
            r = self._cliente.converse(
                modelId=config.model_id,
                system=[{"text": peticion.sistema}],
                messages=[{"role": "user", "content": [{"text": peticion.usuario}]}],
                toolConfig={
                    "tools": [peticion.herramienta],  # type: ignore[list-item]
                    "toolChoice": {"tool": {"name": NOMBRE_HERRAMIENTA}},
                },
                inferenceConfig=config.inference_config(),  # type: ignore[arg-type]
            )
        except ClientError as e:
            error = e.response.get("Error", {})
            raise _clasificar_codigo(str(error.get("Code", "ClientError")), str(error.get("Message", ""))) from e
        except (ReadTimeoutError, ConnectTimeoutError, EndpointConnectionError) as e:
            raise ErrorReintentable("timeout") from e
        except NoCredentialsError as e:
            raise ErrorPermisos("sin_credenciales") from e
        latencia = int((time.monotonic() - inicio) * 1000)
        mensaje = r.get("output", {}).get("message", {})
        contenido = list(mensaje.get("content", []))
        uso = r.get("usage", {})
        return RespuestaModelo(
            entrada_herramienta=_extraer_herramienta(contenido),
            stop_reason=str(r.get("stopReason", "")),
            request_id=r.get("ResponseMetadata", {}).get("RequestId"),
            tokens_entrada=int(uso.get("inputTokens", 0)),
            tokens_salida=int(uso.get("outputTokens", 0)),
            latencia_ms=latencia,
            crudo=json.dumps(contenido, ensure_ascii=False, default=str),
        )


# --------------------------------------------------------------------------- reintentos


def espera_s(reintento: int, aleatorio: Callable[[], float], base_s: float = 1.0, tope_s: float = 20.0) -> float:
    """Espera exponencial con jitter: ``base * 2^(n-1) * U(0.5, 1.5)``, acotada por ``tope_s``."""
    factor = 2.0 ** (reintento - 1)
    return float(min(tope_s, base_s * factor * (0.5 + aleatorio())))


def con_reintentos(
    cliente: ClienteModelo,
    peticion: PeticionModelo,
    config: ConfigModelo,
    *,
    max_reintentos: int = MAX_REINTENTOS,
    dormir: Callable[[float], None] = time.sleep,
    aleatorio: Callable[[], float] = random.random,
) -> RespuestaModelo:
    """Llama al modelo; reintenta solo ``ErrorReintentable``. Otros errores se propagan de inmediato."""
    reintento = 0
    while True:
        try:
            return cliente.converse(peticion, config)
        except ErrorReintentable:
            if reintento >= max_reintentos:
                raise
            reintento += 1
            dormir(espera_s(reintento, aleatorio))


# --------------------------------------------------------------------------- cliente falso (pruebas)


Responder = Callable[[PeticionModelo], "RespuestaModelo | Exception"]


def respuesta_falsa(entrada: dict[str, Any] | None, request_id: str = "req-falso") -> RespuestaModelo:
    return RespuestaModelo(
        entrada_herramienta=entrada,
        stop_reason="tool_use",
        request_id=request_id,
        tokens_entrada=100,
        tokens_salida=50,
        latencia_ms=1,
        crudo=json.dumps(entrada, ensure_ascii=False, sort_keys=True),
    )


@dataclass
class ClienteFalso:
    """Cliente determinista para pruebas: ``responder`` decide la respuesta o el error de cada petición."""

    responder: Responder
    llamadas: list[PeticionModelo] = field(default_factory=list)
    _candado: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def converse(self, peticion: PeticionModelo, config: ConfigModelo) -> RespuestaModelo:
        with self._candado:
            self.llamadas.append(peticion)
        resultado = self.responder(peticion)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado
