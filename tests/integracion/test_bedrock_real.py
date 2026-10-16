"""Prueba manual contra Amazon Bedrock real (consume tokens). Excluida por defecto.

Correr con ``uv run pytest -m bedrock -s``. Usa la cadena estándar de credenciales de AWS y el modelo de
``HLF_BEDROCK_MODEL_ID`` (por defecto ``us.anthropic.claude-sonnet-5``). Un solo análisis: IC-HLF-00002 al
2026-08-10, con las salidas del lote en una carpeta temporal.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest

from estrategias.copiloto import correr_lote
from hlf_priorizacion.copiloto.barrido import ConfigBarrido, ejecutar_barrido
from hlf_priorizacion.copiloto.cliente import ClienteBedrock
from hlf_priorizacion.copiloto.config import config_desde_entorno
from hlf_priorizacion.copiloto.persistencia import leer_analisis, leer_cohortes, leer_fallidos
from hlf_priorizacion.copiloto.prompt import cargar_prompt

RAIZ = Path(__file__).resolve().parents[2]
DATOS = RAIZ / "data" / "dataset_hlf_ambulatorio"
V = "reglas-v0.1.0"
CORTE = date(2026, 8, 10)


@pytest.mark.bedrock
def test_bedrock_real_00002_al_2026_08_10(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    if not (DATOS / "perfiles.json").is_file():
        pytest.skip(f"Dataset real no disponible en {DATOS}")
    salidas = tmp_path / "salidas"
    correr_lote(DATOS, salidas, [CORTE])
    config = config_desde_entorno(os.environ)
    cfg = ConfigBarrido([CORTE], False, date(2026, 10, 13), DATOS, salidas, V, 3,
                        filtro_ids=frozenset({"IC-HLF-00002"}))
    r = ejecutar_barrido(cfg, config, cargar_prompt(), ClienteBedrock(config), "prueba-bedrock-real")
    assert r.error_fatal is None, f"Bedrock rechazó la llamada: {r.error_fatal and r.error_fatal.codigo}"
    assert r.total_fallidas == 0, [f.motivo for f in leer_fallidos(salidas, CORTE, V)]
    assert r.analizadas == 1

    reg = leer_analisis(salidas, CORTE, V)[0]
    a = reg.analisis
    contexto_ids = {"EV-000004", "EV-000005"}
    documentados = [h for h in a.hallazgos if h.tipo == "documentado"]
    assert documentados and all(h.ids_registro for h in documentados)
    citados = {i for h in documentados for i in h.ids_registro}
    assert contexto_ids & citados, citados
    assert a.prioridad_sugerida == "critica" or (
        not a.acuerdo_con_motor.acuerdo and a.acuerdo_con_motor.motivo_discrepancia
    )
    cohorte = leer_cohortes(salidas, CORTE, V)["IC-HLF-00002"]
    assert a.riesgo_poblacional is not None
    assert (a.riesgo_poblacional.n, a.riesgo_poblacional.k, a.riesgo_poblacional.p) == (cohorte.n, cohorte.k, cohorte.p)
    assert a.metadatos.request_id and a.metadatos.estado == "pendiente_revision_medica"

    with capsys.disabled():
        print("\n=== Bedrock real: IC-HLF-00002 al 2026-08-10 ===")
        print(json.dumps({
            "model_id": reg.model_id,
            "request_id": a.metadatos.request_id,
            "tokens_entrada": reg.uso.tokens_entrada,
            "tokens_salida": reg.uso.tokens_salida,
            "latencia_ms": reg.uso.latencia_ms,
            "segundos_total": r.segundos,
            "intentos": reg.intentos,
            "correcciones": [c.model_dump() for c in reg.correcciones],
            "prioridad_sugerida": a.prioridad_sugerida,
            "acuerdo_con_motor": a.acuerdo_con_motor.model_dump(),
            "resumen": a.resumen,
            "hallazgos": [h.model_dump() for h in a.hallazgos],
            "riesgo_poblacional": a.riesgo_poblacional.model_dump(),
            "datos_faltantes": a.datos_faltantes,
        }, ensure_ascii=False, indent=1))
