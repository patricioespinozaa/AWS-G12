"""Carga fail-closed del documento de relaciones clínicas y de reglas-v0.2.0."""

from __future__ import annotations

from pathlib import Path

import pytest

from hlf_priorizacion.motor.parametros import ErrorParametros, cargar_parametros, ruta_version
from hlf_priorizacion.motor.relaciones import (
    DIRECTORIO_CONOCIMIENTO,
    VARIABLE_CONOCIMIENTO,
    ErrorRelaciones,
    cargar_relaciones,
)

VERSION = "relaciones-clinicas-v0.1.0"
TEXTO = (DIRECTORIO_CONOCIMIENTO / f"{VERSION}.yaml").read_text(encoding="utf-8")


def _escribir(tmp_path: Path, texto: str, version: str = VERSION) -> Path:
    (tmp_path / f"{version}.yaml").write_text(texto, encoding="utf-8")
    return tmp_path


def test_el_documento_versionado_es_valido_y_no_esta_validado() -> None:
    doc = cargar_relaciones(VERSION)
    assert doc.version == VERSION and doc.estado == "sintetico_no_validado" and not doc.validado
    assert doc.factor_especialidad("Endocrinología", "Cardiología") == (0.7, True)
    assert doc.factor_especialidad("Cardiología", "Endocrinología") == (0.5, False)  # dirigido
    assert doc.factor_diagnosticos("I50", "I20", True) == doc.factor_diagnosticos("I20", "I50", True) == 0.9
    assert doc.factor_diagnosticos("I20", "I10", True) == 0.7
    assert doc.factor_diagnosticos("I20", "I99", True) == 0.5  # misma especialidad, sin par
    assert doc.factor_diagnosticos("I20", "M75", False) == 0.0  # otra especialidad, sin par


@pytest.mark.parametrize(
    ("viejo", "nuevo", "mensaje"),
    [
        ("factor: 0.7, motivo: \"Descompensación", "factor: 1.7, motivo: \"Descompensación", "less than or equal"),
        ("{de: Endocrinología, a: Cardiología", "{de: Oftalmología, a: Cardiología", "fuera del catálogo"),
        ("{a: I20, b: I50", "{a: I2O, b: I50", "pattern"),
        (
            "    - {a: I10, b: I20, factor: 0.7",
            "    - {a: I50, b: I20, factor: 0.3, motivo: x}\n    - {a: I10, b: I20, factor: 0.7",
            "repetidos",
        ),
        (
            "    - {de: Broncopulmonar, a: Cardiología",
            "    - {de: Endocrinología, a: Cardiología, factor: 0.1, motivo: x}\n"
            "    - {de: Broncopulmonar, a: Cardiología",
            "repetidos",
        ),
        ("estado: sintetico_no_validado", "estado: tal_vez", "estado"),
        ("por_defecto_otra_especialidad: 0.5", "por_defecto_otra_especialidad: -0.1", "greater than or equal"),
    ],
)
def test_documento_invalido_detiene(tmp_path: Path, viejo: str, nuevo: str, mensaje: str) -> None:
    assert viejo in TEXTO
    directorio = _escribir(tmp_path, TEXTO.replace(viejo, nuevo, 1))
    with pytest.raises(ErrorRelaciones, match=mensaje):
        cargar_relaciones(VERSION, directorio)


def test_version_distinta_del_nombre_o_archivo_ausente(tmp_path: Path) -> None:
    _escribir(tmp_path, TEXTO, "relaciones-clinicas-v0.9.0")
    with pytest.raises(ErrorRelaciones, match="declara la versión"):
        cargar_relaciones("relaciones-clinicas-v0.9.0", tmp_path)
    with pytest.raises(ErrorRelaciones, match="no se pudo leer"):
        cargar_relaciones("relaciones-clinicas-v9.9.9", tmp_path)


def test_reglas_v020_fallan_cerradas_si_el_documento_falta_o_es_invalido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ErrorParametros, match="no se pudo leer el documento de relaciones"):
        cargar_parametros(directorio_conocimiento=tmp_path)
    _escribir(tmp_path, TEXTO.replace("factor: 0.9", "factor: 9", 1))
    monkeypatch.setenv(VARIABLE_CONOCIMIENTO, str(tmp_path))  # carpeta configurable por variable
    with pytest.raises(ErrorParametros, match="documento de relaciones inválido"):
        cargar_parametros()


def test_reglas_v020_exigen_relaciones_y_otras_solicitudes_juntas(tmp_path: Path) -> None:
    texto = ruta_version("reglas-v0.2.0").read_text(encoding="utf-8")
    malo = tmp_path / "reglas-v0.2.0.yaml"
    malo.write_text(texto.replace("relaciones: relaciones-clinicas-v0.1.0\n", ""), encoding="utf-8")
    with pytest.raises(ErrorParametros, match="se definen juntas"):
        cargar_parametros(malo)
    malo.write_text(texto + "documento_relaciones: {}\n", encoding="utf-8")
    with pytest.raises(ErrorParametros, match="no se declara en el YAML"):
        cargar_parametros(malo)


def test_reglas_v010_no_cambian_y_siguen_sin_documento() -> None:
    p = cargar_parametros(ruta_version("reglas-v0.1.0"))
    assert p.version == "reglas-v0.1.0" and p.relaciones is None and p.documento_relaciones is None
