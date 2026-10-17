"""Logs JSON con id de correlación y sin datos personales (F0013)."""
import io
import json
import logging

import pytest

from servicios.comun import logs


def _capturar(formato="json"):
    h = logs.configurar(formato=formato)
    salida = io.StringIO()
    h.setStream(salida)
    return salida


def _lineas(salida):
    return [json.loads(l) for l in salida.getvalue().splitlines() if l.strip()]


def test_json_con_correlacion_y_campos_del_mensaje():
    salida = _capturar()
    with logs.correlacion("lambda-req-12345678"):
        logging.getLogger("hlf.ia").info(json.dumps({"evento": "bedrock", "tokens_salida": 120}))
    logging.getLogger("hlf.ia").info("sin correlación")
    (a, b) = _lineas(salida)
    assert a["id_correlacion"] == "lambda-req-12345678" and a["evento"] == "bedrock" and a["tokens_salida"] == 120
    assert "id_correlacion" not in b and b["mensaje"] == "sin correlación" and b["nivel"] == "INFO"


def test_id_externo_solo_si_tiene_forma_de_id():
    with logs.correlacion("hola; DROP TABLE x") as cid:
        assert cid != "hola; DROP TABLE x" and len(cid) == 32
    with logs.correlacion(None) as cid:
        assert len(cid) == 32


def test_sin_datos_personales():
    salida = _capturar()
    log = logging.getLogger("hlf.prueba")
    log.info("Paciente PAC-HLF-00002 llamó desde +56 9 1234 5678, RUT 12.345.678-5, correo ana@ejemplo.cl, 912345678")
    log.info(json.dumps({"evento": "x", "nombre": "Manuel Pérez", "telefono": "+56912345678", "id_paciente": "PAC-HLF-00002"}))
    (a, b) = _lineas(salida)
    assert "PAC-HLF-00002" in a["mensaje"] and "2026-10-13" not in a["mensaje"]
    for dato in ("1234 5678", "12.345.678-5", "ana@ejemplo.cl", "912345678"):
        assert dato not in a["mensaje"]
    assert a["mensaje"].count("[telefono]") == 2 and "[rut]" in a["mensaje"] and "[correo]" in a["mensaje"]
    assert b["nombre"] == "[omitido]" and b["telefono"] == "[omitido]" and b["id_paciente"] == "PAC-HLF-00002"
    assert logs.enmascarar("fecha 2026-10-13, lista 12345678-9 días 120") == "fecha 2026-10-13, lista [rut] días 120"


def test_excepcion_queda_en_el_mismo_objeto():
    salida = _capturar()
    try:
        raise ValueError("falló")
    except ValueError:
        logging.getLogger("hlf.nocturno").exception(json.dumps({"evento": "nocturno", "resultado": "error"}))
    (a,) = _lineas(salida)
    assert a["resultado"] == "error" and "ValueError" in a["error"] and a["nivel"] == "ERROR"


@pytest.mark.datos                    # la API carga el dataset al importarse
def test_la_api_devuelve_y_registra_el_id_de_correlacion():
    from fastapi.testclient import TestClient
    from api.main import app
    salida = _capturar()
    cliente = TestClient(app)
    r = cliente.get("/api/meta", headers={"X-Correlation-Id": "prueba-correlacion-1"})
    assert r.headers["X-Correlation-Id"] == "prueba-correlacion-1"
    peticiones = [l for l in _lineas(salida) if l.get("evento") == "peticion"]
    assert peticiones and peticiones[-1]["id_correlacion"] == "prueba-correlacion-1"
    assert peticiones[-1]["ruta"] == "/api/meta" and peticiones[-1]["estado"] == r.status_code
    assert len(cliente.get("/api/salud").headers["X-Correlation-Id"]) == 32     # uno nuevo si no viene


def teardown_module():
    logs.configurar(formato="texto")
