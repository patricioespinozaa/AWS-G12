"""Prueba de integración de la CLI del lote con un dataset sintético mínimo (sin datos reales)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ayudantes import cita, evento, medicion, perfil_base
from hlf_priorizacion.lote import SALIDA_ENTRADA, SALIDA_OK, main
from hlf_priorizacion.motor.parametros import VERSION_POR_DEFECTO


def _dataset(tmp_path: Path) -> Path:
    datos = tmp_path / "datos"
    datos.mkdir()
    p1 = perfil_base(
        eventos_clinicos=[evento("EV-000001", "2026-07-20", "visita_urgencia", "triage ESI 2", "grave")],
        mediciones=[medicion("2026-07-08", "presion_sistolica", 167, "mmHg", True)],
    )
    p2 = perfil_base(
        id_paciente="PAC-TST-00002",
        citaciones=[
            cita("CT-000001", "2026-05-01", "no_asistio"),
            cita("CT-000002", "2026-06-01", "reprogramo"),
        ],
    )
    p2["lista_espera"]["id_solicitud"] = "IC-TST-00002"  # type: ignore[index]
    malo = perfil_base(id_paciente="PAC-TST-00003")
    malo["lista_espera"].update({"id_solicitud": "IC-TST-00003", "prioridad_inicial": "urgente"})  # type: ignore[attr-defined]
    (datos / "perfiles.json").write_text(json.dumps([p1, p2, malo], ensure_ascii=False), encoding="utf-8")
    return datos


def test_lote_extremo_a_extremo_idempotente(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    datos = _dataset(tmp_path)
    salidas = tmp_path / "salidas"
    args = ["--fecha-corte", "2026-07-20", "--datos", str(datos), "--salidas", str(salidas)]
    assert main(args) == SALIDA_OK
    salida = capsys.readouterr()
    assert "Cobertura: 100.0 %" in salida.out
    # Logs JSON sin valores clínicos ni datos personales.
    for linea in salida.err.strip().splitlines():
        registro = json.loads(linea)
        assert {"timestamp", "nivel", "id_ejecucion", "mensaje"} <= set(registro)
    assert "167" not in salida.err and "Comuna A" not in salida.err and "Paciente Prueba" not in salida.err

    particion = f"version_reglas={VERSION_POR_DEFECTO}"
    parquet = salidas / "propuestas" / "fecha_corte=2026-07-20" / particion / "propuestas.parquet"
    resumen = salidas / "resumen" / "fecha_corte=2026-07-20" / particion / "resumen.json"
    cuarentena = salidas / "cuarentena" / "fecha_extraccion=2026-10-13" / "cuarentena.jsonl"
    auditoria = salidas / "auditoria" / "eventos.jsonl"
    primeros = {r: r.read_bytes() for r in (parquet, resumen, cuarentena)}
    datos_resumen = json.loads(resumen.read_text(encoding="utf-8"))
    assert datos_resumen["solicitudes"]["evaluadas"] == 2
    assert datos_resumen["perfiles"]["cuarentena"] == 1
    assert datos_resumen["cobertura"]["completa"] is True
    assert json.loads(cuarentena.read_text(encoding="utf-8"))["alerta_gestion"] == "perfil_en_cuarentena"
    lineas_auditoria = len(auditoria.read_text(encoding="utf-8").splitlines())
    assert lineas_auditoria == 2

    # Segunda ejecución: salidas idénticas; la auditoría solo crece.
    capsys.readouterr()
    assert main(args) == SALIDA_OK
    for ruta, contenido in primeros.items():
        assert ruta.read_bytes() == contenido, ruta
    assert "Propuestas nuevas: 0 · ya existentes: 2 · conflictos: 0" in capsys.readouterr().out
    assert len(auditoria.read_text(encoding="utf-8").splitlines()) == 2 * lineas_auditoria


@pytest.mark.parametrize(
    "extra",
    [
        ["--fecha-corte", "2026-10-14"],
        ["--fecha-corte", "2025-01-01"],
    ],
)
def test_fecha_corte_fuera_de_rango(tmp_path: Path, extra: list[str]) -> None:
    datos = _dataset(tmp_path)
    assert main([*extra, "--datos", str(datos), "--salidas", str(tmp_path / "s")]) == SALIDA_ENTRADA


@pytest.mark.parametrize("fecha", ["2026/07/20", "20-07-2026", "2026-02-30"])
def test_formato_de_fecha_invalido(fecha: str) -> None:
    with pytest.raises(SystemExit) as e:
        main(["--fecha-corte", fecha])
    assert e.value.code == 2


def test_rutas_invalidas(tmp_path: Path) -> None:
    datos = _dataset(tmp_path)
    assert main(["--fecha-corte", "2026-07-20", "--datos", str(tmp_path / "no")]) == SALIDA_ENTRADA
    assert main(["--fecha-corte", "2026-07-20", "--datos", str(datos), "--salidas", str(datos / "s")]) == SALIDA_ENTRADA
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    assert (
        main(["--fecha-corte", "2026-07-20", "--datos", str(vacio), "--salidas", str(tmp_path / "s")]) == SALIDA_ENTRADA
    )


def test_reglas_invalidas_detienen_el_lote(tmp_path: Path) -> None:
    datos = _dataset(tmp_path)
    reglas = tmp_path / "reglas-v0.1.0.yaml"
    reglas.write_text("version: reglas-v0.1.0\n", encoding="utf-8")
    args = ["--fecha-corte", "2026-07-20", "--datos", str(datos), "--salidas", str(tmp_path / "s"), "--reglas"]
    assert main([*args, str(reglas)]) == SALIDA_ENTRADA
    assert main([*args, str(tmp_path / "no-existe.yaml")]) == SALIDA_ENTRADA
