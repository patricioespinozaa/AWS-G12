"""Configuración del servidor local (solo variables de entorno del proceso, nunca .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from servidor import RAIZ

ADVERTENCIA = "Solo para uso local con datos sintéticos; sin autenticación."
HOST = "127.0.0.1"   # fijo: no configurable


@dataclass(frozen=True)
class ConfigServidor:
    inferencia_real: bool = False
    auditoria_path: Path = RAIZ / "auditoria.jsonl"
    puerto: int = 8000

    @classmethod
    def desde_entorno(cls) -> "ConfigServidor":
        # Falla en cerrado: cualquier valor distinto de "1" = inferencia simulada.
        real = os.environ.get("COPILOTO_INFERENCIA_REAL") == "1"

        ruta = Path(os.environ.get("COPILOTO_AUDITORIA_PATH") or "auditoria.jsonl")
        if not ruta.is_absolute():
            ruta = RAIZ / ruta

        texto_puerto = os.environ.get("COPILOTO_PUERTO", "8000")
        try:
            puerto = int(texto_puerto)
        except ValueError:
            raise ValueError("COPILOTO_PUERTO debe ser un entero entre 1024 y 65535") from None
        if not 1024 <= puerto <= 65535:
            raise ValueError("COPILOTO_PUERTO debe ser un entero entre 1024 y 65535")

        return cls(inferencia_real=real, auditoria_path=ruta.resolve(), puerto=puerto)
