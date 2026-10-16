"""Prompts versionados del copiloto (``copiloto/prompts/copiloto-vX.Y.Z/``).

Cada versión es una carpeta con ``sistema.md`` y ``usuario.md``. La huella SHA-256 cubre ambos textos,
así que cambiar una coma exige una versión nueva. ``version_prompt`` y la huella se guardan en cada
análisis.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Final

DIRECTORIO_PROMPTS = Path(__file__).resolve().parent / "prompts"
# v1.2.0 (decisión E-1 = C): no mencionar comuna, previsión ni NSE; inasistencias solo como riesgo de no
# asistir. Las carpetas v1.0.0 y v1.1.0 no se tocan: sus huellas están en los análisis guardados.
VERSION_PROMPT_POR_DEFECTO: Final = "copiloto-v1.2.0"
_RE_VERSION = re.compile(r"^copiloto-v\d+\.\d+\.\d+$")


class ErrorPrompt(ValueError):
    """Prompt ausente o inválido."""


@dataclass(frozen=True)
class Prompt:
    version_prompt: str
    huella: str
    sistema: str
    plantilla_usuario: str

    def usuario(self, *, id_solicitud: str, fecha_corte: str, version_reglas: str, datos_clinicos: str) -> str:
        return Template(self.plantilla_usuario).substitute(
            id_solicitud=id_solicitud,
            fecha_corte=fecha_corte,
            version_reglas=version_reglas,
            datos_clinicos=datos_clinicos,
        )


def huella_prompt(sistema: str, plantilla_usuario: str) -> str:
    texto = sistema + "\n\x00\n" + plantilla_usuario
    return "sha256:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()


def cargar_prompt(version: str = VERSION_PROMPT_POR_DEFECTO, directorio: Path = DIRECTORIO_PROMPTS) -> Prompt:
    if not _RE_VERSION.match(version):
        raise ErrorPrompt(f"versión de prompt inválida: {version}")
    carpeta = directorio / version
    try:
        sistema = (carpeta / "sistema.md").read_text(encoding="utf-8")
        usuario = (carpeta / "usuario.md").read_text(encoding="utf-8")
    except OSError as e:
        raise ErrorPrompt(f"no se pudo leer el prompt {version}: {type(e).__name__}") from e
    if "$datos_clinicos" not in usuario or "<datos_clinicos>" not in usuario:
        raise ErrorPrompt("la plantilla de usuario debe contener el bloque <datos_clinicos> con $datos_clinicos")
    return Prompt(version, huella_prompt(sistema, usuario), sistema, usuario)
