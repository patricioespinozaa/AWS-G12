"""Exporta el JSON Schema 2020-12 del contrato a ``contrato/contrato-v1.0.0.schema.json``.

Uso: ``uv run python -m hlf_priorizacion.contrato.esquema_json``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hlf_priorizacion.contrato.catalogos import VERSION_CONTRATO
from hlf_priorizacion.contrato.esquema import PerfilCrudo

RUTA_ESQUEMA = Path(__file__).resolve().parent / f"{VERSION_CONTRATO}.schema.json"


def esquema_contrato() -> dict[str, Any]:
    esquema = PerfilCrudo.model_json_schema(mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:hlf-priorizacion:{VERSION_CONTRATO}",
        **esquema,
    }


def texto_esquema() -> str:
    return json.dumps(esquema_contrato(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def exportar(ruta: Path = RUTA_ESQUEMA) -> Path:
    ruta.write_text(texto_esquema(), encoding="utf-8", newline="\n")
    return ruta


if __name__ == "__main__":
    print(exportar())
