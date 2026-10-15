"""Contratos Pydantic de petición y respuesta de la API local.

Los tipos de dominio se reutilizan desde ``modelos.py`` (contrato de entrada oficial).
Las respuestas de lista/avisos no exponen previsión, nivel socioeconómico, comuna
ni nombre de fantasía.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from modelos import ListaEspera, Paciente

# Tipos reutilizados de modelos.py
PrioridadInicial = ListaEspera.model_fields["prioridad_inicial"].annotation
EstadoSolicitud = ListaEspera.model_fields["estado"].annotation
Sexo = Paciente.model_fields["sexo"].annotation

Prioridad = Literal["baja", "media", "alta", "critica"]
TipoResultado = Literal["priorizacion", "gestion", "sin_alerta", "exclusion"]
NivelDQ = Literal["descartar", "verificar", "info"]
Fuente = Literal["solicitud", "evento", "medicion", "cita"]
EstadoAviso = Literal["pendiente", "analizado", "decidido"]
OrigenInferencia = Literal["simulada", "real"]


class _Peticion(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Respuesta(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Peticiones
# ---------------------------------------------------------------------------
class SolicitudAnalisis(_Peticion):
    fecha_corte: date
    confirmar_envio_api_real: bool = False


class SolicitudDecision(_Peticion):
    medico_id: str = Field(pattern=r"^[A-Za-z0-9-]{3,32}$")
    decision: Literal["aceptada", "modificada", "rechazada"]
    prioridad_final: Prioridad
    comentario: str = Field(default="", max_length=1000)

    @field_validator("comentario", mode="before")
    @classmethod
    def _recortar(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# Motor de reglas
# ---------------------------------------------------------------------------
class Motivo(_Respuesta):
    puntos: float
    motivo: str
    registro_ids: list[str] = []


class Bandera(_Respuesta):
    bandera: str
    registro_ids: list[str] = []


class AlertaGestion(_Respuesta):
    alerta: str
    registro_ids: list[str] = []


class Inconsistencia(_Respuesta):
    descripcion: str
    registro_ids: list[str] = []


class Evaluacion(_Respuesta):
    alerta_id: str
    id_paciente: str
    id_solicitud: str
    especialidad: str
    cie10: str
    prioridad_inicial: PrioridadInicial  # type: ignore[valid-type]
    fecha_corte: date
    tipo: TipoResultado
    score: Optional[float] = None
    prioridad_calculada: Optional[Prioridad] = None
    dias_en_espera: Optional[int] = None
    motivos: list[Motivo] = []
    banderas_rojas: list[Bandera] = []
    alertas_gestion: list[AlertaGestion] = []
    inconsistencias: list[Inconsistencia] = []
    motivo_exclusion: Optional[Literal["fallecido", "ya_atendido"]] = Field(
        default=None, validation_alias=AliasChoices("motivo", "motivo_exclusion"))
    fecha_defuncion: Optional[date] = None


class ItemLista(_Respuesta):
    alerta_id: str
    id_paciente: str
    id_solicitud: str
    especialidad: str
    cie10: str
    prioridad_inicial: PrioridadInicial  # type: ignore[valid-type]
    fecha_corte: date
    tipo: TipoResultado
    score: Optional[float] = None
    prioridad_calculada: Optional[Prioridad] = None
    dias_en_espera: Optional[int] = None
    banderas_rojas: list[Bandera] = []
    alertas_gestion: list[AlertaGestion] = []
    inconsistencias: list[Inconsistencia] = []
    estado_aviso: EstadoAviso


class RespuestaLista(_Respuesta):
    fecha_corte: date
    items: list[ItemLista]
    excluidos: list[Evaluacion]
    n_sin_solicitud_a_la_fecha: int


# ---------------------------------------------------------------------------
# Paciente y cronología
# ---------------------------------------------------------------------------
class PerfilMinimo(_Respuesta):
    id_paciente: str
    edad: int
    sexo: Optional[Sexo] = None  # type: ignore[valid-type]


class SolicitudLinea(_Respuesta):
    registro_id: str
    especialidad: Optional[str] = None
    sub_especialidad: Optional[str] = None
    cie10: Optional[str] = None
    diagnostico: Optional[str] = None
    prioridad_inicial: Optional[str] = None
    fecha_ingreso: Optional[date] = None
    dias_en_espera: int
    origen: Optional[str] = None
    estado: Optional[str] = None
    estado_reconstruible: bool


class EventoLinea(_Respuesta):
    fecha: Optional[date] = None
    registro_id: str
    fuente: Fuente
    tipo: Optional[str] = None
    subtipo: Optional[str] = None
    severidad: Optional[str] = None
    detalle: Optional[str] = None
    especialidad_asociada: Optional[str] = None
    valor: Optional[float] = None
    unidad: Optional[str] = None
    fuera_de_rango: Optional[bool] = None
    especialidad: Optional[str] = None
    estado: Optional[str] = None
    id_box: Optional[str] = None


class HallazgoDQ(_Respuesta):
    codigo: str
    nivel: NivelDQ
    id_paciente: str
    descripcion: str
    registro_ids: list[str] = []


class RefEvidencia(_Respuesta):
    registro_id: str
    fuente: Fuente
    fecha: Optional[date] = None
    origen: str


# ---------------------------------------------------------------------------
# Copiloto (salida del modelo: campos opcionales y tolerantes)
# ---------------------------------------------------------------------------
class _SalidaModelo(BaseModel):
    model_config = ConfigDict(extra="allow")


class Verificacion(_SalidaModelo):
    campos_faltantes: list[str] = []
    citas_verificadas: Optional[bool] = None
    citas_no_verificables: Optional[list[str]] = None
    documentados_sin_cita: list[str] = []
    discrepancias_motor: list[str] = []
    requiere_atencion: Optional[bool] = None


class MetaAnalisis(_SalidaModelo):
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    modo: Optional[str] = None
    turnos: Optional[int] = None
    fecha_corte: Optional[str] = None
    estado: Optional[str] = None
    verificacion: Optional[Verificacion] = None


class HallazgoIA(_SalidaModelo):
    hallazgo: Optional[str] = None
    tipo: Optional[str] = None
    registro_ids: list[str] = []


class ItemLineaIA(_SalidaModelo):
    fecha: Optional[str] = None
    descripcion: Optional[str] = None
    registro_id: Optional[str] = None


class InconsistenciaIA(_SalidaModelo):
    descripcion: Optional[str] = None
    registro_ids: list[str] = []


class AnalisisCopiloto(_SalidaModelo):
    resumen: Optional[str] = None
    relacion_con_derivacion: Optional[str] = None
    linea_tiempo_relevante: list[ItemLineaIA] = []
    hallazgos: list[HallazgoIA] = []
    riesgo_poblacional: Optional[str] = None
    prioridad_sugerida: Optional[str] = None
    acuerdo_con_motor_reglas: Optional[bool] = None
    justificacion: Optional[str] = None
    confianza: Optional[str] = None
    acciones_sugeridas: list[str] = []
    propuesta_agenda: Optional[str] = None
    datos_faltantes: list[str] = []
    inconsistencias_datos: list[InconsistenciaIA] = []
    nota_preconsulta: Optional[str] = None
    meta: Optional[MetaAnalisis] = Field(default=None,
                                         validation_alias=AliasChoices("_meta", "meta"),
                                         serialization_alias="meta")


class RespuestaAnalisis(_Respuesta):
    alerta_id: str
    origen_inferencia: OrigenInferencia
    analisis: AnalisisCopiloto
    evidencia: dict[str, RefEvidencia]


# ---------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------
class AnalisisPrevio(_Respuesta):
    timestamp: Optional[str] = None
    origen_inferencia: OrigenInferencia
    prioridad_sugerida: Optional[str] = None
    resumen: Optional[str] = None


class DecisionPrevia(_Respuesta):
    timestamp: Optional[str] = None
    medico_id: Optional[str] = None
    decision: Optional[str] = None
    prioridad_final: Optional[str] = None
    comentario: Optional[str] = None


class HistorialAviso(_Respuesta):
    alerta_id: str
    estado_aviso: EstadoAviso
    analisis: list[AnalisisPrevio]
    decisiones: list[DecisionPrevia]
    ultimo_analisis: Optional[AnalisisCopiloto] = None
    origen_ultimo_analisis: Optional[OrigenInferencia] = None
    lineas_invalidas: int = 0


class RespuestaPaciente(_Respuesta):
    fecha_corte: date
    perfil: PerfilMinimo
    solicitud: SolicitudLinea
    eventos: list[EventoLinea]
    evaluacion: Evaluacion
    calidad: list[HallazgoDQ]
    evidencia: dict[str, RefEvidencia]
    historial: HistorialAviso


class RespuestaDecision(_Respuesta):
    registrada: bool
    alerta_id: str
    nota: str


# ---------------------------------------------------------------------------
# Calidad y estado
# ---------------------------------------------------------------------------
class ResumenDQ(_Respuesta):
    codigo: str
    nivel: NivelDQ
    n: int


class ItemCuarentena(_Respuesta):
    posicion: int
    id_paciente: Optional[str] = None
    n_errores: int


class RespuestaCalidad(_Respuesta):
    fecha_corte: date
    hallazgos: list[HallazgoDQ]
    resumen: list[ResumenDQ]
    cuarentena: list[ItemCuarentena]
    nota: str


class EstadoServidor(_Respuesta):
    modo_inferencia: OrigenInferencia
    requiere_confirmacion_envio: bool
    fecha_referencia: date
    fecha_corte_min: date
    fecha_corte_max: date
    advertencia: str
    perfiles_validos: int
    perfiles_en_cuarentena: int
    fuente_datos: str
