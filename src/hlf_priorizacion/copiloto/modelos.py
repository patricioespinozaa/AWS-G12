"""Entidades propias de U2 (``domain-entities.md``).

``AnalisisIA``, ``Evaluacion`` y ``ContextoPaciente`` vienen de U1 (``hlf_priorizacion.modelos``).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from hlf_priorizacion.modelos import (
    AnalisisIA,
    ContextoPaciente,
    Evaluacion,
    HallazgoDQ,
    Modelo,
    ResultadoCohorte,
)

MotivoOmision = Literal[
    "exclusion",
    "gestion",
    "sin_alerta",
    "sin_cambio_en_rango",
    "ya_analizada",
    "limite_llamadas",
    "interrumpido",
]
MOTIVOS_OMISION: tuple[MotivoOmision, ...] = (
    "exclusion",
    "gestion",
    "sin_alerta",
    "sin_cambio_en_rango",
    "ya_analizada",
    "limite_llamadas",
    "interrumpido",
)


class PaqueteBarrido(Modelo):
    """Todo lo que el modelo recibe de una solicitud (C3). Sin comuna, previsión, NSE ni nombre."""

    id_solicitud: str
    fecha_corte: date
    version_reglas: str
    contexto: ContextoPaciente
    evaluacion: Evaluacion
    evaluacion_anterior: Evaluacion | None = None
    hallazgos_dq: list[HallazgoDQ] = Field(default_factory=list)
    cohorte: ResultadoCohorte | None = None

    def ids_paquete(self) -> set[str]:
        """IDs que el modelo puede citar: los del contexto entregado."""
        return self.contexto.ids_presentes()


class Correccion(Modelo):
    """Cambio que hizo el validador sobre la salida del modelo (C6.2, C6.3)."""

    tipo: Literal[
        "hallazgo_a_inferido",
        "id_eliminado",
        "inconsistencia_eliminada",
        "riesgo_poblacional_reemplazado",
        "revision_equidad",
    ]
    campo: str
    detalle: str


class FraseRevisionEquidad(Modelo):
    """Oración que junta inasistencias con un verbo de bajada (C6.5 regla 2). Marca del sistema, no del modelo."""

    campo: str
    texto: str


class UsoModelo(Modelo):
    tokens_entrada: int = Field(ge=0)
    tokens_salida: int = Field(ge=0)
    latencia_ms: int = Field(ge=0)


class RegistroAnalisis(Modelo):
    """Línea de ``analisis.jsonl``: el análisis validado más su trazabilidad."""

    id_analisis: str
    id_solicitud: str
    fecha_corte: date
    version_reglas: str
    version_prompt: str
    huella_prompt: str
    model_id: str
    temperatura_enviada: float | None  # None: el modelo no acepta temperatura (decisión T-1)
    intentos: int = Field(ge=1)
    correcciones: list[Correccion] = Field(default_factory=list)
    huella_paquete: str
    huella_salida: str
    uso: UsoModelo
    analisis: AnalisisIA
    # C6.5 regla 2 (decisión E-1 = C): metadato del sistema, fuera de los campos que escribe el modelo. U3
    # muestra una advertencia si no está vacía. Los análisis guardados antes de v1.2.0 no lo traen: lista vacía.
    revision_equidad: list[FraseRevisionEquidad] = Field(default_factory=list)


class AnalisisFallido(Modelo):
    """Línea de ``fallidos.jsonl``. La propuesta del motor sigue válida sin análisis IA."""

    id_solicitud: str
    fecha_corte: date
    version_reglas: str
    version_prompt: str
    model_id: str
    id_ejecucion: str
    motivo: str
    intentos: int = Field(ge=0)
