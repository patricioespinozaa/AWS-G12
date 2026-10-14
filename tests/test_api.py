"""Prueba de humo de la API: lectura y el flujo de escritura principal (canal → validación → reevaluación)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def cliente():
    from api.main import app   # corre la consolidación nocturna sobre la base temporal
    return TestClient(app)


def test_lecturas(cliente):
    assert cliente.get("/api/meta").json()["version_reglas"]
    b = cliente.get("/api/bandeja?corte=2026-10-13").json()
    assert len(b["filas"]) > 0
    ficha = cliente.get("/api/solicitudes/IC-HLF-00002?corte=2026-08-10").json()
    assert ficha["resultado"]["nivel_propuesto"] == "alta"
    serie = cliente.get("/api/solicitudes/IC-HLF-00002/serie").json()
    assert serie["cambios"][0]["fecha"] == "2026-07-20"
    for url in ["/api/solicitudes/IC-HLF-00009/clinico?corte=2026-10-13", "/api/agenda?fecha=2026-10-13&especialidad=Cardiología",
                "/api/box?corte=2026-10-13", "/api/kpis?corte=2026-10-13", "/api/nocturno", "/api/canal-pendientes"]:
        assert cliente.get(url).status_code == 200, url


def test_explicacion_sin_llm_usa_plantilla(cliente):
    r = cliente.post("/api/solicitudes/IC-HLF-00002/explicacion-ia?corte=2026-08-10").json()
    assert r["fuente"] == "plantilla"


def test_evidencia_validada_gatilla_reevaluacion(cliente):
    e = cliente.post("/api/canal/evidencias", json={
        "id_paciente": "PAC-HLF-00028", "fecha_examen": "2026-10-10", "tipo_medicion": "PHQ9", "valor": 21,
        "lugar": "Clínica privada", "fecha_recepcion": "2026-10-12"}).json()
    assert len(cliente.get("/api/canal-pendientes").json()["evidencias"]) == 1
    r = cliente.post(f"/api/canal/evidencias/{e['id_evidencia']}/revision",
                     json={"estado": "validada", "revisado_por": "test", "corte": "2026-10-13"}).json()
    assert r["despues"]["puntaje_nivel"] > r["antes"]["puntaje_nivel"]


def test_decision_requiere_motivo_y_queda_registrada(cliente):
    assert cliente.post("/api/solicitudes/IC-HLF-00002/decisiones",
                        json={"corte": "2026-07-21", "decision": "rechaza"}).status_code == 422
    r = cliente.post("/api/solicitudes/IC-HLF-00002/decisiones",
                     json={"corte": "2026-07-21", "decision": "acepta", "usuario": "test"})
    assert r.status_code == 200 and r.json()["prioridad_final"] == "alta"
    ficha = cliente.get("/api/solicitudes/IC-HLF-00002?corte=2026-10-13").json()
    assert ficha["resultado"]["prioridad_vigente"] == "alta"
    assert ficha["solicitud"]["prioridad_inicial"] == "baja"   # nunca se sobrescribe
