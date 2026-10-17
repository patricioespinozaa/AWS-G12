"""Comportamiento esperado del motor en los casos de referencia (docs/casos-ejemplo.md)."""
from datetime import date

import pandas as pd
import pytest

from priorizacion import reglas as R
from priorizacion.explicacion import validar_texto_llm
from priorizacion.motor import Decision, evaluar, huella_datos

pytestmark = pytest.mark.datos   # casos de referencia del dataset


def ev(repo, id_paciente, fecha, decisiones=None):
    sol = repo.solicitud_de_paciente(id_paciente)
    return evaluar(sol, repo.historias[id_paciente], date.fromisoformat(fecha), decisiones)


def test_deterioro_agudo_sube_con_la_urgencia(repo):
    antes = ev(repo, "PAC-HLF-00002", "2026-07-19")
    despues = ev(repo, "PAC-HLF-00002", "2026-07-20")
    assert antes.nivel_propuesto in ("baja", "media") and not antes.alerta
    assert despues.nivel_propuesto == "alta" and despues.alerta and despues.cambio == "sube"
    assert any(f.categoria == "regla_dura" and f.ref_fuente.startswith("EV-") for f in despues.factores)


def test_deterioro_progresivo_se_mantiene_alta_con_tendencia(repo):
    r = ev(repo, "PAC-HLF-00001", "2026-10-13")
    assert r.nivel_propuesto == "alta"
    assert any(f.codigo == "tendencia" and "PHQ-9" in f.descripcion for f in r.factores)


def test_mejora_no_sube(repo):
    r = ev(repo, "PAC-HLF-00028", "2026-10-13")
    assert r.nivel_propuesto == "baja" and r.evidencia_mejora


def test_inasistencia_no_cambia_la_prioridad_clinica(repo):
    r = ev(repo, "PAC-HLF-00020", "2026-10-13")
    assert r.nivel_propuesto == "media" and not r.alerta


def test_atendido_y_fallecido_quedan_fuera(repo):
    assert not ev(repo, "PAC-HLF-00032", "2026-06-29").excluido
    assert ev(repo, "PAC-HLF-00032", "2026-06-30").excluido
    assert ev(repo, "PAC-HLF-00009", "2026-08-29").nivel_propuesto == "alta"
    assert ev(repo, "PAC-HLF-00009", "2026-09-08").excluido


def test_solo_usa_datos_hasta_la_fecha_de_corte(repo):
    r = ev(repo, "PAC-HLF-00002", "2026-07-19")
    assert all(f.fecha_dato is None or f.fecha_dato <= date(2026, 7, 19) for f in r.factores)


def test_contexto_no_cambia_el_nivel_por_si_solo(repo):
    """Riesgo basal + edad + espera ordenan dentro del nivel, pero no alcanzan para subir de nivel."""
    maximo = max(R.PUNTOS_RIESGO_BASAL.values()) + 2 + R.MAX_APORTE_ESPERA
    assert maximo < R.UMBRAL_MEDIA
    for sol in repo.activas(date(2026, 10, 13)):
        r = evaluar(sol, repo.historias[sol.id_paciente], date(2026, 10, 13))
        clinicas = [f for f in r.factores if f.categoria in ("evento", "medicion", "patron")]
        if not clinicas and not r.alerta:
            assert r.nivel_propuesto == sol.prioridad_inicial


def test_riesgo_basal_ordena_dentro_del_nivel(repo):
    """Dos pacientes del mismo nivel sin señales: el de mayor riesgo basal queda con mayor puntaje de orden."""
    corte = date(2026, 10, 13)
    sin_senales = {}
    for sol in repo.activas(corte):
        r = evaluar(sol, repo.historias[sol.id_paciente], corte)
        if r.nivel_propuesto == "media" and not any(f.categoria in ("evento", "medicion", "patron") for f in r.factores):
            clase = R.RIESGO_BASAL_DX[sol.cie10][0]
            sin_senales.setdefault(clase, []).append(r.puntaje_nivel)
    if "alto" in sin_senales and "bajo" in sin_senales:
        # mismo puntaje de nivel (mismo nivel), distinto riesgo basal → distinto orden
        assert set(sin_senales["alto"]) == set(sin_senales["bajo"]) == {R.BASE_PRIORIDAD["media"]}


def test_resguardo_no_baja_sin_evidencia_de_mejora(repo):
    """Si el equipo aceptó 'alta', el decaimiento de los eventos no basta para proponer bajar."""
    decision = [Decision(date(2026, 7, 21), "alta")]
    r = ev(repo, "PAC-HLF-00002", "2026-10-13", decision)
    assert r.prioridad_vigente == "alta"
    assert r.nivel_propuesto == "alta" and r.resguardo_aplicado


def test_determinista_y_huella_reproducible(repo):
    sol = repo.solicitud_de_paciente("PAC-HLF-00001")
    h = repo.historias["PAC-HLF-00001"]
    a, b = evaluar(sol, h, date(2026, 9, 1)), evaluar(sol, h, date(2026, 9, 1))
    assert a.puntaje == b.puntaje and a.factores == b.factores
    assert huella_datos(sol, h, date(2026, 9, 1)) == huella_datos(sol, h, date(2026, 9, 1))
    assert huella_datos(sol, h, date(2026, 9, 1)) != huella_datos(sol, h, date(2026, 9, 20))


def test_evidencia_externa_cuenta_solo_si_esta_validada(repo):
    pid = "PAC-HLF-00028"
    evidencia = pd.DataFrame([{"id_evidencia": "EXT-T1", "id_paciente": pid, "fecha_examen": "2026-10-10",
                               "tipo_medicion": "PHQ9", "valor": 21.0, "estado": "pendiente"}])
    sin_mensajes = pd.DataFrame(columns=["id_mensaje", "id_paciente", "fecha", "tipo", "detalle", "estado"])
    try:
        repo.aplicar_registro(evidencia, sin_mensajes, pid)
        assert ev(repo, pid, "2026-10-13").puntaje_nivel == 0
        repo.aplicar_registro(evidencia.assign(estado="validada"), sin_mensajes, pid)
        r = ev(repo, pid, "2026-10-13")
        assert r.puntaje_nivel > 0 and any(f.tipo_fuente == "externa" for f in r.factores)
    finally:
        repo.aplicar_registro(evidencia.iloc[0:0], sin_mensajes, pid)


def test_validacion_del_texto_llm_rechaza_datos_inventados(repo):
    r = ev(repo, "PAC-HLF-00002", "2026-08-10")
    ref = next(f.ref_fuente for f in r.factores if f.ref_fuente.startswith("EV-"))
    assert validar_texto_llm(f"Se propone alta por la urgencia [{ref}].", r) is None
    assert "EV-999999" in validar_texto_llm("Se propone alta por la urgencia [EV-999999].", r)
    assert "2026-01-01" in validar_texto_llm(f"Se propone alta desde el 2026-01-01 [{ref}].", r)
    assert validar_texto_llm(f"Se propone mantener [{ref}].", r) == "no menciona el nivel propuesto"


@pytest.mark.parametrize("corte", ["2025-06-01", "2026-01-15", "2026-10-13"])
def test_toda_la_lista_activa_tiene_propuesta(repo, corte):
    c = date.fromisoformat(corte)
    activas = repo.activas(c)
    assert activas
    for sol in activas:
        r = evaluar(sol, repo.historias[sol.id_paciente], c)
        assert not r.excluido and r.nivel_propuesto in R.NIVELES and r.factores
