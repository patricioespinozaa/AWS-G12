"""Constructores de perfiles sintéticos para las pruebas de ejemplo (no usan el dataset real)."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

from hlf_priorizacion.contrato.esquema import PerfilValido
from hlf_priorizacion.contrato.validacion import validar_perfil
from hlf_priorizacion.ingesta.normalizacion import PerfilNormalizado, normalizar_perfil

FECHA_EXTRACCION = date(2026, 10, 13)


def perfil_base(**cambios: Any) -> dict[str, Any]:
    """Perfil sintético válido con una solicitud de Cardiología, prioridad baja."""
    perfil: dict[str, Any] = {
        "id_paciente": "PAC-TST-00001",
        "paciente": {
            "nombre_fantasia": "Paciente Prueba 001",
            "edad": 60,
            "sexo": "M",
            "comuna": "Comuna A",
            "prevision": "FONASA B",
            "nivel_socioeconomico": "medio",
            "fallecido": False,
            "fecha_defuncion": None,
        },
        "lista_espera": {
            "id_solicitud": "IC-TST-00001",
            "especialidad": "Cardiología",
            "sub_especialidad": "Cardiología adulto",
            "diagnostico_cie10": "I20",
            "diagnostico_texto": "Angina de pecho",
            "prioridad_inicial": "baja",
            "fecha_ingreso_lista": "2026-01-01",
            "origen_derivacion": "CESFAM/APS",
            "estado": "en_espera",
        },
        "eventos_clinicos": [],
        "mediciones": [],
        "citaciones": [],
    }
    perfil = copy.deepcopy(perfil)
    perfil.update(cambios)
    return perfil


def evento(
    id_evento: str, fecha: str, tipo: str, subtipo: str, severidad: str, esp: str = "Cardiología"
) -> dict[str, Any]:
    return {
        "id_evento": id_evento,
        "fecha_evento": fecha,
        "tipo_evento": tipo,
        "subtipo": subtipo,
        "severidad": severidad,
        "detalle": f"{subtipo} ({esp})",
    }


def medicion(fecha: str, tipo: str, valor: float | int, unidad: str, fuera: bool = False) -> dict[str, Any]:
    return {"fecha_medicion": fecha, "tipo_medicion": tipo, "valor": valor, "unidad": unidad, "fuera_de_rango": fuera}


def cita(id_cita: str, fecha: str, estado: str, esp: str = "Cardiología", minutos: int | str = "") -> dict[str, Any]:
    return {
        "id_cita": id_cita,
        "id_box": "BOX-01",
        "fecha_cita": fecha,
        "especialidad": esp,
        "estado_cita": estado,
        "minutos_atencion_real": minutos,
    }


def valido(raw: dict[str, Any]) -> PerfilValido:
    res = validar_perfil(raw)
    assert res.ok and res.perfil is not None, res.motivos
    return res.perfil


def normalizado(raw: dict[str, Any]) -> PerfilNormalizado:
    return normalizar_perfil(valido(raw)).perfil
