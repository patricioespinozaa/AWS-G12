"""Documento de relaciones clínicas (insumo estándar, reglas-v0.2.0: R5.3 modificada y R11).

``data/conocimiento/relaciones-clinicas-vX.Y.Z.yaml`` dice:

- con qué factor un evento de la especialidad ``de`` afecta a una solicitud de la especialidad ``a`` (dirigido);
- con qué factor se relacionan los diagnósticos CIE-10 de dos solicitudes abiertas del mismo paciente (simétrico).

Se carga una vez, fuera de ``evaluar()``, y llega al motor dentro de ``ParametrosReglas``. Cualquier error es
fatal (fail-closed), igual que los parámetros. La carpeta se puede cambiar con ``HLF_CONOCIMIENTO``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Final, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hlf_priorizacion.contrato.catalogos import ESPECIALIDADES_CATALOGO, PATRON_CIE10

VARIABLE_CONOCIMIENTO: Final = "HLF_CONOCIMIENTO"
# Raíz del repositorio: src/hlf_priorizacion/motor/relaciones.py -> parents[3].
DIRECTORIO_CONOCIMIENTO: Final = Path(__file__).resolve().parents[3] / "data" / "conocimiento"
PATRON_VERSION_RELACIONES: Final = r"^relaciones-clinicas-v\d+\.\d+\.\d+$"

FactorRelacion = Annotated[float, Field(ge=0, le=1)]
Cie10Relacion = Annotated[str, Field(pattern=PATRON_CIE10)]
EstadoDocumento = Literal["validado", "sintetico_no_validado", "no_validado"]


class ErrorRelaciones(Exception):
    """Documento de relaciones ausente o inválido: el lote no puede continuar."""


class _R(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class ParEspecialidades(_R):
    de: str
    a: str
    factor: FactorRelacion
    motivo: Annotated[str, Field(min_length=1)]


class RelacionEspecialidades(_R):
    por_defecto_otra_especialidad: FactorRelacion
    pares: list[ParEspecialidades]

    @model_validator(mode="after")
    def _pares(self) -> Self:
        claves = [(p.de, p.a) for p in self.pares]
        fuera = sorted({e for c in claves for e in c} - ESPECIALIDADES_CATALOGO)
        if fuera:
            raise ValueError(f"especialidades fuera del catálogo: {', '.join(fuera)}")
        if any(de == a for de, a in claves):
            raise ValueError("un par de especialidades no puede ser de una especialidad consigo misma")
        if len(claves) != len(set(claves)):
            raise ValueError("pares de especialidades repetidos")
        return self


class ParDiagnosticos(_R):
    a: Cie10Relacion
    b: Cie10Relacion
    factor: FactorRelacion
    motivo: Annotated[str, Field(min_length=1)]


class RelacionDiagnosticos(_R):
    por_defecto_misma_especialidad: FactorRelacion
    por_defecto_otra_especialidad: FactorRelacion
    pares: list[ParDiagnosticos]

    @model_validator(mode="after")
    def _pares(self) -> Self:
        claves = [frozenset({p.a, p.b}) for p in self.pares]
        if any(len(c) == 1 for c in claves):
            raise ValueError("un par de diagnósticos no puede repetir el mismo CIE-10")
        if len(claves) != len(set(claves)):
            raise ValueError("pares de diagnósticos repetidos ({a, b} y {b, a} cuentan como el mismo)")
        return self


class RelacionesClinicas(_R):
    version: Annotated[str, Field(pattern=PATRON_VERSION_RELACIONES)]
    estado: EstadoDocumento
    fuente: Annotated[str, Field(min_length=1)]
    especialidades: RelacionEspecialidades
    diagnosticos: RelacionDiagnosticos

    @property
    def validado(self) -> bool:
        return self.estado == "validado"

    def factor_especialidad(self, de: str, a: str) -> tuple[float, bool]:
        """R5.3: factor de un evento de ``de`` sobre una solicitud de ``a`` (otra especialidad) y si estaba listado."""
        for p in self.especialidades.pares:
            if p.de == de and p.a == a:
                return p.factor, True
        return self.especialidades.por_defecto_otra_especialidad, False

    def factor_diagnosticos(self, cie10_a: str, cie10_b: str, misma_especialidad: bool) -> float:
        """R11.3: factor simétrico entre dos CIE-10; si el par no está, el valor por defecto que corresponda."""
        clave = frozenset({cie10_a, cie10_b})
        for p in self.diagnosticos.pares:
            if frozenset({p.a, p.b}) == clave:
                return p.factor
        d = self.diagnosticos
        return d.por_defecto_misma_especialidad if misma_especialidad else d.por_defecto_otra_especialidad


def directorio_conocimiento() -> Path:
    return Path(os.environ.get(VARIABLE_CONOCIMIENTO) or DIRECTORIO_CONOCIMIENTO)


def ruta_relaciones(version: str, directorio: Path | None = None) -> Path:
    return (directorio or directorio_conocimiento()) / f"{version}.yaml"


def cargar_relaciones(version: str, directorio: Path | None = None) -> RelacionesClinicas:
    """Lee y valida ``<directorio>/<version>.yaml``. La versión declarada debe coincidir con el nombre."""
    ruta = ruta_relaciones(version, directorio)
    try:
        texto = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ErrorRelaciones(f"no se pudo leer el documento de relaciones {ruta}: {type(e).__name__}") from e
    try:
        datos = yaml.safe_load(texto)
    except yaml.YAMLError as e:
        raise ErrorRelaciones(f"{ruta} no es YAML válido") from e
    if not isinstance(datos, dict):
        raise ErrorRelaciones(f"{ruta} debe contener un mapa")
    try:
        doc = RelacionesClinicas.model_validate(datos)
    except ValidationError as e:
        motivos = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in e.errors(include_input=False, include_url=False)
        )
        raise ErrorRelaciones(f"documento de relaciones inválido en {ruta.name}: {motivos}") from e
    if ruta.stem != doc.version:
        raise ErrorRelaciones(f"el archivo {ruta.name} declara la versión {doc.version}")
    return doc
