import json

import numpy as np
import pandas as pd
import pytest

from servidor.configuracion import ConfigServidor
from servidor.inferencia import MODELO_SIMULADO, ClienteSimulado, origen_inferencia
from servidor.servicios import a_nativo, estado_aviso, indice_evidencia, leer_auditoria

ALERTA = {"alerta_id": "ALR-PAC-HLF-00002-20260708", "id_paciente": "PAC-HLF-00002",
          "tipo": "priorizacion", "prioridad_calculada": "alta",
          "motivos": [{"puntos": 20, "motivo": "Prioridad inicial baja",
                       "registro_ids": ["IC-HLF-00002"]}],
          "banderas_rojas": [{"bandera": "x", "registro_ids": ["EV-000010"]}],
          "inconsistencias": []}


def _mensaje():
    return {"role": "user", "content": "Analiza.\n\n" + json.dumps(ALERTA)}


def test_cliente_simulado_pide_linea_tiempo_y_luego_registra():
    c = ClienteSimulado()
    r1 = c.messages.create(messages=[_mensaje()])
    assert r1.content[0].name == "obtener_linea_tiempo"
    assert r1.content[0].input == {"pid": "PAC-HLF-00002"}
    assert r1.model == MODELO_SIMULADO and r1.usage.model_dump()["output_tokens"] == 0

    salida = json.dumps({"eventos": [{"fecha": "2026-07-01", "registro_id": "EV-000010",
                                      "fuente": "evento", "tipo": "visita_urgencia"}]})
    mensajes = [_mensaje(), {"role": "assistant", "content": r1.content},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t",
                                              "content": salida}]}]
    r2 = c.messages.create(messages=mensajes)
    reg = r2.content[0]
    assert reg.name == "registrar_analisis"
    assert reg.input["resumen"].startswith("[SIMULADO]")
    assert reg.input["prioridad_sugerida"] == "alta"
    assert [h["registro_ids"] for h in reg.input["hallazgos"]] == [["IC-HLF-00002"], ["EV-000010"]]
    assert reg.input["linea_tiempo_relevante"][0]["registro_id"] == "EV-000010"


def test_cliente_simulado_turno_forzado_registra_directo():
    r = ClienteSimulado().messages.create(messages=[_mensaje()],
                                          tool_choice={"type": "tool", "name": "registrar_analisis"})
    assert r.content[0].name == "registrar_analisis"


def test_origen_inferencia():
    assert origen_inferencia({"_meta": {"model": MODELO_SIMULADO}}) == "simulada"
    assert origen_inferencia({"_meta": {"model": "claude-x"}}) == "real"


def test_indice_evidencia():
    cron = {"solicitud": {"registro_id": "IC-1", "fecha_ingreso": "2026-01-01"},
            "eventos": [{"registro_id": "EV-1", "fuente": "evento", "fecha": "2026-02-01"},
                        {"registro_id": "CT-1", "fuente": "cita", "fecha": "2026-03-01"}]}
    idx = indice_evidencia(cron)
    assert set(idx) == {"IC-1", "EV-1", "CT-1"}
    assert idx["IC-1"]["fuente"] == "solicitud"
    assert idx["CT-1"]["origen"] == "perfiles.json › citaciones"


def test_leer_auditoria_archivo_ausente(tmp_path):
    assert leer_auditoria(tmp_path / "no.jsonl") == ({}, 0)


def test_leer_auditoria_linea_invalida(tmp_path):
    ruta = tmp_path / "a.jsonl"
    ruta.write_text('{"tipo": "analisis_ia", "alerta_id": "A", "analisis": {}}\n'
                    "no-json\n"
                    '{"tipo": "decision_medica", "alerta_id": "A"}\n'
                    '{"tipo": "tool", "alerta_id": "A"}\n', encoding="utf-8")
    grupos, invalidas = leer_auditoria(ruta)
    assert invalidas == 1
    assert len(grupos["A"]["analisis"]) == 1 and len(grupos["A"]["decisiones"]) == 1
    assert estado_aviso(grupos["A"]) == "decidido"
    assert estado_aviso(None) == "pendiente"


def test_a_nativo():
    out = a_nativo({"a": np.int64(3), "b": float("nan"), "c": pd.Timestamp("2026-01-02"),
                    "d": [np.float64(1.5)]})
    assert out == {"a": 3, "b": None, "c": "2026-01-02", "d": [1.5]}
    assert type(out["a"]) is int


def test_config_servidor(monkeypatch, tmp_path):
    for v in ("COPILOTO_INFERENCIA_REAL", "COPILOTO_AUDITORIA_PATH", "COPILOTO_PUERTO"):
        monkeypatch.delenv(v, raising=False)
    c = ConfigServidor.desde_entorno()
    assert not c.inferencia_real and c.puerto == 8000 and c.auditoria_path.name == "auditoria.jsonl"

    monkeypatch.setenv("COPILOTO_INFERENCIA_REAL", "true")       # solo "1" activa
    assert not ConfigServidor.desde_entorno().inferencia_real
    monkeypatch.setenv("COPILOTO_INFERENCIA_REAL", "1")
    monkeypatch.setenv("COPILOTO_AUDITORIA_PATH", str(tmp_path / "x.jsonl"))
    c = ConfigServidor.desde_entorno()
    assert c.inferencia_real and c.auditoria_path == (tmp_path / "x.jsonl").resolve()

    for malo in ("80", "abc", "70000"):
        monkeypatch.setenv("COPILOTO_PUERTO", malo)
        with pytest.raises(ValueError):
            ConfigServidor.desde_entorno()
