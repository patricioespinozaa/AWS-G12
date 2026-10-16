"""Qué se analiza y qué se omite en cada corte (C1, C2.4–C2.6, C5.1). Funciones puras.

Cada solicitud del corte termina en exactamente una decisión: ``pendiente`` (se llamará al modelo) u
``omitida`` con su motivo. El orden de entrada no importa: todo se ordena por ``id_solicitud``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from hlf_priorizacion.copiloto.modelos import MotivoOmision
from hlf_priorizacion.modelos import Evaluacion
from hlf_priorizacion.persistencia.salidas import ruta_propuestas

EstadoDecision = Literal["pendiente", "omitida"]
FirmaEvaluacion = tuple[
    str | None,
    tuple[tuple[str, tuple[str, ...]], ...],
    tuple[tuple[str, tuple[str, ...]], ...],
    frozenset[str],
]


class ErrorTope(ValueError):
    """Las solicitudes pendientes superan ``--max-llamadas`` (C2.5): ni con una invocación cada una alcanza."""

    def __init__(self, pendientes: int, maximo: int) -> None:
        super().__init__(f"hay {pendientes} solicitudes pendientes y el presupuesto es de {maximo} invocaciones")
        self.pendientes = pendientes
        self.maximo = maximo


@dataclass(frozen=True)
class Decision:
    id_solicitud: str
    fecha_corte: date
    estado: EstadoDecision
    evaluacion: Evaluacion
    motivo: MotivoOmision | None = None
    evaluacion_anterior: Evaluacion | None = None
    referencia: str | None = None  # corte del análisis vigente cuando se omite por sin_cambio_en_rango


@dataclass(frozen=True)
class PlanCorte:
    fecha_corte: date
    decisiones: list[Decision] = field(default_factory=list)

    @property
    def pendientes(self) -> list[Decision]:
        return [d for d in self.decisiones if d.estado == "pendiente"]

    @property
    def omitidas(self) -> list[Decision]:
        return [d for d in self.decisiones if d.estado == "omitida"]


@dataclass(frozen=True)
class PlanBarrido:
    cortes: list[PlanCorte]

    @property
    def solicitudes_pendientes(self) -> int:
        return sum(len(c.pendientes) for c in self.cortes)

    def omitidas_por_motivo(self) -> dict[str, int]:
        return dict(sorted(Counter(d.motivo for c in self.cortes for d in c.omitidas if d.motivo).items()))


def ids_citados(ev: Evaluacion) -> frozenset[str]:
    ids: set[str] = set()
    for grupo in (ev.factores, ev.banderas, ev.pisos, ev.alertas_gestion):
        for x in grupo:
            ids.update(x.ids_registro)
    for c in ev.contradicciones:
        ids.add(c.id_evento)
        ids.update(c.ids_medicion)
    return frozenset(ids)


def firma_evaluacion(ev: Evaluacion) -> FirmaEvaluacion:
    """Lo que define "la evaluación cambió" en C2.4: nivel propuesto, banderas, pisos y registros citados."""
    return (
        ev.nivel_propuesto,
        tuple(sorted((b.codigo, tuple(sorted(b.ids_registro))) for b in ev.banderas)),
        tuple(sorted((p.codigo, tuple(sorted(p.ids_registro))) for p in ev.pisos)),
        ids_citados(ev),
    )


def sin_cambio(actual: Evaluacion, anterior: Evaluacion | None) -> bool:
    return (
        anterior is not None
        and anterior.tipo_resultado == "priorizacion"
        and firma_evaluacion(actual) == firma_evaluacion(anterior)
    )


def seleccionar_corte(
    fecha_corte: date,
    propuestas: Iterable[Evaluacion],
    *,
    anteriores: Mapping[str, Evaluacion] | None,
    fecha_anterior: date | None,
    ya_analizadas: set[str],
    forzar: bool,
) -> PlanCorte:
    """Decide cada solicitud de un corte. ``anteriores`` es el corte previo del rango (``None`` fuera de rango)."""
    decisiones: list[Decision] = []
    for ev in sorted(propuestas, key=lambda e: e.id_solicitud):
        sid = ev.id_solicitud
        anterior = anteriores.get(sid) if anteriores is not None else None
        if ev.tipo_resultado != "priorizacion":
            decisiones.append(Decision(sid, fecha_corte, "omitida", ev, motivo=ev.tipo_resultado))
        elif not forzar and sin_cambio(ev, anterior):
            ref = fecha_anterior.isoformat() if fecha_anterior else None
            decisiones.append(Decision(sid, fecha_corte, "omitida", ev, motivo="sin_cambio_en_rango", referencia=ref))
        elif sid in ya_analizadas:
            decisiones.append(Decision(sid, fecha_corte, "omitida", ev, motivo="ya_analizada"))
        else:
            decisiones.append(Decision(sid, fecha_corte, "pendiente", ev, evaluacion_anterior=anterior))
    return PlanCorte(fecha_corte, decisiones)


def planificar(
    propuestas_por_corte: Mapping[date, Iterable[Evaluacion]],
    ya_analizadas_por_corte: Mapping[date, set[str]],
    *,
    modo_rango: bool,
    forzar: bool,
) -> PlanBarrido:
    """Plan de todos los cortes, en orden de fecha. En rango, cada día se compara con el anterior."""
    cortes: list[PlanCorte] = []
    previas: dict[str, Evaluacion] | None = None
    fecha_previa: date | None = None
    for corte in sorted(propuestas_por_corte):
        lista = list(propuestas_por_corte[corte])
        cortes.append(
            seleccionar_corte(
                corte,
                lista,
                anteriores=previas if modo_rango else None,
                fecha_anterior=fecha_previa,
                ya_analizadas=ya_analizadas_por_corte.get(corte, set()),
                forzar=forzar,
            )
        )
        previas = {e.id_solicitud: e for e in lista}
        fecha_previa = corte
    return PlanBarrido(cortes)


def verificar_tope(plan: PlanBarrido, max_llamadas: int) -> None:
    """Aborta antes de llamar solo si las solicitudes pendientes, por sí solas, superan el presupuesto.

    El peor caso (varias invocaciones por solicitud) no aborta: el presupuesto se controla en vivo (C2.5).
    """
    if plan.solicitudes_pendientes > max_llamadas:
        raise ErrorTope(plan.solicitudes_pendientes, max_llamadas)


def marcar_por_tope(plan: PlanBarrido) -> PlanBarrido:
    """Las pendientes pasan a ``limite_llamadas`` (se registran al abortar por el tope, C1.2)."""
    return PlanBarrido(
        [
            PlanCorte(
                c.fecha_corte,
                [
                    Decision(d.id_solicitud, d.fecha_corte, "omitida", d.evaluacion, motivo="limite_llamadas")
                    if d.estado == "pendiente"
                    else d
                    for d in c.decisiones
                ],
            )
            for c in plan.cortes
        ]
    )


def cortes_sin_lote(raiz: Path, cortes: Iterable[date], version_reglas: str) -> list[date]:
    """Cortes sin salida de ``hlf-lote`` para ``version_reglas`` (C2.3)."""
    return [c for c in cortes if not ruta_propuestas(raiz, c, version_reglas).is_file()]


def comandos_lote(
    faltantes: Iterable[date],
    *,
    datos: str | None = None,
    salidas: str | None = None,
    reglas: str | None = None,
) -> list[str]:
    extra = ""
    if datos:
        extra += f' --datos "{datos}"'
    if salidas:
        extra += f' --salidas "{salidas}"'
    if reglas:
        extra += f' --reglas "{reglas}"'
    return [f"uv run hlf-lote --fecha-corte {f.isoformat()}{extra}" for f in faltantes]
