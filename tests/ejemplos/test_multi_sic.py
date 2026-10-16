"""reglas-v0.2.0: escenario sintético de varias SIC del mismo paciente (R5.3 modificada y R11).

Usa ``data/synthetic/escenario-multi-sic/`` (versionado, ficticio): PAC-SIN-00001 con IC-SIN-00001
(Cardiología adulto, I20, baja) y, en ``perfiles.json``, además IC-SIN-00002 (Insuficiencia cardíaca, I50,
media, ingreso 2026-08-01). ``perfiles-una-sic.json`` es el "antes", solo con IC-SIN-00001.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ayudantes import cita, normalizado
from hlf_priorizacion.calidad.auditoria import auditar
from hlf_priorizacion.lote import Configuracion, ejecutar_lote
from hlf_priorizacion.modelos import Evaluacion
from hlf_priorizacion.motor.evaluar import MOTIVO_RELACIONES_NO_VALIDADAS, evaluar
from hlf_priorizacion.motor.parametros import ParametrosReglas, cargar_parametros, ruta_version
from hlf_priorizacion.persistencia.salidas import leer_propuestas
from hlf_priorizacion.repositorio.contexto import contexto_a_fecha

RAIZ = Path(__file__).resolve().parents[2]
ESCENARIO = RAIZ / "data" / "synthetic" / "escenario-multi-sic"
CORTE = date(2026, 8, 10)
V2 = cargar_parametros()
V1 = cargar_parametros(ruta_version("reglas-v0.1.0"))


def _perfil(archivo: str) -> dict[str, Any]:
    datos: list[dict[str, Any]] = json.loads((ESCENARIO / archivo).read_text(encoding="utf-8"))
    return datos[0]


def _evaluar(raw: dict[str, Any], id_solicitud: str, params: ParametrosReglas = V2, corte: date = CORTE) -> Evaluacion:
    ctx = contexto_a_fecha(normalizado(raw), id_solicitud, corte)
    return evaluar(ctx, auditar(ctx), params)


def _otras(ev: Evaluacion) -> list[tuple[float, list[str]]]:
    return [(f.aporte, f.ids_registro) for f in ev.factores if f.factor == "otra_solicitud"]


def test_la_version_por_defecto_es_v020_con_documento_sintetico() -> None:
    assert V2.version == "reglas-v0.2.0" and V1.version == "reglas-v0.1.0"
    assert V2.documento_relaciones is not None and V2.documento_relaciones.version == "relaciones-clinicas-v0.1.0"
    assert not V2.documento_relaciones.validado
    assert V1.documento_relaciones is None and V1.otras_solicitudes is None


def test_una_sic_no_tiene_factor_otra_solicitud() -> None:
    ev = _evaluar(_perfil("perfiles-una-sic.json"), "IC-SIN-00001")
    assert _otras(ev) == []


def test_dos_sic_se_aportan_en_ambos_sentidos() -> None:
    raw = _perfil("perfiles.json")
    i20 = _evaluar(raw, "IC-SIN-00001")
    i50 = _evaluar(raw, "IC-SIN-00002")
    assert _otras(i20) == [(4.5, ["IC-SIN-00002"])]  # 5 (media) x 0,9
    assert _otras(i50) == [(2.7, ["IC-SIN-00001"])]  # 3 (baja) x 0,9
    (f,) = [f for f in i20.factores if f.factor == "otra_solicitud"]
    assert "I50 (Insuficiencia cardíaca, prioridad inicial media)" in f.detalle
    assert "relaciones-clinicas-v0.1.0" in f.detalle
    antes = _evaluar(_perfil("perfiles-una-sic.json"), "IC-SIN-00001")
    assert antes.puntaje is not None and i20.puntaje is not None
    assert i20.puntaje == pytest.approx(min(100.0, antes.puntaje + 4.5), abs=0.011)


def test_evento_de_endocrinologia_usa_el_factor_del_documento() -> None:
    raw = _perfil("perfiles.json")
    ev = _evaluar(raw, "IC-SIN-00001")
    (f,) = [f for f in ev.factores if f.ids_registro == ["EV-900002"]]
    assert "Endocrinología → Cardiología 0.7" in f.detalle
    v1 = _evaluar(_perfil("perfiles-una-sic.json"), "IC-SIN-00001", V1)
    (g,) = [g for g in v1.factores if g.ids_registro == ["EV-900002"]]
    assert f.aporte == pytest.approx(g.aporte * 0.7 / 0.5, abs=0.011)  # v0.1.0 usaba 0,5


def test_confianza_no_alta_por_relaciones_no_validadas() -> None:
    raw = _perfil("perfiles.json")
    for id_solicitud in ("IC-SIN-00001", "IC-SIN-00002"):
        ev = _evaluar(raw, id_solicitud)
        assert ev.confianza != "alta"
        assert MOTIVO_RELACIONES_NO_VALIDADAS in ev.motivo_confianza


def test_v010_ignora_las_otras_solicitudes() -> None:
    raw = _perfil("perfiles.json")
    ev = _evaluar(raw, "IC-SIN-00001", V1)
    assert _otras(ev) == [] and ev.version_reglas == "reglas-v0.1.0"
    assert MOTIVO_RELACIONES_NO_VALIDADAS not in ev.motivo_confianza


def _duplicada() -> dict[str, Any]:
    raw = copy.deepcopy(_perfil("perfiles.json"))
    raw["lista_espera"][1].update({"diagnostico_cie10": "I20", "diagnostico_texto": "Angina de pecho"})
    return raw  # misma especialidad y CIE-10, otra subespecialidad


def test_duplicada_no_aporta_y_alerta_en_la_mas_reciente() -> None:
    raw = _duplicada()
    vieja = _evaluar(raw, "IC-SIN-00001")
    nueva = _evaluar(raw, "IC-SIN-00002")
    assert _otras(vieja) == [] and _otras(nueva) == []
    assert [a.codigo for a in vieja.alertas_gestion if a.codigo == "sic_duplicada"] == []
    (alerta,) = [a for a in nueva.alertas_gestion if a.codigo == "sic_duplicada"]
    assert alerta.ids_registro == ["IC-SIN-00001"]
    assert alerta.accion_sugerida.startswith("Verificar duplicidad administrativa")


def test_otra_sic_atendida_al_corte_no_aporta() -> None:
    raw = copy.deepcopy(_perfil("perfiles.json"))
    raw["lista_espera"][1]["estado"] = "atendido"
    raw["citaciones"] = [cita("CT-900001", "2026-08-08", "asistio", minutos=30)]
    ev = _evaluar(raw, "IC-SIN-00001")  # IC-SIN-00002 tiene egreso inferido el 2026-08-08 (R3.3)
    assert _otras(ev) == []


def test_otra_sic_con_ingreso_posterior_al_corte_no_aporta() -> None:
    raw = _perfil("perfiles.json")
    ctx = contexto_a_fecha(normalizado(raw), "IC-SIN-00001", date(2026, 7, 31))
    assert ctx.otras_solicitudes == []  # el repositorio no la entrega (sin fuga de información futura)
    assert _otras(evaluar(ctx, auditar(ctx), V2)) == []


def test_tope_de_10_recorta_el_ultimo_aporte() -> None:
    raw = copy.deepcopy(_perfil("perfiles.json"))
    raw["lista_espera"][1]["prioridad_inicial"] = "alta"  # I50: 8 x 0,9 = 7,2
    tercera = copy.deepcopy(raw["lista_espera"][1])
    tercera.update(
        {
            "id_solicitud": "IC-SIN-00003",
            "sub_especialidad": "Hipertensión",
            "diagnostico_cie10": "I10",
            "diagnostico_texto": "Hipertensión esencial",
            "fecha_ingreso_lista": "2026-08-05",
        }
    )
    raw["lista_espera"].append(tercera)  # I10: 8 x 0,7 = 5,6 -> recortado a 2,8
    ev = _evaluar(raw, "IC-SIN-00001")
    assert _otras(ev) == [(7.2, ["IC-SIN-00002"]), (2.8, ["IC-SIN-00003"])]
    assert "acotado por el tope de 10" in ev.factores[-1].detalle


def _lote(tmp_path: Path, archivo: str) -> dict[str, Evaluacion]:
    datos = tmp_path / "datos"
    datos.mkdir(parents=True)
    (datos / "perfiles.json").write_text((ESCENARIO / archivo).read_text(encoding="utf-8"), encoding="utf-8")
    salidas = tmp_path / "salidas"
    r = ejecutar_lote(Configuracion(CORTE, date(2026, 10, 13), datos, salidas, None), V2, "lote-prueba-multi")
    assert r.cobertura_completa
    return {ev.id_solicitud: ev for ev in leer_propuestas(salidas, CORTE, V2.version)}


def test_lote_con_dos_sic_cubre_ambas_y_es_idempotente(tmp_path: Path) -> None:
    antes = _lote(tmp_path / "una", "perfiles-una-sic.json")
    despues = _lote(tmp_path / "dos", "perfiles.json")
    assert set(antes) == {"IC-SIN-00001"} and set(despues) == {"IC-SIN-00001", "IC-SIN-00002"}
    a, d = antes["IC-SIN-00001"].puntaje, despues["IC-SIN-00001"].puntaje
    assert a is not None and d is not None and d == pytest.approx(min(100.0, a + 4.5), abs=0.011)
    datos, salidas = tmp_path / "dos" / "datos", tmp_path / "dos" / "salidas"
    r = ejecutar_lote(Configuracion(CORTE, date(2026, 10, 13), datos, salidas, None), V2, "lote-prueba-multi-2")
    assert r.resumen["propuestas"] == {"nuevas": 0, "ya_existentes": 2, "conflictos": 0}
    assert r.resumen["cobertura"]["universo"] == 2
