"""Contratos compartidos: el fixture de la sección 6.8 valida y las reglas de AnalisisIA/Decision se cumplen."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hlf_priorizacion.modelos import AcuerdoMotor, Decision, Evaluacion, HallazgoIA

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "evaluacion_ejemplo.json"


def test_fixture_valida_contra_evaluacion() -> None:
    ev = Evaluacion.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    assert ev.estado_revision == "pendiente_revision_medica"
    assert ev.nivel_propuesto == "critica"
    assert all(f.ids_registro for f in ev.factores)
    assert round(sum(f.aporte for f in ev.factores), 2) == ev.puntaje


def test_evaluacion_rechaza_estado_revision_distinto() -> None:
    datos = FIXTURE.read_text(encoding="utf-8").replace('"pendiente_revision_medica"', '"aceptada"')
    with pytest.raises(ValidationError):
        Evaluacion.model_validate_json(datos)


def test_evaluacion_exclusion_exige_codigo() -> None:
    with pytest.raises(ValidationError):
        Evaluacion(
            id_solicitud="IC-HLF-00001",
            fecha_corte=date(2026, 10, 13),
            version_reglas="reglas-v0.1.0",
            huella_contexto="sha256:x",
            prioridad_inicial="baja",
            puntaje=None,
            nivel_calculado=None,
            nivel_propuesto=None,
            tipo_resultado="exclusion",
            confianza="alta",
        )


def test_hallazgo_documentado_exige_ids() -> None:
    with pytest.raises(ValidationError):
        HallazgoIA(texto="x", tipo="documentado", ids_registro=[])
    assert HallazgoIA(texto="x", tipo="inferido").ids_registro == []


def test_acuerdo_motor_exige_motivo_si_discrepa() -> None:
    with pytest.raises(ValidationError):
        AcuerdoMotor(acuerdo=False)
    assert AcuerdoMotor(acuerdo=False, motivo_discrepancia="sin bandera").motivo_discrepancia


def _decision(**kw: object) -> Decision:
    base: dict[str, object] = {
        "id_decision": "D-1",
        "id_solicitud": "IC-HLF-00002",
        "fecha_corte": date(2026, 7, 20),
        "version_reglas": "reglas-v0.1.0",
        "prioridad_propuesta": "critica",
        "usuario": "medico-demo",
        "timestamp": datetime(2026, 10, 15, tzinfo=UTC),
    }
    base.update(kw)
    return Decision.model_validate(base)


def test_decision_ajustada_exige_prioridad_y_motivo() -> None:
    with pytest.raises(ValidationError):
        _decision(decision="ajustada", motivo="x")
    with pytest.raises(ValidationError):
        _decision(decision="ajustada", prioridad_final="alta")
    assert _decision(decision="ajustada", prioridad_final="alta", motivo="control reciente").prioridad_final


def test_decision_rechazada_exige_motivo_y_aceptada_coherente() -> None:
    with pytest.raises(ValidationError):
        _decision(decision="rechazada")
    with pytest.raises(ValidationError):
        _decision(decision="aceptada", prioridad_final="baja")
    assert _decision(decision="aceptada").decision == "aceptada"
