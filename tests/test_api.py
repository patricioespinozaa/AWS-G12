import json

import pytest
from fastapi.testclient import TestClient

from conftest import PIDS_PRUEBA, leer_jsonl
from servidor.app import crear_app
from servidor.configuracion import ConfigServidor
from servidor.inferencia import ClienteSimulado

ANTES, REF = "2026-07-08", "2026-10-13"
CAMPOS_PROHIBIDOS = ("prevision", "nivel_socioeconomico", "comuna", "nombre_fantasia")


def _claves(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        acc |= set(obj)
        for v in obj.values():
            _claves(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _claves(v, acc)
    return acc


def _ids_citados(analisis: dict) -> set[str]:
    ids = {i for h in analisis["hallazgos"] for i in h["registro_ids"]}
    ids |= {e["registro_id"] for e in analisis["linea_tiempo_relevante"] if e.get("registro_id")}
    ids |= {i for x in analisis["inconsistencias_datos"] for i in x["registro_ids"]}
    return ids


# ---------------------------------------------------------------------------
# Estado y fecha de corte
# ---------------------------------------------------------------------------
def test_estado(client, contexto):
    e = client.get("/api/estado").json()
    assert e["modo_inferencia"] == "simulada" and e["requiere_confirmacion_envio"] is False
    assert e["fecha_corte_max"] == REF and e["fecha_corte_min"] == str(contexto.fecha_corte_min)
    assert "sin autenticación" in e["advertencia"]
    assert e["perfiles_validos"] == len(PIDS_PRUEBA)


@pytest.mark.parametrize("ruta", ["/api/lista", "/api/avisos", "/api/calidad",
                                  "/api/pacientes/PAC-HLF-00002"])
def test_fecha_corte_obligatoria_y_en_rango(client, ruta):
    assert client.get(ruta).status_code == 422
    assert client.get(ruta, params={"fecha_corte": "no-fecha"}).status_code == 422
    for fuera in ("2030-01-01", "2000-01-01"):
        r = client.get(ruta, params={"fecha_corte": fuera})
        assert r.status_code == 422
        assert r.json()["detail"]["codigo"] == "fecha_corte_fuera_de_rango"


# ---------------------------------------------------------------------------
# Lista y avisos
# ---------------------------------------------------------------------------
def test_lista(client):
    j = client.get("/api/lista", params={"fecha_corte": ANTES}).json()
    assert j["items"] and all(i["tipo"] != "exclusion" for i in j["items"])
    assert all(e["tipo"] == "exclusion" and e["motivo_exclusion"] for e in j["excluidos"])
    assert len(j["items"]) + len(j["excluidos"]) + j["n_sin_solicitud_a_la_fecha"] == len(PIDS_PRUEBA)
    assert "PAC-HLF-00009" not in {i["id_paciente"] for i in j["items"]}   # ingresó después
    rango = {"critica": 3, "alta": 2, "media": 1, "baja": 0}
    claves = [(-rango[i["prioridad_calculada"]], -i["score"]) for i in j["items"]]
    assert claves == sorted(claves)


def test_lista_y_avisos_sin_campos_socioeconomicos(client):
    for ruta in ("/api/lista", "/api/avisos"):
        for corte in (ANTES, REF):
            r = client.get(ruta, params={"fecha_corte": corte}).json()
            assert not _claves(r) & set(CAMPOS_PROHIBIDOS)


def test_avisos_solo_priorizacion_o_gestion(client):
    avisos = client.get("/api/avisos", params={"fecha_corte": REF}).json()
    tipos = {a["tipo"] for a in avisos}
    assert tipos <= {"priorizacion", "gestion"} and "gestion" in tipos
    assert all(a["estado_aviso"] == "pendiente" for a in avisos)


# ---------------------------------------------------------------------------
# Paciente
# ---------------------------------------------------------------------------
def test_paciente_sin_datos_posteriores_al_corte(client):
    j = client.get("/api/pacientes/PAC-HLF-00002", params={"fecha_corte": ANTES}).json()
    assert j["eventos"]
    assert all(e["fecha"] <= ANTES for e in j["eventos"])
    assert all(r["fecha"] is None or r["fecha"] <= ANTES for r in j["evidencia"].values())
    assert set(j["perfil"]) == {"id_paciente", "edad", "sexo"}
    assert not _claves(j) & set(CAMPOS_PROHIBIDOS)


def test_estado_historico_no_reconstruible(client):
    antes = client.get("/api/pacientes/PAC-HLF-00002", params={"fecha_corte": ANTES}).json()
    assert antes["solicitud"]["estado_reconstruible"] is False
    assert antes["solicitud"]["estado"] == "desconocido_a_la_fecha"
    ref = client.get("/api/pacientes/PAC-HLF-00002", params={"fecha_corte": REF}).json()
    assert ref["solicitud"]["estado_reconstruible"] is True


def test_paciente_sin_registros(client):
    j = client.get("/api/pacientes/PAC-HLF-00065", params={"fecha_corte": ANTES}).json()
    assert j["eventos"] == []


def test_paciente_sin_solicitud_a_la_fecha(client):
    r = client.get("/api/pacientes/PAC-HLF-00009", params={"fecha_corte": ANTES})
    assert r.status_code == 404 and r.json()["detail"]["codigo"] == "sin_solicitud_a_la_fecha"


def test_pid_invalido(client):
    assert client.get("/api/pacientes/xx", params={"fecha_corte": ANTES}).status_code == 422


def test_motivos_resuelven_en_evidencia(client):
    for pid in ("PAC-HLF-00002", "PAC-HLF-00007"):
        j = client.get(f"/api/pacientes/{pid}", params={"fecha_corte": ANTES}).json()
        ev = j["evaluacion"]
        ids = {i for grupo in ("motivos", "banderas_rojas", "alertas_gestion", "inconsistencias")
               for x in ev[grupo] for i in x["registro_ids"]}
        assert ids and ids <= set(j["evidencia"])


# ---------------------------------------------------------------------------
# Copiloto
# ---------------------------------------------------------------------------
def test_analisis_simulado(client, ruta_auditoria):
    r = client.post("/api/pacientes/PAC-HLF-00002/analisis", json={"fecha_corte": ANTES})
    assert r.status_code == 200
    j = r.json()
    assert j["origen_inferencia"] == "simulada"
    assert j["alerta_id"] == "ALR-PAC-HLF-00002-20260708"
    a = j["analisis"]
    assert a["meta"]["estado"] == "pendiente_revision_medica"
    assert a["meta"]["verificacion"]["citas_no_verificables"] == []
    assert _ids_citados(a) <= set(j["evidencia"])
    tipos = {x["tipo"] for x in leer_jsonl(ruta_auditoria)}
    assert {"llamada_modelo", "tool", "analisis_ia"} <= tipos

    h = client.get("/api/avisos/ALR-PAC-HLF-00002-20260708/historial").json()
    assert h["estado_aviso"] == "analizado" and h["origen_ultimo_analisis"] == "simulada"


def test_analisis_sin_aviso(client):
    r = client.post("/api/pacientes/PAC-HLF-00004/analisis", json={"fecha_corte": ANTES})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "sin_aviso"


def test_analisis_cuerpo_invalido(client):
    r = client.post("/api/pacientes/PAC-HLF-00002/analisis",
                    json={"fecha_corte": ANTES, "otro": 1})
    assert r.status_code == 422
    r = client.post("/api/pacientes/PAC-HLF-00002/analisis", json={"fecha_corte": "2030-01-01"})
    assert r.status_code == 422


class ClienteFalsoReal(ClienteSimulado):
    """Simula el modo real sin red: mismo flujo, otro nombre de modelo."""

    def __init__(self):
        super().__init__()
        self.llamadas = 0
        crear = self.messages.create

        def create(**kw):
            self.llamadas += 1
            resp = crear(**kw)
            resp.model = "modelo-falso-real"
            return resp

        self.messages.create = create


def test_modo_real_exige_confirmacion(contexto, ruta_auditoria):
    falso = ClienteFalsoReal()
    app = crear_app(contexto=contexto, cliente=falso,
                    config=ConfigServidor(inferencia_real=True, auditoria_path=ruta_auditoria))
    with TestClient(app) as c:
        assert c.get("/api/estado").json()["requiere_confirmacion_envio"] is True
        r = c.post("/api/pacientes/PAC-HLF-00002/analisis", json={"fecha_corte": ANTES})
        assert r.status_code == 409 and r.json()["detail"]["codigo"] == "confirmacion_requerida"
        assert falso.llamadas == 0 and leer_jsonl(ruta_auditoria) == []

        r = c.post("/api/pacientes/PAC-HLF-00002/analisis",
                   json={"fecha_corte": ANTES, "confirmar_envio_api_real": True})
        assert r.status_code == 200 and r.json()["origen_inferencia"] == "real"
        assert falso.llamadas == 2


# ---------------------------------------------------------------------------
# Decisión del profesional
# ---------------------------------------------------------------------------
def test_decision_registrada_sin_cambiar_prioridad(client, ruta_auditoria):
    antes = client.get("/api/pacientes/PAC-HLF-00002", params={"fecha_corte": ANTES}).json()
    alerta_id = antes["evaluacion"]["alerta_id"]
    cuerpo = {"medico_id": "PROF-PRUEBA", "decision": "modificada",
              "prioridad_final": "baja", "comentario": "  prueba  "}
    r = client.post(f"/api/avisos/{alerta_id}/decision", json=cuerpo)
    assert r.status_code == 200 and r.json()["registrada"] is True

    decisiones = [x for x in leer_jsonl(ruta_auditoria) if x["tipo"] == "decision_medica"]
    assert len(decisiones) == 1
    assert decisiones[0]["prioridad_final"] == "baja" and decisiones[0]["comentario"] == "prueba"

    despues = client.get("/api/pacientes/PAC-HLF-00002", params={"fecha_corte": ANTES}).json()
    assert despues["evaluacion"]["prioridad_calculada"] == antes["evaluacion"]["prioridad_calculada"]
    assert despues["historial"]["estado_aviso"] == "decidido"


@pytest.mark.parametrize("alerta_id, cuerpo, status", [
    ("ALR-PAC-HLF-00004-20260708", {"medico_id": "PROF-1", "decision": "aceptada",
                                    "prioridad_final": "alta"}, 404),   # sin aviso
    ("ALR-PAC-HLF-00002-20260708", {"medico_id": "x", "decision": "aceptada",
                                    "prioridad_final": "alta"}, 422),
    ("ALR-PAC-HLF-00002-20260708", {"medico_id": "PROF-1", "decision": "aplicar",
                                    "prioridad_final": "alta"}, 422),
    ("ALR-PAC-HLF-00002-20260708", {"medico_id": "PROF-1", "decision": "aceptada",
                                    "prioridad_final": "alta", "extra": 1}, 422),
    ("ALR-PAC-HLF-00002-20300101", {"medico_id": "PROF-1", "decision": "aceptada",
                                    "prioridad_final": "alta"}, 422),
    ("otro", {"medico_id": "PROF-1", "decision": "aceptada", "prioridad_final": "alta"}, 422),
])
def test_decision_errores(client, ruta_auditoria, alerta_id, cuerpo, status):
    assert client.post(f"/api/avisos/{alerta_id}/decision", json=cuerpo).status_code == status
    assert leer_jsonl(ruta_auditoria) == []


# ---------------------------------------------------------------------------
# Calidad, carga única y ausencia de acciones clínicas
# ---------------------------------------------------------------------------
def test_calidad_sin_dq06_antes_de_referencia(client):
    antes = client.get("/api/calidad", params={"fecha_corte": ANTES}).json()
    assert "DQ-06" not in {h["codigo"] for h in antes["hallazgos"]}
    assert antes["cuarentena"] == []
    ref = client.get("/api/calidad", params={"fecha_corte": REF}).json()
    assert "DQ-06" in {h["codigo"] for h in ref["hallazgos"]}


def test_sin_duplicar_json_y_csv(contexto, perfiles_prueba):
    crudo = json.loads(perfiles_prueba.read_text(encoding="utf-8"))
    t = contexto.repo.t
    assert len(t["lista"]) == len(crudo)
    assert len(t["eventos"]) == sum(len(p["eventos_clinicos"]) for p in crudo)
    assert len(t["mediciones"]) == sum(len(p["mediciones"]) for p in crudo)
    assert len(t["citaciones"]) == sum(len(p["citaciones"]) for p in crudo)


def test_no_existen_endpoints_de_acciones_clinicas(client):
    rutas = {(m, r.path) for r in client.app.routes if r.path.startswith("/api")
             for m in getattr(r, "methods", set())}
    assert rutas == {
        ("GET", "/api/estado"), ("GET", "/api/lista"), ("GET", "/api/avisos"),
        ("GET", "/api/pacientes/{pid}"), ("GET", "/api/avisos/{alerta_id}/historial"),
        ("POST", "/api/pacientes/{pid}/analisis"), ("POST", "/api/avisos/{alerta_id}/decision"),
        ("GET", "/api/calidad"),
    }
