"""Ingesta: carga con errores controlados, normalización, ID de medición y conciliación."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ayudantes import cita, evento, medicion, perfil_base, valido
from hlf_priorizacion.ingesta.carga import ErrorCarga, TablasPlanas, cargar_perfiles, cargar_tablas
from hlf_priorizacion.ingesta.conciliacion import conciliar
from hlf_priorizacion.ingesta.normalizacion import (
    especialidad_desde_detalle,
    id_medicion,
    normalizar_perfil,
    normalizar_valor,
)


def test_id_medicion_determinista_y_valor_normalizado() -> None:
    a = id_medicion("PAC-HLF-00002", date(2026, 7, 8), "presion_sistolica", Decimal("167"))
    b = id_medicion("PAC-HLF-00002", date(2026, 7, 8), "presion_sistolica", Decimal("167.00"))
    assert a == b == "MED-372ba075aa3128b4"
    assert normalizar_valor(Decimal("7.40")) == "7.4"
    assert normalizar_valor(Decimal("160")) == "160"
    assert normalizar_valor(Decimal("-0.0")) == "0"


def test_especialidad_desde_detalle() -> None:
    assert especialidad_desde_detalle("triage ESI 2 (Cardiología)") == "Cardiología"
    assert especialidad_desde_detalle("ingreso hospitalario") is None


def test_normalizar_perfil_especialidad_inferida_duplicados_y_orden() -> None:
    raw = perfil_base(
        eventos_clinicos=[
            evento("EV-000002", "2026-03-01", "control_aps", "control", "leve"),
            {
                **evento("EV-000001", "2026-02-01", "visita_urgencia", "triage ESI 2", "grave"),
                "detalle": "sin plantilla",
            },
        ],
        mediciones=[
            medicion("2026-02-01", "presion_sistolica", 150, "mmHg", True),
            medicion("2026-02-01", "presion_sistolica", 150.0, "mmHg", True),
        ],
        citaciones=[
            cita("CT-000002", "2026-04-01", "asistio", minutos=20),
            cita("CT-000001", "2026-03-01", "no_asistio"),
        ],
    )
    res = normalizar_perfil(valido(raw))
    p = res.perfil
    assert [e.id_evento for e in p.eventos] == ["EV-000001", "EV-000002"]
    assert p.eventos[0].especialidad_inferida and p.eventos[0].especialidad_evento == "Cardiología"
    assert not p.eventos[1].especialidad_inferida
    assert len(p.mediciones) == 1
    assert [c.id_cita for c in p.citas] == ["CT-000001", "CT-000002"]
    codigos = {h.codigo: h for h in res.hallazgos}
    assert codigos["medicion_duplicada"].nivel == "info"
    assert codigos["citas_no_cronologicas"].ids_registro == ["CT-000001"]


def test_cargar_perfiles_errores(tmp_path: Path) -> None:
    with pytest.raises(ErrorCarga, match="no existe"):
        cargar_perfiles(tmp_path)
    (tmp_path / "perfiles.json").write_text("{no json", encoding="utf-8")
    with pytest.raises(ErrorCarga, match="no es JSON"):
        cargar_perfiles(tmp_path)
    (tmp_path / "perfiles.json").write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(ErrorCarga, match="lista"):
        cargar_perfiles(tmp_path)
    (tmp_path / "perfiles.json").write_text(json.dumps([perfil_base()]), encoding="utf-8")
    assert len(cargar_perfiles(tmp_path)) == 1


def test_cargar_tablas_informa_faltantes(tmp_path: Path) -> None:
    (tmp_path / "pacientes.csv").write_text("id_paciente,edad\nPAC-TST-00001,60\n", encoding="utf-8")
    tablas = cargar_tablas(tmp_path)
    assert tablas.filas["pacientes"] == [{"id_paciente": "PAC-TST-00001", "edad": "60"}]
    assert "mediciones" in tablas.faltantes


def _tablas_de(raw: dict[str, object], extra_medicion: bool = False) -> TablasPlanas:
    perfil = valido(raw)  # type: ignore[arg-type]
    pid = perfil.id_paciente
    s = perfil.lista_espera[0]
    p = perfil.paciente
    mediciones = [
        {
            "id_paciente": pid,
            "fecha_medicion": m.fecha_medicion.isoformat(),
            "tipo_medicion": m.tipo_medicion,
            "valor": str(m.valor),
            "unidad": m.unidad,
            "fuera_de_rango": str(m.fuera_de_rango).lower(),
        }
        for m in perfil.mediciones
    ]
    if extra_medicion:
        mediciones.append(
            {
                "id_paciente": pid,
                "fecha_medicion": "2026-05-05",
                "tipo_medicion": "glicemia",
                "valor": "100",
                "unidad": "mg/dL",
                "fuera_de_rango": "false",
            }
        )
    return TablasPlanas(
        filas={
            "pacientes": [
                {"id_paciente": pid, "edad": str(p.edad), "sexo": p.sexo, "fallecido": "false", "fecha_defuncion": ""}
            ],
            "lista_espera": [
                {
                    "id_paciente": pid,
                    "id_solicitud": s.id_solicitud,
                    "especialidad": s.especialidad,
                    "diagnostico_cie10": s.diagnostico_cie10,
                    "prioridad_inicial": s.prioridad_inicial,
                    "fecha_ingreso_lista": s.fecha_ingreso_lista.isoformat(),
                    "estado": s.estado,
                }
            ],
            "mediciones": mediciones,
        }
    )


def test_conciliacion_sin_y_con_diferencias() -> None:
    raw = perfil_base(mediciones=[medicion("2026-02-01", "presion_sistolica", 150, "mmHg", True)])
    perfil = valido(raw)
    assert conciliar([perfil], _tablas_de(raw)).hallazgos == {}
    informe = conciliar([perfil], _tablas_de(raw, extra_medicion=True))
    h = informe.hallazgos["PAC-TST-00001"][0]
    assert h.nivel == "verificar" and h.codigo == "conciliacion_diferencias"
    assert "mediciones (perfil 1, tabla 2)" in h.detalle
    assert "IC-TST-00001" in h.ids_registro
