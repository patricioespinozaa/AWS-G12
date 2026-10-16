"""Contratos compartidos entre unidades (U1 motor, U2 copiloto, U3 bandeja).

Todas las entidades son inmutables (``frozen=True``) y se validan en modo estricto.
Ver ``aidlc-docs/construction/u1-nucleo-motor/functional-design/domain-entities.md`` y las
secciones 6.8 (Evaluacion) y 8.4 (AnalisisIA) de ``docs/contexto-tecnico.md``.

``ContextoPaciente`` no tiene ``comuna``, ``prevision``, ``nivel_socioeconomico`` ni
``nombre_fantasia``: es la garantía estructural de la regla de equidad.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hlf_priorizacion.contrato.catalogos import (
    EstadoALaFecha,
    EstadoCita,
    EstadoSolicitud,
    PrioridadInicial,
    Severidad,
    TipoEvento,
    TipoMedicion,
)

Nivel = Literal["baja", "media", "alta", "critica"]
ORDEN_NIVEL: dict[str, int] = {"baja": 0, "media": 1, "alta": 2, "critica": 3}
NIVELES: tuple[Nivel, ...] = ("baja", "media", "alta", "critica")

TipoResultado = Literal["priorizacion", "gestion", "exclusion", "sin_alerta"]
Confianza = Literal["alta", "media", "baja"]
NivelHallazgo = Literal["descartar", "verificar", "info"]
TipoFactor = Literal[
    "base",
    "evento",
    "medicion_zona",
    "medicion_brusco",
    "medicion_tendencia",
    "aceleracion",
    "espera",
    "otra_solicitud",  # reglas-v0.2.0, R11
]
ESTADO_REVISION_INICIAL: Literal["pendiente_revision_medica"] = "pendiente_revision_medica"


class Modelo(BaseModel):
    """Base común: estricto, inmutable y sin campos extra."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


# --------------------------------------------------------------------------- contexto


class RegistroEvento(Modelo):
    id_evento: str
    fecha_evento: date
    tipo_evento: TipoEvento
    subtipo: str
    severidad: Severidad
    detalle: str
    especialidad_evento: str
    especialidad_inferida: bool = False


class RegistroMedicion(Modelo):
    id_medicion: str
    fecha_medicion: date
    tipo_medicion: TipoMedicion
    valor: Decimal
    unidad: str
    fuera_de_rango_origen: bool


class RegistroCita(Modelo):
    id_cita: str
    id_box: str
    fecha_cita: date
    especialidad: str
    estado_cita: EstadoCita
    minutos_atencion_real: int | None = None


class SolicitudContexto(Modelo):
    id_solicitud: str
    especialidad: str
    sub_especialidad: str
    diagnostico_cie10: str
    diagnostico_texto: str
    prioridad_inicial: PrioridadInicial
    fecha_ingreso_lista: date
    origen_derivacion: str
    estado_extraccion: EstadoSolicitud
    estado_a_la_fecha: EstadoALaFecha


class ContextoPaciente(Modelo):
    """Todo lo que el motor puede ver de una solicitud a una fecha de corte."""

    id_paciente: str
    id_solicitud: str
    fecha_corte: date
    fecha_extraccion: date
    edad: int
    sexo: str
    solicitud: SolicitudContexto
    fallecido_a_la_fecha: bool
    fecha_defuncion: date | None = None
    fecha_egreso_inferida: date | None = None
    id_cita_egreso_inferido: str | None = None
    eventos: list[RegistroEvento] = Field(default_factory=list)
    mediciones: list[RegistroMedicion] = Field(default_factory=list)
    citas: list[RegistroCita] = Field(default_factory=list)
    otras_solicitudes: list[SolicitudContexto] = Field(default_factory=list)
    huella: str = ""

    def ids_presentes(self) -> set[str]:
        """IDs de registro que se pueden citar en una explicación."""
        ids = {self.id_solicitud, self.id_paciente}
        ids.update(e.id_evento for e in self.eventos)
        ids.update(m.id_medicion for m in self.mediciones)
        ids.update(c.id_cita for c in self.citas)
        ids.update(s.id_solicitud for s in self.otras_solicitudes)
        return ids


class RegistroCitado(Modelo):
    """Entrada de la línea de tiempo: siempre con su ID de registro."""

    fecha: date
    tipo_registro: Literal["solicitud", "evento", "medicion", "cita"]
    id_registro: str
    descripcion: str


class HallazgoDQ(Modelo):
    codigo: str
    nivel: NivelHallazgo
    ids_registro: list[str] = Field(min_length=1)
    detalle: str


class ResultadoCohorte(Modelo):
    clave: str
    nivel_relajacion: int = Field(ge=0, le=2)
    n: int = Field(ge=0)
    k: int = Field(ge=0)
    p: float | None
    ic95_inf: float | None
    ic95_sup: float | None
    advertencia_muestra_pequena: bool
    advertencia_sesgo_acceso: bool = True


# --------------------------------------------------------------------------- evaluación


class Factor(Modelo):
    factor: TipoFactor
    detalle: str
    aporte: float
    ids_registro: list[str] = Field(min_length=1)


class Bandera(Modelo):
    codigo: str
    ids_registro: list[str] = Field(min_length=1)


class Piso(Modelo):
    codigo: str
    ids_registro: list[str] = Field(min_length=1)


class Contradiccion(Modelo):
    id_evento: str
    ids_medicion: list[str] = Field(min_length=1)
    pregunta_clinica: str


class AlertaGestion(Modelo):
    codigo: str
    ids_registro: list[str] = Field(min_length=1)
    accion_sugerida: str


class MarcaInferido(Modelo):
    """Dato que el motor infiere (no viene explícito en la fuente)."""

    campo: str
    valor: str
    ids_registro: list[str] = Field(min_length=1)


class Evaluacion(Modelo):
    """Salida del motor (sección 6.8). Nace siempre pendiente de revisión médica."""

    id_solicitud: str
    fecha_corte: date
    version_reglas: str
    huella_contexto: str
    prioridad_inicial: PrioridadInicial
    puntaje: float | None
    nivel_calculado: Nivel | None
    nivel_propuesto: Nivel | None
    tipo_resultado: TipoResultado
    codigo_exclusion: str | None = None
    banderas: list[Bandera] = Field(default_factory=list)
    pisos: list[Piso] = Field(default_factory=list)
    contradicciones: list[Contradiccion] = Field(default_factory=list)
    factores: list[Factor] = Field(default_factory=list)
    alertas_gestion: list[AlertaGestion] = Field(default_factory=list)
    confianza: Confianza
    motivo_confianza: list[str] = Field(default_factory=list)
    marcas_inferido: list[MarcaInferido] = Field(default_factory=list)
    estado_revision: Literal["pendiente_revision_medica"] = ESTADO_REVISION_INICIAL

    @model_validator(mode="after")
    def _coherencia(self) -> Self:
        if self.tipo_resultado == "exclusion":
            if not self.codigo_exclusion:
                raise ValueError("una exclusión exige codigo_exclusion")
        elif self.puntaje is None or self.nivel_calculado is None or self.nivel_propuesto is None:
            raise ValueError("una evaluación que no es exclusión exige puntaje y niveles")
        if self.puntaje is not None and not 0.0 <= self.puntaje <= 100.0:
            raise ValueError("puntaje fuera de [0, 100]")
        return self


# --------------------------------------------------------------------------- U2: analisis-v1


class RelacionDerivacion(Modelo):
    tipo: Literal["directa", "indirecta", "no_relacionada", "incierta"]
    texto: str


class EntradaLineaTiempo(Modelo):
    fecha: date
    descripcion: str
    ids_registro: list[str] = Field(default_factory=list)


class HallazgoIA(Modelo):
    texto: str
    tipo: Literal["documentado", "inferido"]
    ids_registro: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _documentado_con_ids(self) -> Self:
        if self.tipo == "documentado" and not self.ids_registro:
            raise ValueError("un hallazgo documentado exige al menos un ID de registro")
        return self


class RiesgoPoblacional(Modelo):
    n: int = Field(ge=0)
    k: int = Field(ge=0)
    p: float | None
    ic95_inf: float | None
    ic95_sup: float | None
    advertencia_muestra_pequena: bool
    advertencia_sesgo_acceso: bool


class AcuerdoMotor(Modelo):
    acuerdo: bool
    motivo_discrepancia: str | None = None

    @model_validator(mode="after")
    def _motivo_si_discrepa(self) -> Self:
        if not self.acuerdo and not (self.motivo_discrepancia and self.motivo_discrepancia.strip()):
            raise ValueError("si discrepa del motor, motivo_discrepancia es obligatorio")
        return self


class InconsistenciaDatos(Modelo):
    texto: str
    ids_registro: list[str] = Field(min_length=1)


class MetadatosAnalisis(Modelo):
    model_id: str
    version_prompt: str
    request_id: str | None
    fecha_corte: date
    id_ejecucion: str
    estado: Literal["pendiente_revision_medica", "fallido"] = ESTADO_REVISION_INICIAL


class AnalisisIA(Modelo):
    """Salida estructurada del copiloto (esquema ``analisis-v1``, sección 8.4)."""

    version_esquema: Literal["analisis-v1"] = "analisis-v1"
    id_solicitud: str
    resumen: str = Field(max_length=1200)
    relacion_con_derivacion: RelacionDerivacion
    linea_tiempo_relevante: list[EntradaLineaTiempo] = Field(default_factory=list)
    hallazgos: list[HallazgoIA] = Field(default_factory=list)
    riesgo_poblacional: RiesgoPoblacional | None = None
    prioridad_sugerida: Nivel
    acuerdo_con_motor: AcuerdoMotor
    justificacion: str
    confianza: Confianza
    acciones_sugeridas: list[str] = Field(default_factory=list)
    propuesta_agenda: str | None = None
    datos_faltantes: list[str] = Field(default_factory=list)
    escalas_sustitutas: list[str] = Field(default_factory=list)
    inconsistencias_datos: list[InconsistenciaDatos] = Field(default_factory=list)
    nota_preconsulta: str = Field(max_length=2000)
    metadatos: MetadatosAnalisis


# --------------------------------------------------------------------------- U3: decisión médica


class Decision(Modelo):
    """Decisión del médico contralor sobre una propuesta. Nunca se edita: una nueva es un nuevo registro."""

    id_decision: str
    id_solicitud: str
    fecha_corte: date
    version_reglas: str
    id_analisis: str | None = None
    decision: Literal["aceptada", "ajustada", "rechazada"]
    prioridad_propuesta: Nivel
    prioridad_final: Nivel | None = None
    motivo: str | None = None
    usuario: str = Field(min_length=1)
    timestamp: datetime

    @model_validator(mode="after")
    def _reglas_decision(self) -> Self:
        motivo_ok = bool(self.motivo and self.motivo.strip())
        if self.decision == "aceptada":
            if self.prioridad_final is not None and self.prioridad_final != self.prioridad_propuesta:
                raise ValueError("aceptar implica prioridad_final igual a la propuesta")
        elif self.decision == "ajustada":
            if self.prioridad_final is None:
                raise ValueError("ajustar exige prioridad_final")
            if self.prioridad_final == self.prioridad_propuesta:
                raise ValueError("ajustar exige una prioridad_final distinta de la propuesta")
            if not motivo_ok:
                raise ValueError("ajustar exige motivo")
        elif not motivo_ok:
            raise ValueError("rechazar exige motivo")
        return self
