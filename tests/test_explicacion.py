"""Explicaciones con IA (F0008) con un cliente de Bedrock simulado: sin AWS ni dataset.

Cubre: texto aceptado, descartado por la validación (referencias, fechas ISO y en prosa, nivel), guardrail, texto
incompleto, error de AWS → plantilla, caché por huella y el log estructurado por llamada.
"""
import json
import logging
from datetime import date

import pytest

from priorizacion import config
from priorizacion import explicacion as X
from priorizacion.motor import Factor, Resultado

R = Resultado(
    id_solicitud="IC-HLF-00002", id_paciente="PAC-HLF-00002", especialidad="Cardiología",
    fecha_corte=date(2026, 8, 10), excluido=False, motivo_exclusion=None, puntaje=30.0, puntaje_nivel=28.0,
    nivel_calculado="alta", nivel_propuesto="alta", prioridad_inicial="baja", prioridad_vigente="baja",
    cambio="sube", alerta=False,
    factores=[Factor("evento", "Hospitalización: ingreso hospitalario (grave)", 8.7, "evento", "evento",
                     "EV-000005", date(2026, 8, 6)),
              Factor("evento", "Urgencia: triage ESI 2 (grave)", 6.8, "evento", "evento", "EV-000004",
                     date(2026, 7, 20))])
BUENO = ("La propuesta sube a prioridad alta por la hospitalización del 6 de agosto [EV-000005] y la urgencia del "
         "2026-07-20 [EV-000004]. La decisión final es del equipo clínico.")


class BedrockFalso:
    def __init__(self, texto=BUENO, parada="end_turn", error=None):
        self.texto, self.parada, self.error, self.pedidos = texto, parada, error, []

    def converse(self, **pedido):
        self.pedidos.append(pedido)
        if self.error:
            raise self.error
        return {"output": {"message": {"role": "assistant", "content": [{"text": self.texto}]}},
                "stopReason": self.parada, "usage": {"inputTokens": 900, "outputTokens": 120}}


class CacheMemoria:
    def __init__(self):
        self.datos = {}

    def explicacion_guardada(self, huella, modelo, version_prompt):
        return self.datos.get((huella, modelo, version_prompt))

    def guardar_explicacion(self, huella, modelo, version_prompt, id_solicitud, texto):
        self.datos[(huella, modelo, version_prompt)] = texto


@pytest.fixture
def bedrock(monkeypatch):
    falso = BedrockFalso()
    monkeypatch.setattr(config, "LLM_PROVEEDOR", "bedrock")
    monkeypatch.setattr(config, "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    monkeypatch.setattr(config, "BEDROCK_GUARDRAIL_ID", "")
    monkeypatch.setattr(X, "_cliente", lambda: falso)
    return falso


def test_texto_aceptado_y_lo_que_se_envia(bedrock):
    e = X.explicacion_llm(R)
    assert e.fuente == "bedrock" and e.texto == BUENO and e.modelo.startswith("us.anthropic")
    (pedido,) = bedrock.pedidos
    assert pedido["modelId"] == config.BEDROCK_MODEL_ID and pedido["inferenceConfig"]["maxTokens"] > 0
    carga = json.loads(pedido["messages"][0]["content"][0]["text"])
    assert {f["ref"] for f in carga["factores"]} == {"EV-000005", "EV-000004"}
    assert "nombre" not in json.dumps(carga) and "rut" not in json.dumps(carga).lower()   # solo factores
    assert "guardrailConfig" not in pedido


@pytest.mark.parametrize("texto, motivo", [
    ("Sube a prioridad alta por la urgencia [EV-999999].", "referencias"),
    ("Sube a prioridad alta por la hospitalización del 2026-08-04 [EV-000005].", "fechas"),
    ("Sube a prioridad alta por la hospitalización del 4 de agosto [EV-000005].", "4 de agosto"),
    ("Sube a prioridad alta: hospitalización el 06/08/2025 [EV-000005].", "6 de agosto de 2025"),
    ("Se propone un cambio por la hospitalización [EV-000005].", "nivel propuesto"),
])
def test_texto_descartado_vuelve_a_la_plantilla(bedrock, texto, motivo):
    bedrock.texto = texto
    e = X.explicacion_llm(R)
    assert e.fuente == "plantilla" and e.texto == X.explicacion_plantilla(R)
    assert motivo in e.aviso


def test_markdown_se_limpia_antes_de_validar(bedrock):
    bedrock.texto = "# Explicación\n\nLa propuesta **sube** a prioridad alta [EV-000005]. Decide el equipo clínico."
    e = X.explicacion_llm(R)
    assert e.fuente == "bedrock" and "#" not in e.texto and "**" not in e.texto


@pytest.mark.parametrize("parada, aviso", [("guardrail_intervened", "guardrail"), ("max_tokens", "incompleto")])
def test_guardrail_o_texto_incompleto(bedrock, parada, aviso):
    bedrock.parada = parada
    e = X.explicacion_llm(R)
    assert e.fuente == "plantilla" and aviso in e.aviso


def test_error_de_aws_nunca_rompe(bedrock):
    bedrock.error = RuntimeError("AccessDeniedException")
    e = X.explicacion_llm(R)
    assert e.fuente == "plantilla" and "No se pudo llamar a Bedrock" in e.aviso


def test_con_guardrail_configurado(bedrock, monkeypatch):
    monkeypatch.setattr(config, "BEDROCK_GUARDRAIL_ID", "gr-123")
    monkeypatch.setattr(config, "BEDROCK_GUARDRAIL_VERSION", "1")
    X.explicacion_llm(R)
    assert bedrock.pedidos[0]["guardrailConfig"] == {"guardrailIdentifier": "gr-123", "guardrailVersion": "1",
                                                      "trace": "disabled"}


def test_la_misma_propuesta_no_vuelve_a_llamar(bedrock):
    cache = CacheMemoria()
    a = X.explicacion_llm(R, "huella-1", cache)
    b = X.explicacion_llm(R, "huella-1", cache)
    assert len(bedrock.pedidos) == 1 and a.texto == b.texto and b.desde_cache
    X.explicacion_llm(R, "huella-2", cache)                     # otros datos: sí llama
    assert len(bedrock.pedidos) == 2


def test_un_texto_descartado_no_se_guarda(bedrock):
    cache = CacheMemoria()
    bedrock.texto = "Sube a prioridad alta [EV-999999]."
    X.explicacion_llm(R, "huella-1", cache)
    assert cache.datos == {}


def test_log_estructurado_por_llamada(bedrock, caplog):
    with caplog.at_level(logging.INFO, logger="hlf.explicacion"):
        X.explicacion_llm(R, "huella-1")
    ev = json.loads(caplog.records[-1].getMessage())
    assert ev["evento"] == "explicacion_ia" and ev["resultado"] == "aceptado"
    assert ev["tokens_entrada"] == 900 and ev["tokens_salida"] == 120 and ev["latencia_ms"] is not None
    assert ev["huella"] == "huella-1" and BUENO not in caplog.text     # el texto clínico no va al log


@pytest.mark.parametrize("proveedor", ["", "anthropic", "openai", "BEDROCKX"])
def test_solo_bedrock_activa_el_llm(bedrock, monkeypatch, proveedor):
    monkeypatch.setattr(config, "LLM_PROVEEDOR", proveedor)
    e = X.explicacion_llm(R)
    assert e.fuente == "plantilla" and bedrock.pedidos == []
