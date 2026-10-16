"""Una sola ejecución de ``hlf-copiloto`` a la vez por carpeta de salidas.

Dos ejecuciones simultáneas sobre el mismo corte calculan su lista de pendientes al inicio, sin ver lo que
la otra está guardando: ambas llaman al modelo por las mismas solicitudes (tokens duplicados) y agregan
análisis repetidos. Se usa un bloqueo exclusivo del sistema operativo sobre un archivo: si el proceso muere,
el sistema lo libera solo, así que no quedan bloqueos huérfanos.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

ARCHIVO_BLOQUEO = ".hlf-copiloto.lock"


class CopilotoEnEjecucion(Exception):
    """Ya hay otra ejecución de ``hlf-copiloto`` sobre la misma carpeta de salidas."""

    def __init__(self, ruta: Path) -> None:
        super().__init__(f"ya hay otra ejecución de hlf-copiloto usando {ruta.parent}")
        self.ruta = ruta


def _bloquear(f: IO[bytes]) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _desbloquear(f: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@contextmanager
def ejecucion_exclusiva(salidas: Path, id_ejecucion: str) -> Iterator[None]:
    """Mantiene el bloqueo mientras dura el bloque; lanza ``CopilotoEnEjecucion`` si ya está tomado."""
    salidas.mkdir(parents=True, exist_ok=True)
    ruta = salidas / ARCHIVO_BLOQUEO
    f = open(ruta, "a+b")  # noqa: SIM115 - el archivo debe seguir abierto mientras dura el bloqueo
    try:
        f.seek(0)
        if not _bloquear(f):
            raise CopilotoEnEjecucion(ruta)
        try:
            f.seek(0)
            f.truncate()
            f.write(f"{os.getpid()} {id_ejecucion}\n".encode())
            f.flush()
            yield
        finally:
            _desbloquear(f)
    finally:
        f.close()
