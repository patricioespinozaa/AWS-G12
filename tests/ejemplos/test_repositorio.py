"""Repositorio: contexto a fecha de corte (R2, R3.3), línea de tiempo y cohortes (R9)."""

from __future__ import annotations

from datetime import date

import pytest

from ayudantes import FECHA_EXTRACCION, cita, evento, medicion, normalizado, perfil_base
from hlf_priorizacion.repositorio.cohortes import banda_edad, cohorte, wilson
from hlf_priorizacion.repositorio.contexto import (
    ErrorFechaCorte,
    Repositorio,
    contexto_a_fecha,
    edad_a_la_fecha,
)


def _perfil_completo() -> dict[str, object]:
    return perfil_base(
        eventos_clinicos=[
            evento("EV-000001", "2026-03-01", "visita_urgencia", "triage ESI 2", "grave"),
            evento("EV-000002", "2026-09-01", "control_aps", "control", "leve"),
        ],
        mediciones=[
            medicion("2026-02-01", "presion_sistolica", 120, "mmHg"),
            medicion("2026-08-01", "presion_sistolica", 150, "mmHg", True),
        ],
        citaciones=[
            cita("CT-000001", "2026-05-01", "no_asistio"),
            cita("CT-000002", "2026-09-15", "asistio", minutos=30),
        ],
    )


def test_contexto_filtra_por_corte_y_no_tiene_campos_de_equidad() -> None:
    p = normalizado(_perfil_completo())
    ctx = contexto_a_fecha(p, "IC-TST-00001", date(2026, 6, 1), FECHA_EXTRACCION)
    assert [e.id_evento for e in ctx.eventos] == ["EV-000001"]
    assert len(ctx.mediciones) == 1
    assert [c.id_cita for c in ctx.citas] == ["CT-000001"]
    assert ctx.solicitud.estado_a_la_fecha == "desconocido_a_la_fecha"
    assert ctx.solicitud.estado_extraccion == "en_espera"
    assert ctx.huella.startswith("sha256:")
    volcado = ctx.model_dump()
    for prohibido in ("comuna", "prevision", "nivel_socioeconomico", "nombre_fantasia"):
        assert prohibido not in str(volcado.keys())
        assert prohibido not in ctx.model_dump_json()


def test_estado_en_la_fecha_de_extraccion_y_edad_recalculada() -> None:
    p = normalizado(_perfil_completo())
    ctx = contexto_a_fecha(p, "IC-TST-00001", FECHA_EXTRACCION, FECHA_EXTRACCION)
    assert ctx.solicitud.estado_a_la_fecha == "en_espera"
    assert ctx.edad == 60
    assert edad_a_la_fecha(60, date(2025, 10, 13), FECHA_EXTRACCION) == 59
    assert edad_a_la_fecha(60, date(2025, 10, 14), FECHA_EXTRACCION) == 60


def test_fecha_corte_fuera_de_rango() -> None:
    p = normalizado(_perfil_completo())
    with pytest.raises(ErrorFechaCorte):
        contexto_a_fecha(p, "IC-TST-00001", date(2026, 10, 14), FECHA_EXTRACCION)
    with pytest.raises(ErrorFechaCorte):
        contexto_a_fecha(p, "IC-TST-00001", date(2025, 12, 31), FECHA_EXTRACCION)


def test_egreso_inferido_solo_si_atendido_en_la_extraccion() -> None:
    raw = _perfil_completo()
    raw["lista_espera"]["estado"] = "atendido"  # type: ignore[index]
    p = normalizado(raw)
    ctx = contexto_a_fecha(p, "IC-TST-00001", date(2026, 9, 20), FECHA_EXTRACCION)
    assert ctx.fecha_egreso_inferida == date(2026, 9, 15)
    assert ctx.id_cita_egreso_inferido == "CT-000002"
    antes = contexto_a_fecha(p, "IC-TST-00001", date(2026, 9, 14), FECHA_EXTRACCION)
    assert antes.fecha_egreso_inferida is None
    # En espera con cita asistida: no se infiere egreso (R3.4).
    p2 = normalizado(_perfil_completo())
    assert contexto_a_fecha(p2, "IC-TST-00001", date(2026, 9, 20), FECHA_EXTRACCION).fecha_egreso_inferida is None


def test_fallecido_a_la_fecha() -> None:
    raw = _perfil_completo()
    raw["paciente"].update({"fallecido": True, "fecha_defuncion": "2026-09-08"})  # type: ignore[attr-defined]
    p = normalizado(raw)
    assert not contexto_a_fecha(p, "IC-TST-00001", date(2026, 9, 7), FECHA_EXTRACCION).fallecido_a_la_fecha
    ctx = contexto_a_fecha(p, "IC-TST-00001", date(2026, 9, 8), FECHA_EXTRACCION)
    assert ctx.fallecido_a_la_fecha and ctx.fecha_defuncion == date(2026, 9, 8)
    assert contexto_a_fecha(p, "IC-TST-00001", date(2026, 9, 7), FECHA_EXTRACCION).fecha_defuncion is None


def test_linea_tiempo_citada_y_hasta_el_corte() -> None:
    repo = Repositorio([normalizado(_perfil_completo())], FECHA_EXTRACCION)
    linea = repo.linea_tiempo("PAC-TST-00001", date(2026, 6, 1))
    assert [r.tipo_registro for r in linea] == ["solicitud", "medicion", "evento", "cita"]
    assert all(r.fecha <= date(2026, 6, 1) and r.id_registro for r in linea)
    with pytest.raises(ErrorFechaCorte):
        repo.linea_tiempo("PAC-TST-00001", date(2026, 12, 1))


def test_wilson_valores_conocidos() -> None:
    inf, sup = wilson(3, 10)
    assert inf == pytest.approx(0.1078, abs=1e-4)
    assert sup == pytest.approx(0.6032, abs=1e-4)
    assert wilson(0, 5)[0] == 0.0
    with pytest.raises(ValueError):
        wilson(1, 0)


def _paciente(i: int, ingreso: str, origen: str, grave: str | None, edad: int = 60) -> dict[str, object]:
    raw = perfil_base(id_paciente=f"PAC-TST-{i:05d}")
    raw["paciente"]["edad"] = edad  # type: ignore[index]
    raw["lista_espera"].update(  # type: ignore[attr-defined]
        {"id_solicitud": f"IC-TST-{i:05d}", "fecha_ingreso_lista": ingreso, "origen_derivacion": origen}
    )
    if grave:
        raw["eventos_clinicos"] = [evento(f"EV-{i:06d}", grave, "hospitalizacion", "ingreso hospitalario", "grave")]
    return raw


def test_cohorte_relajacion_seguimiento_y_exclusion_propia() -> None:
    perfiles = [normalizado(_paciente(1, "2026-01-01", "Urgencia", "2026-01-15"))]
    # 6 con el mismo origen y 6 con otro: el nivel 0 tiene n = 6 (< 10) y se relaja a nivel 1 (n = 12).
    perfiles += [
        normalizado(_paciente(i, "2026-01-10", "Urgencia", "2026-02-01" if i % 2 else None)) for i in range(2, 8)
    ]
    perfiles += [normalizado(_paciente(i, "2026-01-10", "CESFAM/APS", None)) for i in range(8, 14)]
    # Sin seguimiento completo (ingreso a menos de 90 días del corte): no entra.
    perfiles.append(normalizado(_paciente(20, "2026-05-20", "Urgencia", "2026-05-25")))
    # Evento grave después de los 90 días: no cuenta como desenlace.
    perfiles.append(normalizado(_paciente(21, "2026-01-10", "Urgencia", "2026-05-01")))
    res = cohorte(perfiles, "IC-TST-00001", date(2026, 6, 1), FECHA_EXTRACCION)
    assert res.nivel_relajacion == 1
    assert res.n == 13 and res.k == 3
    assert res.clave == "I20|60-69"
    assert res.p == pytest.approx(3 / 13)
    assert res.ic95_inf is not None and res.ic95_inf <= res.p <= (res.ic95_sup or 0)
    assert res.advertencia_sesgo_acceso and not res.advertencia_muestra_pequena
    assert banda_edad(65, 20) == "60-79"
