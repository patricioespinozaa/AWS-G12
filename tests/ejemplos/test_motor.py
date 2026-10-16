"""Motor de reglas: ejemplos de la sección 16.1 y validación de parámetros (fail-closed)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ayudantes import FECHA_EXTRACCION, cita, evento, medicion, normalizado, perfil_base
from hlf_priorizacion.calidad.auditoria import auditar
from hlf_priorizacion.modelos import Evaluacion
from hlf_priorizacion.motor.evaluar import evaluar
from hlf_priorizacion.motor.parametros import ErrorParametros, cargar_parametros, ruta_version
from hlf_priorizacion.motor.referencia import puntaje_y_niveles
from hlf_priorizacion.repositorio.contexto import contexto_a_fecha

PARAMS = cargar_parametros()


def _evaluar(raw: dict[str, object], corte: date = FECHA_EXTRACCION) -> Evaluacion:
    ctx = contexto_a_fecha(normalizado(raw), "IC-TST-00001", corte, FECHA_EXTRACCION)
    return evaluar(ctx, auditar(ctx), PARAMS)


def test_sin_registros_conserva_prioridad_inicial() -> None:
    raw = perfil_base()
    raw["lista_espera"].update({"prioridad_inicial": "media", "fecha_ingreso_lista": "2026-09-01"})  # type: ignore[attr-defined]
    ev = _evaluar(raw)
    assert ev.puntaje == 40.0 and ev.nivel_propuesto == "media" and ev.tipo_resultado == "sin_alerta"
    assert [f.factor for f in ev.factores] == ["base", "espera"]


def test_contradiccion_reduccion_dosis_con_pas_85() -> None:
    raw = perfil_base(
        eventos_clinicos=[evento("EV-000001", "2026-10-01", "cambio_farmaco", "reducción dosis", "leve")],
        mediciones=[medicion("2026-10-05", "presion_sistolica", 85, "mmHg", True)],
    )
    raw["lista_espera"]["fecha_ingreso_lista"] = "2026-09-01"  # type: ignore[index]
    ev = _evaluar(raw)
    factor_evento = next(f for f in ev.factores if f.factor == "evento")
    assert factor_evento.aporte == 0.0
    assert "anulado" in factor_evento.detalle
    assert ev.contradicciones and ev.contradicciones[0].id_evento == "EV-000001"
    assert ev.contradicciones[0].pregunta_clinica.startswith("¿")


def test_mas_de_dos_inasistencias_alerta_sin_cambiar_puntaje() -> None:
    sin_citas = perfil_base()
    con_citas = perfil_base(
        citaciones=[
            cita("CT-000001", "2026-03-01", "no_asistio"),
            cita("CT-000002", "2026-04-01", "no_asistio"),
            cita("CT-000003", "2026-05-01", "no_asistio"),
        ]
    )
    a, b = _evaluar(sin_citas), _evaluar(con_citas)
    assert a.puntaje == b.puntaje and a.nivel_propuesto == b.nivel_propuesto
    codigos = {x.codigo for x in b.alertas_gestion}
    assert {"citas_fallidas", "limite_inasistencias"} <= codigos
    assert b.tipo_resultado == "gestion"


def test_fallecido_excluido_desde_su_fecha_de_defuncion() -> None:
    raw = perfil_base()
    raw["paciente"].update({"fallecido": True, "fecha_defuncion": "2026-09-08"})  # type: ignore[attr-defined]
    raw["lista_espera"]["estado"] = "fallecido"  # type: ignore[index]
    assert _evaluar(raw, date(2026, 9, 7)).tipo_resultado != "exclusion"
    ev = _evaluar(raw, date(2026, 9, 8))
    assert ev.tipo_resultado == "exclusion" and ev.codigo_exclusion == "EX_FALLECIDO"
    assert ev.puntaje is None and ev.estado_revision == "pendiente_revision_medica"


def test_fallecido_que_sigue_en_lista_genera_alerta() -> None:
    raw = perfil_base()
    raw["paciente"].update({"fallecido": True, "fecha_defuncion": "2026-09-08"})  # type: ignore[attr-defined]
    ev = _evaluar(raw)
    assert [a.codigo for a in ev.alertas_gestion] == ["fallecido_en_lista"]


def test_exclusion_inferida_con_marca_y_confianza_media() -> None:
    raw = perfil_base(citaciones=[cita("CT-000001", "2026-06-30", "asistio", minutos=30)])
    raw["lista_espera"]["estado"] = "atendido"  # type: ignore[index]
    ev = _evaluar(raw, date(2026, 7, 15))
    assert ev.codigo_exclusion == "EX_ATENDIDO_INFERIDO"
    assert ev.confianza == "media"
    assert ev.marcas_inferido[0].valor == "2026-06-30" and ev.marcas_inferido[0].ids_registro == ["CT-000001"]


def test_bajada_maximo_un_nivel_con_evidencia_de_mejoria() -> None:
    raw = perfil_base(
        eventos_clinicos=[
            evento("EV-000001", "2026-10-01", "control_aps", "buena respuesta", "leve", "Salud Mental"),
            evento("EV-000002", "2026-10-05", "cambio_farmaco", "reducción dosis", "leve", "Salud Mental"),
        ],
        mediciones=[medicion("2026-10-02", "PHQ9", 2, "puntos")],
    )
    raw["lista_espera"].update(
        {  # type: ignore[attr-defined]
            "especialidad": "Salud Mental",
            "prioridad_inicial": "media",
            "fecha_ingreso_lista": "2026-09-20",
        }
    )
    ev = _evaluar(raw)
    assert ev.nivel_calculado == "baja"
    assert ev.nivel_propuesto == "baja"
    assert ev.tipo_resultado == "priorizacion"
    # Sin la medición en rango no hay evidencia suficiente: no baja.
    raw["mediciones"] = []
    assert _evaluar(raw).nivel_propuesto == "media"


def test_piso_y_bandera() -> None:
    raw = perfil_base(mediciones=[medicion("2026-10-01", "escala_dolor_eva", 8, "puntos", True)])
    raw["lista_espera"]["fecha_ingreso_lista"] = "2026-09-01"  # type: ignore[index]
    ev = _evaluar(raw)
    assert [p.codigo for p in ev.pisos] == ["PISO_EVA"] and ev.nivel_propuesto == "alta"
    raw = perfil_base(mediciones=[medicion("2026-10-01", "saturacion_o2", 88, "%", True)])
    raw["lista_espera"]["fecha_ingreso_lista"] = "2026-09-01"  # type: ignore[index]
    ev = _evaluar(raw)
    assert [b.codigo for b in ev.banderas] == ["BR_SATO2_BAJA"] and ev.nivel_propuesto == "critica"


def test_medicion_antigua_no_dispara_bandera() -> None:
    raw = perfil_base(mediciones=[medicion("2026-03-01", "saturacion_o2", 88, "%", True)])
    assert _evaluar(raw).banderas == []


def test_tope_de_mediciones() -> None:
    raw = perfil_base(
        mediciones=[
            medicion("2026-03-01", "presion_sistolica", 120, "mmHg"),
            medicion("2026-10-01", "presion_sistolica", 179, "mmHg", True),
            medicion("2026-03-01", "glicemia", 100, "mg/dL"),
            medicion("2026-10-01", "glicemia", 390, "mg/dL", True),
        ]
    )
    ev = _evaluar(raw)
    total = sum(f.aporte for f in ev.factores if f.factor.startswith("medicion"))
    assert total == pytest.approx(20.0)
    assert any("acotado" in f.detalle for f in ev.factores)


def test_oraculo_en_un_ejemplo() -> None:
    raw = perfil_base(
        eventos_clinicos=[evento("EV-000001", "2026-08-01", "visita_urgencia", "triage ESI 2", "grave")],
        mediciones=[
            medicion("2026-02-01", "presion_sistolica", 120, "mmHg"),
            medicion("2026-09-01", "presion_sistolica", 150, "mmHg", True),
        ],
    )
    ctx = contexto_a_fecha(normalizado(raw), "IC-TST-00001", FECHA_EXTRACCION, FECHA_EXTRACCION)
    dq = auditar(ctx)
    ev = evaluar(ctx, dq, PARAMS)
    assert puntaje_y_niveles(ctx, dq, PARAMS) == (ev.puntaje, ev.nivel_calculado, ev.nivel_propuesto)


def test_parametros_invalidos_detienen(tmp_path: Path) -> None:
    texto = ruta_version("reglas-v0.1.0").read_text(encoding="utf-8")
    malo = tmp_path / "reglas-v0.1.0.yaml"
    malo.write_text(texto.replace("vida_media_dias: 90", "vida_media_dias: -1"), encoding="utf-8")
    with pytest.raises(ErrorParametros, match="vida_media_dias"):
        cargar_parametros(malo)
    malo.write_text(texto.replace("    - {tipo: control_aps, subtipo: control, peso: 0}\n", ""), encoding="utf-8")
    with pytest.raises(ErrorParametros, match="faltan pesos"):
        cargar_parametros(malo)
    otro = tmp_path / "reglas-v0.1.9.yaml"
    otro.write_text(texto, encoding="utf-8")
    with pytest.raises(ErrorParametros, match="declara la versión"):
        cargar_parametros(otro)
    with pytest.raises(ErrorParametros, match="no se pudo leer"):
        cargar_parametros(tmp_path / "no-existe.yaml")
    (tmp_path / "reglas-v0.2.0.yaml").write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ErrorParametros, match="mapa"):
        cargar_parametros(tmp_path / "reglas-v0.2.0.yaml")
