"""Filas de la bandeja (B2): indicadores, orden determinista y filtros. Funciones puras."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from hlf_priorizacion.bandeja.datos import EstadoAnalisis
from hlf_priorizacion.modelos import ORDEN_NIVEL, Evaluacion, Nivel, TipoResultado

EstadoDecision = Literal["pendiente", "aceptada", "ajustada", "rechazada"]
ESTADOS_DECISION: Final[tuple[EstadoDecision, ...]] = ("pendiente", "aceptada", "ajustada", "rechazada")
TIPOS_POR_DEFECTO: Final[frozenset[TipoResultado]] = frozenset({"priorizacion", "gestion", "exclusion"})
TIPOS_RESULTADO: Final[tuple[TipoResultado, ...]] = ("priorizacion", "gestion", "exclusion", "sin_alerta")


@dataclass(frozen=True)
class FilaBandeja:
    id_solicitud: str
    especialidad: str
    prioridad_inicial: Nivel
    nivel_propuesto: Nivel | None
    magnitud: int  # nivel propuesto - prioridad inicial (0 en exclusiones)
    puntaje: float | None
    tipo_resultado: TipoResultado
    banderas: tuple[str, ...]
    analisis: EstadoAnalisis
    revision_equidad: bool
    estado_decision: EstadoDecision

    @property
    def tiene_analisis(self) -> bool:
        return self.analisis == "si"

    @property
    def bandera_roja(self) -> bool:
        return bool(self.banderas)


def magnitud(ev: Evaluacion) -> int:
    return 0 if ev.nivel_propuesto is None else ORDEN_NIVEL[ev.nivel_propuesto] - ORDEN_NIVEL[ev.prioridad_inicial]


def construir_filas(
    propuestas: Iterable[Evaluacion],
    especialidades: Mapping[str, str],
    estado_analisis: Mapping[str, EstadoAnalisis],
    con_equidad: Iterable[str],
    estados_decision: Mapping[str, EstadoDecision],
) -> list[FilaBandeja]:
    equidad = set(con_equidad)
    return [
        FilaBandeja(
            id_solicitud=ev.id_solicitud,
            especialidad=especialidades.get(ev.id_solicitud, ""),
            prioridad_inicial=ev.prioridad_inicial,
            nivel_propuesto=ev.nivel_propuesto,
            magnitud=magnitud(ev),
            puntaje=ev.puntaje,
            tipo_resultado=ev.tipo_resultado,
            banderas=tuple(b.codigo for b in ev.banderas),
            analisis=estado_analisis.get(ev.id_solicitud, "no"),
            revision_equidad=ev.id_solicitud in equidad,
            estado_decision=estados_decision.get(ev.id_solicitud, "pendiente"),
        )
        for ev in propuestas
    ]


def clave_orden(
    nivel: Nivel | None, magnitud_cambio: int, puntaje: float | None, id_solicitud: str
) -> tuple[int, int, int, float, str]:
    """B2.2: crítica primero; magnitud del cambio descendente (subida antes que bajada); puntaje desc.; ID."""
    return (
        0 if nivel == "critica" else 1,
        -abs(magnitud_cambio),
        0 if magnitud_cambio > 0 else 1,
        -puntaje if puntaje is not None else float("inf"),
        id_solicitud,
    )


def ordenar(filas: Iterable[FilaBandeja]) -> list[FilaBandeja]:
    return sorted(filas, key=lambda f: clave_orden(f.nivel_propuesto, f.magnitud, f.puntaje, f.id_solicitud))


@dataclass(frozen=True)
class Filtros:
    """B2.3. Un conjunto vacío no filtra. Sin ``tipos`` se usan los por defecto (B2.1) más, si se pide, sin_alerta."""

    especialidades: frozenset[str] = frozenset()
    niveles: frozenset[Nivel] = frozenset()
    tipos: frozenset[TipoResultado] = frozenset()
    incluir_sin_alerta: bool = False
    solo_con_analisis: bool = False
    solo_con_equidad: bool = False
    estados_decision: frozenset[EstadoDecision] = frozenset()

    def tipos_efectivos(self) -> frozenset[TipoResultado]:
        if self.tipos:
            return self.tipos
        return TIPOS_POR_DEFECTO | {"sin_alerta"} if self.incluir_sin_alerta else TIPOS_POR_DEFECTO

    def acepta(self, f: FilaBandeja) -> bool:
        return (
            f.tipo_resultado in self.tipos_efectivos()
            and (not self.especialidades or f.especialidad in self.especialidades)
            and (not self.niveles or f.nivel_propuesto in self.niveles)
            and (not self.solo_con_analisis or f.tiene_analisis)
            and (not self.solo_con_equidad or f.revision_equidad)
            and (not self.estados_decision or f.estado_decision in self.estados_decision)
        )


def filtrar(filas: Sequence[FilaBandeja], filtros: Filtros) -> list[FilaBandeja]:
    """Subconjunto en el mismo orden de entrada."""
    return [f for f in filas if filtros.acepta(f)]


def contador(filas: Sequence[FilaBandeja]) -> tuple[int, int, int]:
    """``(solicitudes, críticas, con análisis)`` para el texto "N solicitudes · M críticas · K con análisis"."""
    return (
        len(filas),
        sum(1 for f in filas if f.nivel_propuesto == "critica"),
        sum(1 for f in filas if f.tiene_analisis),
    )
