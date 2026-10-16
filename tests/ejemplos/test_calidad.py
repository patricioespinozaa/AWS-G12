"""Calidad de datos (R4, sección 7): un ejemplo por categoría."""

from __future__ import annotations

from datetime import date

from ayudantes import FECHA_EXTRACCION, cita, evento, medicion, normalizado, perfil_base
from hlf_priorizacion.calidad.auditoria import auditar, ids_descartados
from hlf_priorizacion.modelos import HallazgoDQ
from hlf_priorizacion.repositorio.contexto import contexto_a_fecha


def _hallazgos(raw: dict[str, object], corte: date = FECHA_EXTRACCION) -> dict[str, HallazgoDQ]:
    ctx = contexto_a_fecha(normalizado(raw), "IC-TST-00001", corte, FECHA_EXTRACCION)
    return {h.codigo: h for h in auditar(ctx)}


def test_perfil_limpio_sin_hallazgos() -> None:
    raw = perfil_base(mediciones=[medicion("2026-02-01", "presion_sistolica", 120, "mmHg")])
    assert _hallazgos(raw) == {}


def test_fuera_de_plausibilidad_se_descarta() -> None:
    raw = perfil_base(mediciones=[medicion("2026-02-01", "presion_sistolica", 400, "mmHg", True)])
    h = _hallazgos(raw)["fuera_de_plausibilidad"]
    assert h.nivel == "descartar"
    assert ids_descartados([h]) == set(h.ids_registro)


def test_repetida_mismo_dia_implausible() -> None:
    raw = perfil_base(
        mediciones=[
            medicion("2026-02-01", "presion_sistolica", 100, "mmHg"),
            medicion("2026-02-01", "presion_sistolica", 135, "mmHg"),
        ]
    )
    assert _hallazgos(raw)["medicion_repetida_implausible"].nivel == "verificar"
    raw_ok = perfil_base(
        mediciones=[
            medicion("2026-02-01", "presion_sistolica", 100, "mmHg"),
            medicion("2026-02-01", "presion_sistolica", 110, "mmHg"),
        ]
    )
    assert "medicion_repetida_implausible" not in _hallazgos(raw_ok)


def test_registro_previo_al_ingreso_es_info() -> None:
    raw = perfil_base(eventos_clinicos=[evento("EV-000001", "2025-12-01", "control_aps", "control", "leve")])
    assert _hallazgos(raw)["registro_previo_ingreso"].nivel == "info"


def test_registro_posterior_a_defuncion_se_descarta() -> None:
    raw = perfil_base(mediciones=[medicion("2026-09-10", "glicemia", 100, "mg/dL")])
    raw["paciente"].update({"fallecido": True, "fecha_defuncion": "2026-09-08"})  # type: ignore[attr-defined]
    raw["lista_espera"]["estado"] = "fallecido"  # type: ignore[index]
    h = _hallazgos(raw)["registro_posterior_defuncion"]
    assert h.nivel == "descartar"


def test_asistio_pero_sigue_en_espera() -> None:
    raw = perfil_base(citaciones=[cita("CT-000001", "2026-05-01", "asistio", minutos=30)])
    assert _hallazgos(raw)["asistio_en_espera"].ids_registro == ["CT-000001"]
    # En un corte pasado el estado es desconocido: no se emite.
    assert "asistio_en_espera" not in _hallazgos(raw, date(2026, 6, 1))


def test_fuera_de_rango_de_origen_inconsistente() -> None:
    raw = perfil_base(mediciones=[medicion("2026-02-01", "peak_flow", 500, "L/min", True)])
    h = _hallazgos(raw)["fuera_de_rango_inconsistente"]
    assert h.nivel == "verificar"


def test_especialidad_inferida_es_info() -> None:
    ev = evento("EV-000001", "2026-02-01", "control_aps", "control", "leve")
    ev["detalle"] = "sin plantilla"
    assert _hallazgos(perfil_base(eventos_clinicos=[ev]))["especialidad_evento_inferida"].nivel == "info"
