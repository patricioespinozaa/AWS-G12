"""Registro de auditoría local: JSONL de solo agregado (adaptador del MVP para Firehose + S3 Object Lock).

Nunca se trunca ni se reescribe el archivo: solo se abre en modo ``"a"``. Los eventos llevan IDs y
huellas, no valores clínicos.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

TipoEvento = Literal[
    "llamada_modelo",
    "herramienta",
    "analisis_ia",
    "analisis_omitido",
    "evaluacion_motor",
    "vista",
    "decision_medica",
    "error_proceso",
    "cambio_parametros",
]

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def nuevo_ulid(ms: int | None = None, aleatorio: bytes | None = None) -> str:
    """ULID: 48 bits de milisegundos + 80 bits aleatorios, en base32 de Crockford (26 caracteres)."""
    ms = int(time.time() * 1000) if ms is None else ms
    aleatorio = os.urandom(10) if aleatorio is None else aleatorio
    valor = (ms << 80) | int.from_bytes(aleatorio, "big")
    return "".join(_CROCKFORD[(valor >> (5 * i)) & 31] for i in range(25, -1, -1))


def _ahora_utc() -> datetime:
    return datetime.now(UTC)


class RegistroAuditoria:
    def __init__(
        self,
        ruta: Path,
        id_ejecucion: str,
        actor: str = "sistema:motor",
        reloj: Callable[[], datetime] = _ahora_utc,
    ) -> None:
        self.ruta = ruta
        self.id_ejecucion = id_ejecucion
        self.actor = actor
        self._reloj = reloj

    def registrar(self, tipo: TipoEvento, **campos: Any) -> dict[str, Any]:
        evento: dict[str, Any] = {
            "id_auditoria": nuevo_ulid(),
            "tipo": tipo,
            "timestamp": self._reloj().astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "actor": self.actor,
            "id_ejecucion": self.id_ejecucion,
            **campos,
        }
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self.ruta.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(evento, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        return evento
