"""Fixtures de la capa HTTP. Sin red: cualquier conexión fuera de loopback falla."""
import hashlib
import json
import os
import socket
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Guardia de entorno antes de importar el backend: modo simulado y sin leer .env.
os.environ.pop("COPILOTO_INFERENCIA_REAL", None)
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ.setdefault("ANTHROPIC_MODEL", "simulado-local")

import pytest  # noqa: E402

import servidor  # noqa: E402,F401
import auditoria  # noqa: E402
import copiloto  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from servidor.app import crear_app  # noqa: E402
from servidor.configuracion import ConfigServidor  # noqa: E402
from servidor.servicios import ContextoDatos  # noqa: E402

# Incluye: alerta (00002), DQ-01 (00007), ingreso posterior a 2026-07-08 y exclusión al
# 13-10 (00009), gestión al 13-10 (00020), DQ-06/cita asistida (00005, 00021), sin
# registros (00056, 00065), gestión al 08-07 (00062), sin alerta (00004), excluido (00010).
PIDS_PRUEBA = [f"PAC-HLF-{n:05d}" for n in
               (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 20, 21, 22, 32, 56, 62, 65)]
ARCHIVOS_PROTEGIDOS = sorted([RAIZ / "perfiles.json", RAIZ / "auditoria.jsonl",
                              *RAIZ.glob("*.csv")])
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _huellas() -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in ARCHIVOS_PROTEGIDOS if p.exists()}


@pytest.fixture(scope="session", autouse=True)
def datos_originales_intactos():
    antes = _huellas()
    yield
    assert _huellas() == antes, "Las pruebas modificaron datos originales o auditoria.jsonl"


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    original = socket.socket.connect

    def conectar(self, direccion, *a, **kw):
        host = direccion[0] if isinstance(direccion, tuple) else str(direccion)
        if host not in LOOPBACK:            # socketpair interno del event loop (Windows)
            raise RuntimeError(f"Conexión de red bloqueada en pruebas: {host}")
        return original(self, direccion, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", conectar)


@pytest.fixture(scope="session")
def perfiles_prueba(tmp_path_factory) -> Path:
    crudo = json.loads((RAIZ / "perfiles.json").read_text(encoding="utf-8"))
    subconjunto = [p for p in crudo if p["id_paciente"] in PIDS_PRUEBA]
    assert len(subconjunto) == len(PIDS_PRUEBA)
    ruta = tmp_path_factory.mktemp("datos") / "perfiles.json"
    ruta.write_text(json.dumps(subconjunto, ensure_ascii=False), encoding="utf-8")
    return ruta


@pytest.fixture(scope="session")
def contexto(perfiles_prueba) -> ContextoDatos:
    return ContextoDatos.cargar(perfiles_prueba, RAIZ / "agenda_box.csv")


@pytest.fixture
def ruta_auditoria(tmp_path, monkeypatch) -> Path:
    ruta = tmp_path / "auditoria.jsonl"
    monkeypatch.setattr(auditoria, "LOG", ruta)
    monkeypatch.setattr(copiloto, "_cliente", copiloto._cliente)   # se restaura al final
    return ruta


@pytest.fixture
def client(contexto, ruta_auditoria):
    app = crear_app(contexto=contexto,
                    config=ConfigServidor(inferencia_real=False, auditoria_path=ruta_auditoria))
    with TestClient(app) as c:
        yield c


def leer_jsonl(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]
