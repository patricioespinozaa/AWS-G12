"""Persistencia idempotente de propuestas y auditoría de solo agregado."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from hlf_priorizacion.auditoria.registro import RegistroAuditoria, nuevo_ulid
from hlf_priorizacion.modelos import Evaluacion
from hlf_priorizacion.persistencia.salidas import (
    agregar_jsonl,
    escribir_propuestas,
    leer_propuestas,
    ruta_propuestas,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "evaluacion_ejemplo.json"


def _ev() -> Evaluacion:
    return Evaluacion.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def test_escribir_dos_veces_deja_un_registro_y_bytes_identicos(tmp_path: Path) -> None:
    ev = _ev()
    r1 = escribir_propuestas(tmp_path, [(ev, "Cardiología")])
    ruta = ruta_propuestas(tmp_path, date(2026, 8, 10), "reglas-v0.1.0")
    bytes1 = ruta.read_bytes()
    r2 = escribir_propuestas(tmp_path, [(ev, "Cardiología")])
    assert r1[0].nuevas == 1 and r2[0].nuevas == 0 and r2[0].existentes == 1
    assert ruta.read_bytes() == bytes1
    assert leer_propuestas(tmp_path, date(2026, 8, 10), "reglas-v0.1.0") == [ev]


def test_conflicto_conserva_la_primera(tmp_path: Path) -> None:
    ev = _ev()
    escribir_propuestas(tmp_path, [(ev, "Cardiología")])
    otra = ev.model_copy(update={"puntaje": 70.0})
    r = escribir_propuestas(tmp_path, [(otra, "Cardiología")])
    assert r[0].conflictos == 1
    assert leer_propuestas(tmp_path, date(2026, 8, 10), "reglas-v0.1.0")[0].puntaje == ev.puntaje


def test_jsonl_agrega_solo_lo_nuevo(tmp_path: Path) -> None:
    ruta = tmp_path / "h.jsonl"
    registros = [{"k": "a", "v": 1}, {"k": "b", "v": 2}]
    assert agregar_jsonl(ruta, registros, lambda r: str(r["k"])) == 2
    assert agregar_jsonl(ruta, [*registros, {"k": "c", "v": 3}], lambda r: str(r["k"])) == 1
    assert [json.loads(x)["k"] for x in ruta.read_text(encoding="utf-8").splitlines()] == ["a", "b", "c"]


def test_auditoria_solo_agrega(tmp_path: Path) -> None:
    ruta = tmp_path / "auditoria" / "eventos.jsonl"
    reloj = lambda: datetime(2026, 10, 15, 12, 0, tzinfo=UTC)  # noqa: E731
    reg = RegistroAuditoria(ruta, "lote-1", reloj=reloj)
    reg.registrar("evaluacion_motor", id_solicitud="IC-HLF-00002", fecha_corte="2026-07-20")
    primera = ruta.read_text(encoding="utf-8")
    RegistroAuditoria(ruta, "lote-2", reloj=reloj).registrar("error_proceso", id_solicitud="IC-HLF-00003")
    texto = ruta.read_text(encoding="utf-8")
    assert texto.startswith(primera)
    eventos = [json.loads(x) for x in texto.splitlines()]
    assert [e["tipo"] for e in eventos] == ["evaluacion_motor", "error_proceso"]
    assert eventos[0]["timestamp"] == "2026-10-15T12:00:00Z"
    assert {"id_auditoria", "actor", "id_ejecucion"} <= set(eventos[0])


def test_ulid_formato_y_orden() -> None:
    a = nuevo_ulid(1000, bytes(10))
    b = nuevo_ulid(2000, bytes(10))
    assert len(a) == 26 and a < b
