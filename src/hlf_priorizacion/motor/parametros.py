"""Carga y validación de ``reglas-vX.Y.Z.yaml``. Cualquier error es fatal (fail-closed)."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hlf_priorizacion.contrato.catalogos import COMBINACIONES_EVENTO, TIPOS_MEDICION, TipoMedicion
from hlf_priorizacion.motor.relaciones import (
    PATRON_VERSION_RELACIONES,
    ErrorRelaciones,
    RelacionesClinicas,
    cargar_relaciones,
)

DIRECTORIO_REGLAS = Path(__file__).resolve().parent / "reglas"
VERSION_POR_DEFECTO = "reglas-v0.2.0"

Positivo = Annotated[float, Field(gt=0)]
NoNegativo = Annotated[float, Field(ge=0)]
Dias = Annotated[int, Field(ge=0, le=3650)]
Operador = Literal[">=", "<=", ">", "<"]


class ErrorParametros(Exception):
    """Parámetros ausentes o inválidos: el lote no puede continuar."""


class _P(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class PorPrioridad(_P):
    alta: NoNegativo
    media: NoNegativo
    baja: NoNegativo


class PlazosEspera(_P):
    alta: Annotated[int, Field(gt=0)]
    media: Annotated[int, Field(gt=0)]
    baja: Annotated[int, Field(gt=0)]


class Umbrales(_P):
    media: NoNegativo
    alta: NoNegativo

    @model_validator(mode="after")
    def _orden(self) -> Self:
        if not self.media < self.alta <= 100:
            raise ValueError("se requiere umbral media < alta <= 100")
        return self


class PesoEvento(_P):
    tipo: str
    subtipo: str
    peso: float


class ParamEventos(_P):
    vida_media_dias: Positivo
    relacion_misma_especialidad: NoNegativo
    relacion_otra_especialidad: NoNegativo
    pesos: list[PesoEvento]

    @property
    def lambda_decaimiento(self) -> float:
        return math.log(2) / self.vida_media_dias

    def peso(self, tipo: str, subtipo: str) -> float:
        for p in self.pesos:
            if p.tipo == tipo and p.subtipo == subtipo:
                return p.peso
        raise KeyError((tipo, subtipo))

    @model_validator(mode="after")
    def _cobertura(self) -> Self:
        claves = [(p.tipo, p.subtipo) for p in self.pesos]
        if len(claves) != len(set(claves)):
            raise ValueError("pesos de eventos duplicados")
        faltan = set(COMBINACIONES_EVENTO) - set(claves)
        if faltan:
            raise ValueError(f"faltan pesos para {len(faltan)} combinación(es) catalogada(s)")
        sobran = set(claves) - set(COMBINACIONES_EVENTO)
        if sobran:
            raise ValueError("hay pesos para combinaciones no catalogadas")
        return self


class Aceleracion(_P):
    aporte: NoNegativo
    ventana_dias: Annotated[int, Field(gt=0)]


class RangoMedicion(_P):
    minimo: float
    maximo: float
    direccion: Literal["alta", "baja", "ambas"]

    @property
    def ancho(self) -> float:
        return self.maximo - self.minimo

    @property
    def medio(self) -> float:
        return (self.maximo + self.minimo) / 2

    @model_validator(mode="after")
    def _orden(self) -> Self:
        if not self.minimo < self.maximo:
            raise ValueError("rango con minimo >= maximo")
        return self


class ParamMediciones(_P):
    tope: NoNegativo
    zona_maximo: NoNegativo
    brusco_aporte: NoNegativo
    brusco_fraccion_ancho: NoNegativo
    tendencia_aporte: NoNegativo
    tendencia_min_puntos: Annotated[int, Field(ge=2)]
    tendencia_max_puntos: Annotated[int, Field(ge=2)]
    tendencia_span_min_dias: Dias
    tendencia_fraccion_ancho_por_30_dias: NoNegativo
    rangos: dict[TipoMedicion, RangoMedicion]

    @model_validator(mode="after")
    def _coherencia(self) -> Self:
        if set(self.rangos) != set(TIPOS_MEDICION):
            raise ValueError("rangos debe definir exactamente los tipos de medición del catálogo")
        if self.tendencia_min_puntos > self.tendencia_max_puntos:
            raise ValueError("tendencia_min_puntos > tendencia_max_puntos")
        return self


class Espera(_P):
    tope: NoNegativo
    plazos: PlazosEspera


class ParamContradiccion(_P):
    dias_antes: Dias
    dias_despues: Dias


class Ventanas(_P):
    mediciones_banderas_pisos_dias: Dias
    evento_grave_bandera_dias: Dias
    evidencia_mejoria_dias: Dias


class ReglaUmbral(_P):
    codigo: Annotated[str, Field(min_length=1)]
    tipo: TipoMedicion
    operador: Operador
    umbral: float

    def cumple(self, valor: float) -> bool:
        if self.operador == ">=":
            return valor >= self.umbral
        if self.operador == "<=":
            return valor <= self.umbral
        if self.operador == ">":
            return valor > self.umbral
        return valor < self.umbral


class ParamAlertas(_P):
    citas_fallidas_minimo: Annotated[int, Field(ge=1)]
    inasistencias_maximo: Annotated[int, Field(ge=0)]
    silencio_dias_espera: Dias
    silencio_dias_sin_registro: Dias


class ParamConfianza(_P):
    dias_mediciones_recientes: Dias
    dias_aviso_sin_mediciones: Dias


class ParamOtrasSolicitudes(_P):
    """R11.4 / R11.5: peso por prioridad inicial de la otra solicitud y tope de la suma."""

    pesos: PorPrioridad
    tope: NoNegativo


class ParametrosReglas(_P):
    version: Annotated[str, Field(pattern=r"^reglas-v\d+\.\d+\.\d+$")]
    # reglas-v0.2.0: versión del documento de relaciones clínicas (R5.3, R11). Sin ella, el motor se comporta
    # como reglas-v0.1.0 (r fijo por especialidad y sin R11).
    relaciones: Annotated[str, Field(pattern=PATRON_VERSION_RELACIONES)] | None = None
    otras_solicitudes: ParamOtrasSolicitudes | None = None
    # Lo llena ``cargar_parametros`` con el documento leído; no se escribe en el YAML.
    documento_relaciones: RelacionesClinicas | None = None
    base: PorPrioridad
    umbrales: Umbrales
    eventos: ParamEventos
    aceleracion: Aceleracion
    mediciones: ParamMediciones
    espera: Espera
    contradiccion: ParamContradiccion
    ventanas: Ventanas
    banderas_medicion: list[ReglaUmbral]
    pisos: list[ReglaUmbral]
    alertas: ParamAlertas
    confianza: ParamConfianza

    @model_validator(mode="after")
    def _codigos_unicos(self) -> Self:
        codigos = [r.codigo for r in self.banderas_medicion + self.pisos]
        if len(codigos) != len(set(codigos)):
            raise ValueError("códigos de bandera/piso duplicados")
        if (self.relaciones is None) != (self.otras_solicitudes is None):
            raise ValueError("relaciones y otras_solicitudes se definen juntas")
        doc = self.documento_relaciones
        if (doc is None) != (self.relaciones is None) or (doc is not None and doc.version != self.relaciones):
            raise ValueError("documento_relaciones no corresponde a la versión declarada en relaciones")
        return self


def ruta_version(version: str) -> Path:
    return DIRECTORIO_REGLAS / f"{version}.yaml"


def cargar_parametros(ruta: Path | None = None, directorio_conocimiento: Path | None = None) -> ParametrosReglas:
    """Lee y valida el YAML. El nombre del archivo debe coincidir con ``version``.

    Si declara ``relaciones``, carga y valida ese documento desde ``directorio_conocimiento`` (por defecto
    ``data/conocimiento/`` o ``HLF_CONOCIMIENTO``) y lo deja en ``documento_relaciones``.
    """
    ruta = ruta or ruta_version(VERSION_POR_DEFECTO)
    try:
        texto = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ErrorParametros(f"no se pudo leer el archivo de reglas {ruta}: {type(e).__name__}") from e
    try:
        datos = yaml.safe_load(texto)
    except yaml.YAMLError as e:
        raise ErrorParametros(f"{ruta} no es YAML válido") from e
    if not isinstance(datos, dict):
        raise ErrorParametros(f"{ruta} debe contener un mapa de parámetros")
    if "documento_relaciones" in datos:
        raise ErrorParametros(f"{ruta.name}: documento_relaciones no se declara en el YAML (use relaciones)")
    nombre_relaciones = datos.get("relaciones")
    if isinstance(nombre_relaciones, str) and re.match(PATRON_VERSION_RELACIONES, nombre_relaciones):
        try:
            datos = {**datos, "documento_relaciones": cargar_relaciones(nombre_relaciones, directorio_conocimiento)}
        except ErrorRelaciones as e:
            raise ErrorParametros(str(e)) from e
    try:
        params = ParametrosReglas.model_validate(datos)
    except ValidationError as e:
        motivos = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in e.errors(include_input=False, include_url=False)
        )
        raise ErrorParametros(f"parámetros inválidos en {ruta.name}: {motivos}") from e
    if ruta.stem != params.version:
        raise ErrorParametros(f"el archivo {ruta.name} declara la versión {params.version}")
    return params
