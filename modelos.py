from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, field_validator


class _Base(BaseModel):
    model_config = {"extra": "forbid"}   # un campo desconocido = cambio de contrato, se detecta

    @field_validator("*", mode="before")
    @classmethod
    def vacio_a_none(cls, v):
        return None if v == "" else v     # minutos_atencion_real llega como "" en el JSON


class Paciente(_Base):
    nombre_fantasia: str
    edad: int
    sexo: Literal["F", "M"]
    comuna: str
    prevision: str
    nivel_socioeconomico: str
    fallecido: bool
    fecha_defuncion: Optional[date]


class ListaEspera(_Base):
    id_solicitud: str
    especialidad: str
    sub_especialidad: str
    diagnostico_cie10: str
    diagnostico_texto: str
    prioridad_inicial: Literal["alta", "media", "baja"]
    fecha_ingreso_lista: date
    origen_derivacion: str
    estado: Literal["en_espera", "citado", "atendido", "egresado", "fallecido"]


class Evento(_Base):
    id_evento: str
    fecha_evento: date
    tipo_evento: Literal["cambio_farmaco", "control_aps", "examen_alterado",
                         "hospitalizacion", "visita_urgencia"]
    subtipo: str
    severidad: Literal["leve", "moderada", "grave"]
    detalle: str


class Medicion(_Base):
    fecha_medicion: date
    tipo_medicion: Literal["HbA1c", "PHQ9", "escala_dolor_eva", "glicemia", "peak_flow",
                           "presion_diastolica", "presion_sistolica", "saturacion_o2"]
    valor: float
    unidad: str
    fuera_de_rango: bool


class Cita(_Base):
    id_cita: str
    id_box: str
    fecha_cita: date
    especialidad: str
    estado_cita: Literal["asistio", "no_asistio", "reprogramo", "cancelo"]
    minutos_atencion_real: Optional[int]


class Perfil(_Base):
    id_paciente: str
    paciente: Paciente
    lista_espera: ListaEspera
    eventos_clinicos: list[Evento]
    mediciones: list[Medicion]
    citaciones: list[Cita]