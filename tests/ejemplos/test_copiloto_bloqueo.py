"""Una sola ejecución de hlf-copiloto a la vez (defecto encontrado en uso real: dos ejecuciones simultáneas
del 2026-10-13 duplicaron 44 análisis y sus llamadas al modelo)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from hlf_priorizacion.copiloto.bloqueo import CopilotoEnEjecucion, ejecucion_exclusiva

_OTRO_PROCESO = """
import sys, time
from pathlib import Path
from hlf_priorizacion.copiloto.bloqueo import CopilotoEnEjecucion, ejecucion_exclusiva
try:
    with ejecucion_exclusiva(Path(sys.argv[1]), "otro"):
        print("TOMADO")
except CopilotoEnEjecucion:
    print("OCUPADO")
"""


def _en_otro_proceso(salidas: Path) -> str:
    # Entrada fija del propio test (intérprete actual + script constante + carpeta temporal).
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _OTRO_PROCESO, str(salidas)], capture_output=True, text=True, timeout=60, check=True
    )
    return r.stdout.strip()


def test_segunda_ejecucion_en_otro_proceso_se_rechaza(tmp_path: Path) -> None:
    with ejecucion_exclusiva(tmp_path, "primera"):
        assert _en_otro_proceso(tmp_path) == "OCUPADO"
    assert _en_otro_proceso(tmp_path) == "TOMADO"  # al terminar, se libera


def test_bloqueo_se_libera_ante_un_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), ejecucion_exclusiva(tmp_path, "con-error"):
        raise RuntimeError("falla")
    with ejecucion_exclusiva(tmp_path, "siguiente"):
        pass


def test_ejecuciones_sobre_salidas_distintas_no_se_bloquean(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    with ejecucion_exclusiva(a, "a"):
        assert _en_otro_proceso(b) == "TOMADO"


def test_excepcion_indica_la_carpeta(tmp_path: Path) -> None:
    e = CopilotoEnEjecucion(tmp_path / ".hlf-copiloto.lock")
    assert str(tmp_path) in str(e)
