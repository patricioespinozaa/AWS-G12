"""Los 6 casos de docs/casos-ejemplo.md (tabla "Verificación en seco" de business-logic-model.md).

Leen el dataset sintético real en ``data/dataset_hlf_ambulatorio/`` (ignorado por git). Si no está,
las pruebas se saltan con un mensaje claro en lugar de fallar.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from hlf_priorizacion.calidad.auditoria import auditar
from hlf_priorizacion.contrato.validacion import validar_perfil
from hlf_priorizacion.ingesta.carga import cargar_perfiles
from hlf_priorizacion.ingesta.normalizacion import normalizar_perfil
from hlf_priorizacion.modelos import ORDEN_NIVEL, Evaluacion
from hlf_priorizacion.motor.evaluar import evaluar
from hlf_priorizacion.motor.parametros import cargar_parametros
from hlf_priorizacion.repositorio.contexto import Repositorio

RAIZ = Path(__file__).resolve().parents[2]
DATOS = Path(os.environ.get("HLF_DATOS", RAIZ / "data" / "dataset_hlf_ambulatorio"))
FIXTURE = RAIZ / "tests" / "fixtures" / "evaluacion_ejemplo.json"
PARAMS = cargar_parametros()


@pytest.fixture(scope="module")
def repo() -> Repositorio:
    if not (DATOS / "perfiles.json").is_file():
        pytest.skip(
            f"Dataset real no disponible en {DATOS} (está en .gitignore). "
            "Copie el dataset del HLF ahí o defina HLF_DATOS para correr los casos de referencia."
        )
    perfiles = []
    for raw in cargar_perfiles(DATOS):
        res = validar_perfil(raw)
        assert res.ok and res.perfil is not None, (res.id_paciente, res.motivos)
        perfiles.append(normalizar_perfil(res.perfil).perfil)
    return Repositorio(perfiles)


def _ev(repo: Repositorio, id_solicitud: str, corte: str) -> Evaluacion:
    ctx = repo.contexto_a_fecha(id_solicitud, date.fromisoformat(corte))
    return evaluar(ctx, auditar(ctx), PARAMS)


def _al_menos(ev: Evaluacion, nivel: str) -> bool:
    return ev.nivel_propuesto is not None and ORDEN_NIVEL[ev.nivel_propuesto] >= ORDEN_NIVEL[nivel]


def test_00002_antes_de_la_urgencia_baja_o_media(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00002", "2026-07-19")
    assert ev.nivel_propuesto in {"baja", "media"}
    assert ev.banderas == []
    assert ev.puntaje == pytest.approx(37.8, abs=1.0)


def test_00002_dia_de_la_urgencia_critica_por_bandera(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00002", "2026-07-20")
    assert ev.nivel_propuesto == "critica"
    assert ev.nivel_calculado == "media"  # hallazgo del diseño: sube solo por la bandera
    assert [(b.codigo, b.ids_registro) for b in ev.banderas] == [("BR_EVENTO_GRAVE_30D", ["EV-000004"])]
    assert ev.tipo_resultado == "priorizacion"


def test_00002_en_la_extraccion_alta_sin_bandera(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00002", "2026-10-13")
    assert _al_menos(ev, "alta")
    assert ev.nivel_calculado == "alta" and ev.banderas == []
    assert ev.puntaje == pytest.approx(66.6, abs=1.0)


def test_00002_fixture_seccion_6_8_coincide_con_el_motor(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00002", "2026-08-10")
    assert ev == Evaluacion.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def test_00001_se_mantiene_alta_y_explica_la_tendencia_del_phq9(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00001", "2026-10-13")
    assert _al_menos(ev, "alta")
    assert any(f.factor == "medicion_tendencia" and "PHQ9" in f.detalle for f in ev.factores)
    assert [p.codigo for p in ev.pisos] == ["PISO_PHQ9"]
    assert ev.puntaje == pytest.approx(94.8, abs=1.0)


def test_00028_puede_bajar_como_maximo_un_nivel_y_explica_la_mejora(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00028", "2026-10-13")
    assert ev.nivel_propuesto is not None
    assert ORDEN_NIVEL[ev.nivel_propuesto] >= ORDEN_NIVEL[ev.prioridad_inicial] - 1
    mejoras = [f for f in ev.factores if f.factor == "evento" and f.aporte < 0]
    assert {f.detalle.split(",")[0] for f in mejoras} == {
        "control_aps: buena respuesta",
        "cambio_farmaco: reducción dosis",
    }
    assert ev.contradicciones == []
    assert ev.puntaje is not None and ev.puntaje < 20.0
    assert ev.puntaje == pytest.approx(13.8, abs=1.0)


def test_00020_citas_no_cambian_el_puntaje_y_alerta_citas_fallidas(repo: Repositorio) -> None:
    ctx = repo.contexto_a_fecha("IC-HLF-00020", date(2026, 10, 13))
    con = evaluar(ctx, auditar(ctx), PARAMS)
    sin_ctx = ctx.model_copy(update={"citas": []})
    sin = evaluar(sin_ctx, auditar(sin_ctx), PARAMS)
    assert con.puntaje == sin.puntaje == 50.0
    assert con.nivel_propuesto == sin.nivel_propuesto == "media"
    alerta = next(a for a in con.alertas_gestion if a.codigo == "citas_fallidas")
    assert len(alerta.ids_registro) == 3
    assert all(a.codigo != "citas_fallidas" for a in sin.alertas_gestion)


def test_00032_atendido_en_la_extraccion_se_excluye(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00032", "2026-10-13")
    assert ev.tipo_resultado == "exclusion" and ev.codigo_exclusion == "EX_ATENDIDO"


def test_00032_antes_de_ser_atendido_no_se_dispara(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00032", "2026-06-29")
    assert ev.nivel_propuesto == "baja"
    assert ev.tipo_resultado != "priorizacion"
    assert ev.banderas == [] and ev.pisos == []


def test_00032_egreso_inferido_despues_de_la_cita(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00032", "2026-07-15")
    assert ev.codigo_exclusion == "EX_ATENDIDO_INFERIDO"
    assert ev.marcas_inferido[0].valor == "2026-06-30"


def test_00009_antes_del_fallecimiento_se_evalua_critica(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00009", "2026-09-07")
    assert ev.tipo_resultado == "priorizacion"
    assert ev.nivel_propuesto == "critica"
    assert ev.puntaje == pytest.approx(80.0, abs=1.5)


def test_00009_desde_el_fallecimiento_se_excluye(repo: Repositorio) -> None:
    ev = _ev(repo, "IC-HLF-00009", "2026-09-08")
    assert ev.tipo_resultado == "exclusion" and ev.codigo_exclusion == "EX_FALLECIDO"
