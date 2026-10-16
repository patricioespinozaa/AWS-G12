"""Lectura de ``perfiles.json`` y de las tablas planas CSV con manejo explícito de errores de E/S.

Los mensajes de error nunca incluyen contenido de los archivos (solo la ruta y el tipo de error).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ARCHIVO_PERFILES = "perfiles.json"
TABLAS_CONCILIABLES = ("pacientes", "lista_espera", "eventos_clinicos", "mediciones", "citaciones")


class ErrorCarga(Exception):
    """Error fatal de lectura de la fuente (el lote se detiene: fail-closed)."""


@dataclass(frozen=True)
class TablasPlanas:
    """Filas de los CSV por tabla. Una tabla ausente o ilegible queda en ``faltantes``."""

    filas: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    faltantes: tuple[str, ...] = ()


def cargar_perfiles(directorio: Path) -> list[Any]:
    """Lee ``perfiles.json``. Debe ser una lista JSON; si no, ``ErrorCarga``."""
    ruta = directorio / ARCHIVO_PERFILES
    try:
        texto = ruta.read_text(encoding="utf-8-sig")
    except FileNotFoundError as e:
        raise ErrorCarga(f"no existe el archivo de perfiles: {ruta}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise ErrorCarga(f"no se pudo leer {ruta}: {type(e).__name__}") from e
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ErrorCarga(f"{ruta} no es JSON válido (línea {e.lineno})") from e
    if not isinstance(datos, list):
        raise ErrorCarga(f"{ruta} debe contener una lista de perfiles")
    return datos


def cargar_csv(ruta: Path) -> list[dict[str, str]]:
    """Lee un CSV con encabezado. Lanza ``OSError``/``UnicodeDecodeError``/``csv.Error`` si falla."""
    with ruta.open(encoding="utf-8-sig", newline="") as f:
        return [dict(fila) for fila in csv.DictReader(f)]


def cargar_tablas(directorio: Path) -> TablasPlanas:
    """Carga las tablas conciliables. Las que faltan o fallan no detienen el lote: se informan."""
    filas: dict[str, list[dict[str, str]]] = {}
    faltantes: list[str] = []
    for nombre in TABLAS_CONCILIABLES:
        try:
            filas[nombre] = cargar_csv(directorio / f"{nombre}.csv")
        except (OSError, UnicodeDecodeError, csv.Error):
            faltantes.append(nombre)
    return TablasPlanas(filas=filas, faltantes=tuple(faltantes))
