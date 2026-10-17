"""Privacidad del repositorio: lo que no debe versionarse (CLAUDE.md, "Datos y privacidad").

Los notebooks se versionan sin salidas: una salida puede imprimir filas del dataset del hospital (IDs, edades,
diagnósticos, fechas). Para limpiarlos antes de commitear:

    python -m jupyter nbconvert --clear-output --inplace notebooks/*.ipynb
"""
import json
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


def _versionados(*patrones: str) -> list[str]:
    try:
        salida = subprocess.run(["git", "ls-files", *patrones], cwd=RAIZ, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("Sin git: no se puede saber qué archivos están versionados")
    return [l for l in salida.stdout.splitlines() if l]


def test_notebooks_sin_salidas():
    con_salidas = []
    for ruta in _versionados("*.ipynb"):
        nb = json.loads((RAIZ / ruta).read_text(encoding="utf-8"))
        celdas = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
        if any(c.get("outputs") or c.get("execution_count") is not None for c in celdas):
            con_salidas.append(ruta)
    assert not con_salidas, (f"Notebooks con salidas (pueden exponer filas del dataset): {con_salidas}. "
                             "Límpialos con: python -m jupyter nbconvert --clear-output --inplace <notebook>")


def test_sin_datos_ni_secretos_versionados():
    prohibidos = [r for r in _versionados()
                  if Path(r).name == ".env" or r.endswith((".pem", ".key", ".sqlite", ".parquet"))
                  or (r.endswith(".csv") and not r.startswith("data/synthetic/"))]
    assert not prohibidos, f"Archivos que no deben versionarse (datos o secretos): {prohibidos}"
