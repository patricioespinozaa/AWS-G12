"""Contrato y cuarentena (R1, sección 4.2): un perfil válido y cada motivo de cuarentena."""

from __future__ import annotations

from typing import Any

import pytest

from ayudantes import cita, evento, medicion, perfil_base
from hlf_priorizacion.contrato.esquema import normalizar_cie10
from hlf_priorizacion.contrato.esquema_json import RUTA_ESQUEMA, texto_esquema
from hlf_priorizacion.contrato.validacion import validar_perfil


def test_perfil_valido_descarta_nombre_y_normaliza_lista() -> None:
    raw = perfil_base(
        eventos_clinicos=[evento("EV-000001", "2026-02-01", "visita_urgencia", "triage ESI 2", "grave")],
        mediciones=[medicion("2026-02-01", "presion_sistolica", 150, "mmHg", True)],
        citaciones=[cita("CT-000001", "2026-03-01", "no_asistio")],
    )
    res = validar_perfil(raw)
    assert res.ok, res.motivos
    assert res.perfil is not None
    assert len(res.perfil.lista_espera) == 1
    assert "nombre_fantasia" not in res.perfil.paciente.model_dump()
    assert res.perfil.citaciones[0].minutos_atencion_real is None
    assert res.version_contrato == "contrato-v1.0.0"


def test_lista_espera_como_lista_tambien_se_acepta() -> None:
    raw = perfil_base()
    raw["lista_espera"] = [raw["lista_espera"]]
    assert validar_perfil(raw).ok


def test_cie10_se_normaliza() -> None:
    raw = perfil_base()
    raw["lista_espera"]["diagnostico_cie10"] = " i20 "
    res = validar_perfil(raw)
    assert res.ok and res.perfil is not None
    assert res.perfil.lista_espera[0].diagnostico_cie10 == "I20"
    assert normalizar_cie10("e11.3") == "E11.3"


def _con(ruta: list[Any], valor: Any) -> dict[str, Any]:
    raw = perfil_base(
        eventos_clinicos=[evento("EV-000001", "2026-02-01", "visita_urgencia", "triage ESI 2", "grave")],
        mediciones=[medicion("2026-02-01", "presion_sistolica", 150, "mmHg", True)],
        citaciones=[cita("CT-000001", "2026-03-01", "no_asistio")],
    )
    destino: Any = raw
    for clave in ruta[:-1]:
        destino = destino[clave]
    if valor is _BORRAR:
        del destino[ruta[-1]]
    else:
        destino[ruta[-1]] = valor
    return raw


_BORRAR = object()

CASOS_CUARENTENA = {
    "falta id_paciente": (["id_paciente"], _BORRAR, "id_paciente"),
    "id_paciente con formato inválido": (["id_paciente"], "12345", "id_paciente"),
    "fecha no ISO": (["eventos_clinicos", 0, "fecha_evento"], "01-02-2026", "fecha_evento"),
    "valor no numérico": (["mediciones", 0, "valor"], "alto", "valor"),
    "tipo_evento fuera de catálogo": (["eventos_clinicos", 0, "tipo_evento"], "teleconsulta", "tipo_evento"),
    "estado_cita fuera de catálogo": (["citaciones", 0, "estado_cita"], "perdida", "estado_cita"),
    "prioridad_inicial fuera de catálogo": (["lista_espera", "prioridad_inicial"], "urgente", "prioridad_inicial"),
    "unidad fuera de catálogo": (["mediciones", 0, "unidad"], "kPa", "unidad"),
    "combinación no catalogada": (["eventos_clinicos", 0, "subtipo"], "ingreso UCI", "combinación"),
    "severidad que no corresponde": (["eventos_clinicos", 0, "severidad"], "leve", "severidad"),
    "unidad incompatible con el tipo": (["mediciones", 0, "unidad"], "mg/dL", "unidad"),
    "fallecido sin fecha_defuncion": (["paciente", "fallecido"], True, "fecha_defuncion"),
    "solicitud sin especialidad": (["lista_espera", "especialidad"], "", "especialidad"),
    "solicitud sin CIE-10": (["lista_espera", "diagnostico_cie10"], "", "diagnostico_cie10"),
}


@pytest.mark.parametrize("caso", sorted(CASOS_CUARENTENA))
def test_motivos_de_cuarentena(caso: str) -> None:
    ruta, valor, fragmento = CASOS_CUARENTENA[caso]
    res = validar_perfil(_con(ruta, valor))
    assert not res.ok, caso
    assert res.perfil is None
    assert any(fragmento in m for m in res.motivos), res.motivos


def test_motivos_no_copian_valores_de_entrada() -> None:
    res = validar_perfil(_con(["mediciones", 0, "valor"], "VALOR-SECRETO"))
    assert not res.ok
    assert all("VALOR-SECRETO" not in m for m in res.motivos)


def test_cuarentena_recupera_ids_para_la_alerta() -> None:
    res = validar_perfil(_con(["mediciones", 0, "unidad"], "kPa"))
    assert res.id_paciente == "PAC-TST-00001"
    assert res.ids_solicitud == ["IC-TST-00001"]


def test_entrada_que_no_es_objeto() -> None:
    assert not validar_perfil(["no", "es", "objeto"]).ok


def test_esquema_json_exportado_esta_al_dia() -> None:
    assert RUTA_ESQUEMA.read_text(encoding="utf-8") == texto_esquema()
