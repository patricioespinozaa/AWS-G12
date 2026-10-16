"""Propiedades del contrato y la ingesta (round-trip, idempotencia, conmutatividad)."""

from __future__ import annotations

import copy
import random
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from estrategias import perfil_y_corte, perfiles
from estrategias.tuberia import evaluar_crudo, normalizar
from hlf_priorizacion.contrato.esquema import PerfilValido, normalizar_cie10
from hlf_priorizacion.contrato.validacion import validar_perfil
from hlf_priorizacion.ingesta.normalizacion import deduplicar_mediciones


@given(perfiles())
def test_round_trip_perfil_valido(raw: dict[str, Any]) -> None:
    res = validar_perfil(raw)
    assert res.ok and res.perfil is not None
    assert PerfilValido.model_validate_json(res.perfil.model_dump_json()) == res.perfil


@given(st.text(alphabet=st.characters(codec="ascii"), max_size=12))
def test_normalizar_cie10_idempotente(codigo: str) -> None:
    una = normalizar_cie10(codigo)
    assert normalizar_cie10(una) == una


def _barajar(raw: dict[str, Any], semilla: int) -> dict[str, Any]:
    """Reordena filas y el orden de los campos de cada fila."""
    rnd = random.Random(semilla)  # noqa: S311 - solo para barajar en pruebas
    nuevo = copy.deepcopy(raw)
    for serie in ("eventos_clinicos", "mediciones", "citaciones"):
        filas = [dict(sorted(f.items(), key=lambda _: rnd.random())) for f in nuevo[serie]]
        rnd.shuffle(filas)
        nuevo[serie] = filas
    return nuevo


@given(perfil_y_corte(), st.integers(0, 2**32))
def test_reordenar_no_cambia_ids_ni_resultado(caso: tuple[dict[str, Any], Any], semilla: int) -> None:
    raw, corte = caso
    barajado = _barajar(raw, semilla)
    assert {m.id_medicion for m in normalizar(raw).mediciones} == {
        m.id_medicion for m in normalizar(barajado).mediciones
    }
    assert evaluar_crudo(raw, corte)[2] == evaluar_crudo(barajado, corte)[2]


@given(perfiles(max_mediciones=12))
def test_deduplicar_dos_veces_igual_a_una(raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(raw)
    raw["mediciones"] = raw["mediciones"] + raw["mediciones"][:3]  # fuerza duplicados
    meds = normalizar(raw).mediciones
    una, _ = deduplicar_mediciones(list(meds) + list(meds))
    dos, duplicados = deduplicar_mediciones(una)
    assert una == dos and duplicados == []
