"""Logs de la app (F0013): JSON de una línea con `id_correlacion`, y sin datos personales.

En AWS (ECS o Lambda) cada línea es un objeto JSON que CloudWatch Logs Insights y los filtros de métricas leen por
campo (`$.evento`, `$.resultado`). Si el mensaje ya es un objeto JSON (los registros de Bedrock de F0008, los del OCR
de F0012), sus campos suben al primer nivel. En local queda texto legible, salvo HLF_LOG_FORMATO=json.

Identificadores sí (id_paciente, id_evidencia); nombres, RUT, teléfonos y correos no: el filtro los enmascara aunque
alguien los ponga en un mensaje por descuido.

    from servicios.comun import logs
    logs.configurar()                         # una vez, al arrancar
    with logs.correlacion("abc123"): ...      # todo lo que se registre dentro lleva ese id
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone

id_correlacion: contextvars.ContextVar[str | None] = contextvars.ContextVar("id_correlacion", default=None)
_ID_VALIDO = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

# Datos personales que nunca deben quedar en un log (se reemplazan por una marca)
_PATRONES = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[correo]"),
    (re.compile(r"(?<![\w-])\d{1,2}\.\d{3}\.\d{3}-[\dkK](?![\w])|(?<![\w-])\d{7,8}-[\dkK](?![\w])"), "[rut]"),
    (re.compile(r"\+?56[\s-]?9(?:[\s-]?\d){8}(?!\d)|(?<![\d-])9\d{8}(?!\d)"), "[telefono]"),
]
_CAMPOS_SENSIBLES = {"nombre", "telefono", "rut", "correo", "texto", "mensaje_paciente"}
_ESTANDAR = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


def enmascarar(texto: str) -> str:
    for patron, marca in _PATRONES:
        texto = patron.sub(marca, texto)
    return texto


def nuevo_id() -> str:
    return uuid.uuid4().hex


def valido(valor: str | None) -> str | None:
    """Un id que viene de afuera (cabecera) solo se usa si tiene forma de id: nada de texto libre en los logs."""
    return valor if valor and _ID_VALIDO.match(valor) else None


@contextlib.contextmanager
def correlacion(valor: str | None = None):
    token = id_correlacion.set(valido(valor) or nuevo_id())
    try:
        yield id_correlacion.get()
    finally:
        id_correlacion.reset(token)


def _limpio(valor):
    if isinstance(valor, str):
        return enmascarar(valor)
    if isinstance(valor, dict):
        return {k: ("[omitido]" if k in _CAMPOS_SENSIBLES else _limpio(v)) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_limpio(v) for v in valor]
    return valor


class FormatoJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        mensaje = record.getMessage()
        linea = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
                 "nivel": record.levelname, "logger": record.name}
        if (cid := id_correlacion.get()) is not None:
            linea["id_correlacion"] = cid
        estructurado = None
        if mensaje.startswith("{"):
            try:
                estructurado = json.loads(mensaje)
            except ValueError:
                pass
        if isinstance(estructurado, dict):
            linea.update({k: v for k, v in estructurado.items() if k not in linea})
        else:
            linea["mensaje"] = mensaje
        linea.update({k: v for k, v in vars(record).items() if k not in _ESTANDAR and k not in linea})
        if record.exc_info:
            linea["error"] = self.formatException(record.exc_info)
        return json.dumps(_limpio(linea), ensure_ascii=False, default=str)


class FormatoTexto(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(name)s %(levelname)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        texto = enmascarar(super().format(record))
        cid = id_correlacion.get()
        return f"{texto} [{cid[:8]}]" if cid else texto


def en_aws() -> bool:
    return bool(os.environ.get("ECS_CONTAINER_METADATA_URI_V4") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def configurar(nivel: int = logging.INFO, formato: str | None = None) -> logging.Handler:
    """Un solo handler a stdout para `hlf.*` (idempotente). JSON en AWS o con HLF_LOG_FORMATO=json."""
    formato = formato or os.environ.get("HLF_LOG_FORMATO") or ("json" if en_aws() else "texto")
    raiz = logging.getLogger("hlf")
    for h in list(raiz.handlers):
        if getattr(h, "_hlf", False):
            raiz.removeHandler(h)
    h = logging.StreamHandler(sys.stdout)
    h._hlf = True  # type: ignore[attr-defined]
    h.setFormatter(FormatoJSON() if formato == "json" else FormatoTexto())
    raiz.addHandler(h)
    raiz.setLevel(nivel)
    return h
