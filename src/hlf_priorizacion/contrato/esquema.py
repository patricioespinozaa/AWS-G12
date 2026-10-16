"""Modelos de entrada del contrato ``contrato-v1.0.0`` (sección 4 de docs/contexto-tecnico.md).

- ``PerfilCrudo``: lo que llega en ``perfiles.json``. ``lista_espera`` se acepta como objeto o lista.
- ``PerfilValido``: perfil aceptado por el contrato, con ``lista_espera`` normalizada a lista y sin
  ``nombre_fantasia`` (se descarta al validar y nunca llega al motor).

Todo es estricto: tipos incorrectos, enumerados fuera de catálogo, combinaciones de evento no
catalogadas o unidades incompatibles hacen fallar la validación (cuarentena, R1.1).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from hlf_priorizacion.contrato.catalogos import (
    COMBINACIONES_EVENTO,
    PATRON_CIE10,
    PATRON_ID_BOX,
    PATRON_ID_CITA,
    PATRON_ID_EVENTO,
    PATRON_ID_PACIENTE,
    PATRON_ID_SOLICITUD,
    UNIDAD_POR_TIPO,
    EstadoCita,
    EstadoSolicitud,
    PrioridadInicial,
    Severidad,
    TipoEvento,
    TipoMedicion,
)

_ESPACIOS = re.compile(r"\s+")


def normalizar_cie10(codigo: str) -> str:
    """Mayúsculas y sin espacios. Idempotente. No agrega punto a códigos de 3 caracteres (4.4)."""
    return _ESPACIOS.sub("", codigo).upper()


def _cie10_antes(valor: Any) -> Any:
    return normalizar_cie10(valor) if isinstance(valor, str) else valor


def _vacio_a_nulo(valor: Any) -> Any:
    """En el dataset, ``minutos_atencion_real`` llega como ``""`` cuando no hubo atención."""
    return None if valor == "" else valor


Texto = Annotated[str, Field(min_length=1)]
MinutosOpcionales = Annotated[Annotated[int, Field(ge=0)] | None, BeforeValidator(_vacio_a_nulo)]
Cie10 = Annotated[str, BeforeValidator(_cie10_antes), Field(pattern=PATRON_CIE10)]


class _Entrada(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class PacienteCrudo(_Entrada):
    nombre_fantasia: str | None = None
    edad: int = Field(ge=0, le=120)
    sexo: Texto
    comuna: str
    prevision: str
    nivel_socioeconomico: str
    fallecido: bool
    fecha_defuncion: date | None = None

    @model_validator(mode="after")
    def _defuncion(self) -> Self:
        if self.fallecido and self.fecha_defuncion is None:
            raise ValueError("fallecido = true sin fecha_defuncion")
        return self


class Paciente(_Entrada):
    """Paciente validado: sin ``nombre_fantasia``."""

    edad: int = Field(ge=0, le=120)
    sexo: Texto
    comuna: str
    prevision: str
    nivel_socioeconomico: str
    fallecido: bool
    fecha_defuncion: date | None = None

    @model_validator(mode="after")
    def _defuncion(self) -> Self:
        if self.fallecido and self.fecha_defuncion is None:
            raise ValueError("fallecido = true sin fecha_defuncion")
        return self


class Solicitud(_Entrada):
    id_solicitud: Annotated[str, Field(pattern=PATRON_ID_SOLICITUD)]
    especialidad: Texto
    sub_especialidad: str
    diagnostico_cie10: Cie10
    diagnostico_texto: str
    prioridad_inicial: PrioridadInicial
    fecha_ingreso_lista: date
    origen_derivacion: str
    estado: EstadoSolicitud


class EventoCrudo(_Entrada):
    id_evento: Annotated[str, Field(pattern=PATRON_ID_EVENTO)]
    fecha_evento: date
    tipo_evento: TipoEvento
    subtipo: Texto
    severidad: Severidad
    detalle: str

    @model_validator(mode="after")
    def _combinacion(self) -> Self:
        esperada = COMBINACIONES_EVENTO.get((self.tipo_evento, self.subtipo))
        if esperada is None:
            raise ValueError("combinación tipo_evento/subtipo no catalogada")
        if esperada != self.severidad:
            raise ValueError("severidad no corresponde a la combinación tipo_evento/subtipo")
        return self


class MedicionCruda(_Entrada):
    fecha_medicion: date
    tipo_medicion: TipoMedicion
    valor: Decimal
    unidad: str
    fuera_de_rango: bool

    @model_validator(mode="after")
    def _unidad_y_valor(self) -> Self:
        if not self.valor.is_finite():
            raise ValueError("valor no numérico")
        if UNIDAD_POR_TIPO[self.tipo_medicion] != self.unidad:
            raise ValueError("unidad incompatible con tipo_medicion")
        return self


class CitaCruda(_Entrada):
    id_cita: Annotated[str, Field(pattern=PATRON_ID_CITA)]
    id_box: Annotated[str, Field(pattern=PATRON_ID_BOX)]
    fecha_cita: date
    especialidad: Texto
    estado_cita: EstadoCita
    minutos_atencion_real: MinutosOpcionales = None


class PerfilCrudo(_Entrada):
    """Perfil tal como llega. ``lista_espera`` puede ser un objeto (dataset actual) o una lista."""

    id_paciente: Annotated[str, Field(pattern=PATRON_ID_PACIENTE)]
    paciente: PacienteCrudo
    lista_espera: Solicitud | Annotated[list[Solicitud], Field(min_length=1)]
    eventos_clinicos: list[EventoCrudo] = Field(default_factory=list)
    mediciones: list[MedicionCruda] = Field(default_factory=list)
    citaciones: list[CitaCruda] = Field(default_factory=list)

    def solicitudes(self) -> list[Solicitud]:
        return [self.lista_espera] if isinstance(self.lista_espera, Solicitud) else list(self.lista_espera)


class PerfilValido(_Entrada):
    """Perfil aceptado por el contrato (normalizado)."""

    id_paciente: Annotated[str, Field(pattern=PATRON_ID_PACIENTE)]
    paciente: Paciente
    lista_espera: Annotated[list[Solicitud], Field(min_length=1)]
    eventos_clinicos: list[EventoCrudo] = Field(default_factory=list)
    mediciones: list[MedicionCruda] = Field(default_factory=list)
    citaciones: list[CitaCruda] = Field(default_factory=list)

    @classmethod
    def desde_crudo(cls, crudo: PerfilCrudo) -> PerfilValido:
        return cls(
            id_paciente=crudo.id_paciente,
            paciente=Paciente.model_validate(crudo.paciente.model_dump(exclude={"nombre_fantasia"})),
            lista_espera=crudo.solicitudes(),
            eventos_clinicos=list(crudo.eventos_clinicos),
            mediciones=list(crudo.mediciones),
            citaciones=list(crudo.citaciones),
        )
