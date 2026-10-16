"""Persistencia incremental y Ctrl+C del copiloto (C5, C4.8) con cliente falso: nunca llaman a Bedrock.

Ctrl+C se simula sin señales reales (determinista en Windows): ``vigia`` lanza ``KeyboardInterrupt`` en la
espera del hilo principal tras ``k`` solicitudes terminadas, o el cliente falso lo lanza en un hilo.
"""

from __future__ import annotations

import functools
import json
import threading
from datetime import date
from pathlib import Path
from typing import Any, NoReturn

import pytest

from ayudantes import FECHA_EXTRACCION, evento, medicion, perfil_base
from estrategias.copiloto import correr_lote, escribir_dataset, responder_eco
from hlf_priorizacion.copiloto import barrido, cli
from hlf_priorizacion.copiloto.barrido import ConfigBarrido, ResumenBarrido, ejecutar_barrido
from hlf_priorizacion.copiloto.cliente import ClienteFalso, PeticionModelo, RespuestaModelo
from hlf_priorizacion.copiloto.config import ConfigModelo
from hlf_priorizacion.copiloto.persistencia import leer_analisis, leer_fallidos
from hlf_priorizacion.copiloto.prompt import cargar_prompt
from hlf_priorizacion.motor.parametros import VERSION_POR_DEFECTO

V = VERSION_POR_DEFECTO  # reglas-v0.2.0: el lote de prueba corre con la versión por defecto
CORTE = date(2026, 7, 20)
N = 6
IDS = [f"IC-TST-{i:05d}" for i in range(1, N + 1)]


def _perfil(i: int) -> dict[str, Any]:
    """Sube a crítica el 2026-07-20 (urgencia ESI 2): queda pendiente para el copiloto."""
    p = perfil_base(
        id_paciente=f"PAC-TST-{i:05d}",
        eventos_clinicos=[evento(f"EV-{i:06d}", "2026-07-20", "visita_urgencia", "triage ESI 2", "grave")],
        mediciones=[
            medicion("2026-06-01", "presion_sistolica", 120, "mmHg"),
            medicion("2026-07-08", "presion_sistolica", 167, "mmHg", True),
        ],
    )
    p["lista_espera"]["id_solicitud"] = f"IC-TST-{i:05d}"
    return p


@pytest.fixture
def entorno(tmp_path: Path) -> tuple[Path, Path]:
    datos = escribir_dataset(tmp_path / "datos", [_perfil(i) for i in range(1, N + 1)])
    salidas = tmp_path / "salidas"
    correr_lote(datos, salidas, [CORTE])
    return datos, salidas


def _args(datos: Path, salidas: Path) -> list[str]:
    return ["--fecha-corte", CORTE.isoformat(), "--datos", str(datos), "--salidas", str(salidas)]


def _eventos(salidas: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (salidas / "auditoria" / "eventos.jsonl").read_text(encoding="utf-8").splitlines()]


def _ids(eventos: list[dict[str, Any]], tipo: str, motivo: str | None = None) -> set[str]:
    return {
        str(e["id_solicitud"]) for e in eventos if e["tipo"] == tipo and (motivo is None or e.get("motivo") == motivo)
    }


def _interrumpir_tras(k: int) -> Any:
    def vigia(n: int) -> None:
        if n == k:
            raise KeyboardInterrupt

    return vigia


def _barrer(datos: Path, salidas: Path, cliente: ClienteFalso, concurrencia: int, id_ejecucion: str) -> ResumenBarrido:
    cfg = ConfigBarrido([CORTE], False, FECHA_EXTRACCION, datos, salidas, V, 300)
    return ejecutar_barrido(cfg, ConfigModelo(concurrencia=concurrencia), cargar_prompt(), cliente, id_ejecucion)


@pytest.mark.parametrize("k", [1, 3])
def test_ctrl_c_guarda_lo_terminado_sale_con_130_y_la_reejecucion_sigue(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, k: int
) -> None:
    datos, salidas = entorno
    soltar = threading.Event()  # las solicitudes después de la k-ésima esperan: Ctrl+C las encuentra sin terminar

    def responder(p: PeticionModelo) -> RespuestaModelo:
        if IDS.index(p.id_solicitud) >= k:
            assert soltar.wait(10)
        return responder_eco(p)

    def vigia(n: int) -> None:
        if n == k:
            soltar.set()  # la que está en curso termina durante la espera y se guarda
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "ejecutar_barrido", functools.partial(barrido.ejecutar_barrido, vigia=vigia))
    cliente = ClienteFalso(responder)
    assert cli.main(_args(datos, salidas), cliente=cliente, entorno={"HLF_COPILOTO_CONCURRENCIA": "1"}) == 130
    salida = capsys.readouterr().out
    assert "Interrumpido con Ctrl+C" in salida and "Interrumpidas (Ctrl+C" in salida

    guardadas = {r.id_solicitud for r in leer_analisis(salidas, CORTE, V)}
    eventos = _eventos(salidas)
    interrumpidas = _ids(eventos, "analisis_omitido", "interrumpido")
    # Las k terminadas (y la que estaba en curso, si alcanzó) quedaron con su análisis y su auditoría.
    assert len(guardadas) >= k
    assert guardadas <= _ids(eventos, "llamada_modelo")
    assert guardadas == _ids(eventos, "analisis_ia")
    assert leer_fallidos(salidas, CORTE, V) == []
    # Ninguna solicitud quedó sin estado ni en dos estados.
    assert guardadas.isdisjoint(interrumpidas) and guardadas | interrumpidas == set(IDS)
    assert interrumpidas  # con concurrencia 1 y k < N siempre quedan algunas sin empezar
    assert f"Analizadas: {len(guardadas)}" in salida

    # La re-ejecución del mismo comando omite lo guardado (ya_analizada) y procesa solo lo interrumpido.
    monkeypatch.setattr(cli, "ejecutar_barrido", barrido.ejecutar_barrido)
    cliente2 = ClienteFalso(responder_eco)
    assert cli.main(_args(datos, salidas), cliente=cliente2, entorno={"HLF_COPILOTO_CONCURRENCIA": "3"}) == 0
    assert {p.id_solicitud for p in cliente2.llamadas} == interrumpidas
    finales = [r.id_solicitud for r in leer_analisis(salidas, CORTE, V)]
    assert sorted(finales) == IDS  # cada solicitud con exactamente un análisis


def test_keyboardinterrupt_desde_un_hilo_se_atiende_como_ctrl_c(entorno: tuple[Path, Path]) -> None:
    datos, salidas = entorno

    def responder(p: PeticionModelo) -> RespuestaModelo:
        if p.id_solicitud == IDS[2]:
            raise KeyboardInterrupt
        return responder_eco(p)

    r = _barrer(datos, salidas, ClienteFalso(responder), 1, "e1")
    guardadas = {x.id_solicitud for x in leer_analisis(salidas, CORTE, V)}
    interrumpidas = _ids(_eventos(salidas), "analisis_omitido", "interrumpido")
    # El hilo libre pudo tomar la siguiente antes de la cancelación: esa termina y también se guarda.
    assert set(IDS[:2]) <= guardadas and IDS[2] in interrumpidas
    assert guardadas.isdisjoint(interrumpidas) and guardadas | interrumpidas == set(IDS)
    assert r.interrumpido and r.analizadas == len(guardadas) and r.interrumpidas == len(interrumpidas)


def test_error_inesperado_del_cliente_en_una_no_pierde_las_demas(entorno: tuple[Path, Path]) -> None:
    datos, salidas = entorno

    def responder(p: PeticionModelo) -> RespuestaModelo | Exception:
        return RuntimeError("caída") if p.id_solicitud == IDS[-1] else responder_eco(p)

    r = _barrer(datos, salidas, ClienteFalso(responder), 2, "e1")
    assert r.analizadas == N - 1 and r.fallidas == {"inesperado": 1} and not r.interrumpido
    assert {x.id_solicitud for x in leer_analisis(salidas, CORTE, V)} == set(IDS[:-1])
    fallidos = [(f.id_solicitud, f.motivo) for f in leer_fallidos(salidas, CORTE, V)]
    assert fallidos == [(IDS[-1], "inesperado:RuntimeError")]


class _Caida(BaseException):
    """Falla que ni ``analizar`` ni el CLI atrapan (simula que el proceso se cae a mitad del barrido)."""


def test_caida_a_mitad_del_barrido_deja_persistido_lo_ya_terminado(entorno: tuple[Path, Path]) -> None:
    datos, salidas = entorno

    def responder(p: PeticionModelo) -> RespuestaModelo:
        if p.id_solicitud == IDS[-1]:
            raise _Caida
        return responder_eco(p)

    with pytest.raises(_Caida):
        _barrer(datos, salidas, ClienteFalso(responder), 1, "e1")
    guardadas = {x.id_solicitud for x in leer_analisis(salidas, CORTE, V)}
    eventos = _eventos(salidas)
    assert guardadas == set(IDS[:-1])  # antes se perdía todo
    assert guardadas <= _ids(eventos, "llamada_modelo") and guardadas == _ids(eventos, "analisis_ia")
    huellas = {e["huella_salida"] for e in eventos if e["tipo"] == "llamada_modelo"}
    io = salidas / "copiloto_io" / f"fecha_corte={CORTE.isoformat()}"
    assert all((io / (h.removeprefix("sha256:") + ".json")).is_file() for h in huellas)

    # La re-ejecución solo llama por la que faltó.
    cliente2 = ClienteFalso(responder_eco)
    _barrer(datos, salidas, cliente2, 4, "e2")
    assert [p.id_solicitud for p in cliente2.llamadas] == [IDS[-1]]


def test_espera_acotada_tras_ctrl_c_abandona_la_llamada_colgada(
    entorno: tuple[Path, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una llamada que no termina dentro de la espera queda como interrumpido y el CLI sale sin esperarla."""
    datos, salidas = entorno
    liberar = threading.Event()

    def responder(p: PeticionModelo) -> RespuestaModelo:
        if p.id_solicitud == IDS[0]:
            liberar.wait(10)  # colgada hasta que la prueba la suelte
        return responder_eco(p)

    def salir(codigo: int) -> NoReturn:
        raise SystemExit(codigo)

    monkeypatch.setattr(cli, "_salir_ya", salir)
    monkeypatch.setattr(
        cli,
        "ejecutar_barrido",
        functools.partial(barrido.ejecutar_barrido, vigia=_interrumpir_tras(1), espera_interrupcion=0.2),
    )
    try:
        with pytest.raises(SystemExit) as e:
            cli.main(_args(datos, salidas), cliente=ClienteFalso(responder), entorno={"HLF_COPILOTO_CONCURRENCIA": "2"})
    finally:
        liberar.set()
    assert e.value.code == 130
    eventos = _eventos(salidas)
    guardadas = {x.id_solicitud for x in leer_analisis(salidas, CORTE, V)}
    interrumpidas = _ids(eventos, "analisis_omitido", "interrumpido")
    assert IDS[0] in interrumpidas and IDS[0] not in guardadas
    assert guardadas | interrumpidas == set(IDS) and guardadas.isdisjoint(interrumpidas)
    assert "Interrumpido con Ctrl+C" in capsys.readouterr().out


def test_ctrl_c_antes_de_las_llamadas_registra_interrumpido_y_sale_con_130(
    entorno: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    datos, salidas = entorno

    def cortar(*_a: Any, **_k: Any) -> NoReturn:
        raise KeyboardInterrupt

    monkeypatch.setattr(barrido, "construir_tarea", cortar)
    cliente = ClienteFalso(responder_eco)
    assert cli.main(_args(datos, salidas), cliente=cliente, entorno={}) == 130
    assert cliente.llamadas == []
    assert _ids(_eventos(salidas), "analisis_omitido", "interrumpido") == set(IDS)
