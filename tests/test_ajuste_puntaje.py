"""Ajuste del puntaje de orden por la Administradora (F0007).

El motor sigue calculando su puntaje; la decisión guarda la diferencia, que rige hasta la siguiente decisión que la
cambie. Ordena la cola dentro del nivel, pero no cambia el nivel propuesto ni el puntaje de nivel.
"""
from datetime import date

import pandas as pd
import pytest

from priorizacion.estimacion import estimar
from priorizacion.motor import Decision, ajuste_vigente, evaluar, huella_datos
from priorizacion.nocturno import calcular_posiciones


# -- puro ---------------------------------------------------------------------------------------------------
def test_ajuste_vigente_por_fecha():
    decs = [Decision(date(2026, 7, 1), "media", 5.0), Decision(date(2026, 8, 1), "alta"),       # mantiene +5
            Decision(date(2026, 9, 1), "alta", 0.0)]                                            # vuelve al motor
    assert ajuste_vigente(decs, date(2026, 6, 30)) == 0.0
    assert ajuste_vigente(decs, date(2026, 7, 15)) == 5.0
    assert ajuste_vigente(decs, date(2026, 8, 15)) == 5.0
    assert ajuste_vigente(decs, date(2026, 9, 1)) == 0.0


def _fila(id_sol, puntaje, ajuste=0.0, nivel="media", ingreso="2026-01-01"):
    return {"fecha": "2026-10-13", "id_solicitud": id_sol, "especialidad": "Cardiología", "puntaje": puntaje,
            "nivel_propuesto": nivel, "prioridad_inicial": "media", "alerta": 0, "fecha_ingreso": ingreso,
            "ajuste_puntaje": ajuste}


def test_el_ajuste_mueve_la_posicion_dentro_del_nivel():
    sin = calcular_posiciones(pd.DataFrame([_fila("A", 15), _fila("B", 12)])).set_index("id_solicitud")
    assert sin.loc["B", "posicion_dinamica"] == 2
    con = calcular_posiciones(pd.DataFrame([_fila("A", 15), _fila("B", 12, ajuste=5)])).set_index("id_solicitud")
    assert con.loc["B", "posicion_dinamica"] == 1                          # 12 + 5 = 17 > 15
    # pero no salta de nivel: un ajuste enorme en "media" no pasa a una "alta"
    otra = calcular_posiciones(pd.DataFrame([_fila("A", 21, nivel="alta"), _fila("B", 12, ajuste=50)]))
    assert otra.set_index("id_solicitud").loc["A", "posicion_dinamica"] == 1
    # sin la columna (series antiguas) se comporta como antes
    assert calcular_posiciones(pd.DataFrame([_fila("A", 15), _fila("B", 12)]).drop(columns="ajuste_puntaje")) \
        .set_index("id_solicitud").loc["B", "posicion_dinamica"] == 2


def test_la_estimacion_usa_el_puntaje_vigente_dentro_del_nivel():
    corte = date(2026, 10, 13)
    citas = pd.DataFrame([{"especialidad": "Cardiología", "estado_cita": "asistio",
                           "fecha_cita": pd.Timestamp(corte) - pd.Timedelta(days=d)} for d in range(0, 56, 2)])
    cola = pd.DataFrame([{"id_solicitud": "A", "especialidad": "Cardiología", "prioridad_vigente": "media",
                          "fecha_ingreso": "2026-01-01", "puntaje_vigente": 12.0},
                         {"id_solicitud": "B", "especialidad": "Cardiología", "prioridad_vigente": "media",
                          "fecha_ingreso": "2026-03-01", "puntaje_vigente": 18.0}])
    est = estimar(cola, citas, corte).set_index("id_solicitud")
    assert est.loc["B", "posicion_vigente"] == 1 and est.loc["A", "posicion_vigente"] == 2
    sin_puntaje = estimar(cola.drop(columns="puntaje_vigente"), citas, corte).set_index("id_solicitud")
    assert sin_puntaje.loc["A", "posicion_vigente"] == 1                   # sin puntaje: orden de llegada


# -- motor con el dataset --------------------------------------------------------------------------------------
@pytest.mark.datos
def test_el_ajuste_no_cambia_el_calculo_del_motor(repo):
    sol = repo.solicitud_de_paciente("PAC-HLF-00001")
    h = repo.historias["PAC-HLF-00001"]
    corte = date(2026, 10, 13)
    base = evaluar(sol, h, corte)
    decs = [Decision(date(2026, 9, 1), base.prioridad_vigente, 7.5)]
    r = evaluar(sol, h, corte, decs)
    assert (r.puntaje, r.puntaje_nivel, r.nivel_propuesto, r.factores) == \
        (base.puntaje, base.puntaje_nivel, base.nivel_propuesto, base.factores)      # el motor no se toca
    assert r.ajuste_puntaje == 7.5 and r.puntaje_vigente == round(base.puntaje + 7.5, 2)
    assert huella_datos(sol, h, corte, decs) != huella_datos(sol, h, corte, [Decision(date(2026, 9, 1), base.prioridad_vigente)])


# -- API ---------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cliente():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def _fila_bandeja(cliente, id_sol):
    b = cliente.get("/api/bandeja?corte=2026-10-13").json()["filas"]
    return next(f for f in b if f["id_solicitud"] == id_sol)


@pytest.mark.datos
def test_la_administradora_cambia_el_puntaje_y_la_cola_se_reordena(cliente):
    from api import estado as E
    b = cliente.get("/api/bandeja?corte=2026-10-13").json()["filas"]
    # el último de una cola de "media" con al menos otro "media" delante
    cola = [f for f in b if f["especialidad"] == b[0]["especialidad"] and f["nivel_propuesto"] == "media"]
    cola.sort(key=lambda f: f["posicion_dinamica"])
    assert len(cola) >= 2
    ultimo, primero = cola[-1], cola[0]
    nuevo = round(primero["puntaje_vigente"] + 1, 1)

    sin_motivo = {"corte": "2026-10-13", "decision": "ajusta", "puntaje": nuevo}
    assert cliente.post(f"/api/solicitudes/{ultimo['id_solicitud']}/decisiones", json=sin_motivo).status_code == 422
    fuera = {"corte": "2026-10-13", "decision": "ajusta", "puntaje": ultimo["puntaje"] + 150, "motivo": "x"}
    assert cliente.post(f"/api/solicitudes/{ultimo['id_solicitud']}/decisiones", json=fuera).status_code == 422

    r = cliente.post(f"/api/solicitudes/{ultimo['id_solicitud']}/decisiones",
                     json={**sin_motivo, "motivo": "Revisado con el especialista: adelantar dentro de su nivel"})
    assert r.status_code == 200, r.text
    assert r.json()["prioridad_final"] == ultimo["prioridad_vigente"]              # solo cambió el puntaje
    despues = _fila_bandeja(cliente, ultimo["id_solicitud"])
    assert despues["puntaje"] == ultimo["puntaje"]                                 # el motor no se toca
    assert despues["puntaje_vigente"] == nuevo and despues["ajuste_puntaje"] == round(nuevo - ultimo["puntaje"], 2)
    assert despues["posicion_dinamica"] < ultimo["posicion_dinamica"]              # subió en la cola
    assert despues["nivel_propuesto"] == ultimo["nivel_propuesto"]                 # el nivel no cambia

    ficha = cliente.get(f"/api/solicitudes/{ultimo['id_solicitud']}?corte=2026-10-13").json()
    assert ficha["resultado"]["puntaje_vigente"] == nuevo
    d = ficha["decisiones"][-1]
    assert d["puntaje_calculado"] == ultimo["puntaje"] and d["ajuste_puntaje"] == despues["ajuste_puntaje"]
    serie = E.registro.serie(ultimo["id_solicitud"]).set_index("fecha")
    assert serie.loc["2026-10-13", "ajuste_puntaje"] == despues["ajuste_puntaje"]  # queda en la simulación

    # Volver al puntaje del motor
    r = cliente.post(f"/api/solicitudes/{ultimo['id_solicitud']}/decisiones",
                     json={"corte": "2026-10-13", "decision": "ajusta", "puntaje": ultimo["puntaje"],
                           "motivo": "Se retira el ajuste"})
    assert r.status_code == 200 and r.json()["ajuste_puntaje"] == 0
    assert _fila_bandeja(cliente, ultimo["id_solicitud"])["puntaje_vigente"] == ultimo["puntaje"]
