"""Vista "¿Qué cambió?" (B4): comparación de dos cortes. Funciones puras.

Los registros nuevos salen de la línea de tiempo del paciente al ``corte_b`` (inyectada), filtrada a
fecha en ``(corte_a, corte_b]``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from hlf_priorizacion.bandeja.filas import clave_orden, magnitud
from hlf_priorizacion.modelos import Bandera, Evaluacion, Nivel, Piso, RegistroCitado, TipoResultado

LineaTiempo = Callable[[Evaluacion], Sequence[RegistroCitado]]


class CortesInvalidos(ValueError):
    """B4.1: ``corte_a`` debe ser estrictamente anterior a ``corte_b``."""


@dataclass(frozen=True)
class CambioEntreCortes:
    id_solicitud: str
    nivel_a: Nivel | None
    nivel_b: Nivel | None
    puntaje_a: float | None
    puntaje_b: float | None
    tipo_a: TipoResultado | None
    tipo_b: TipoResultado
    registros_nuevos: tuple[str, ...] = ()
    fechas_registros_nuevos: tuple[date, ...] = ()
    banderas_nuevas: tuple[str, ...] = ()
    pisos_nuevos: tuple[str, ...] = ()
    factores_nuevos: tuple[str, ...] = ()
    magnitud_b: int = 0


@dataclass(frozen=True)
class ComparacionCortes:
    corte_a: date
    corte_b: date
    cambios: list[CambioEntreCortes] = field(default_factory=list)
    ingresos_nuevos: list[CambioEntreCortes] = field(default_factory=list)
    a_exclusion: list[CambioEntreCortes] = field(default_factory=list)


def validar_cortes(corte_a: date, corte_b: date) -> None:
    if corte_a >= corte_b:
        raise CortesInvalidos("el corte A debe ser anterior al corte B")


def _codigos(items: Iterable[Bandera | Piso]) -> set[str]:
    return {i.codigo for i in items}


def cambio_relevante(a: Evaluacion, b: Evaluacion) -> bool:
    """B4.2: nivel propuesto, banderas o pisos distintos."""
    return (
        a.nivel_propuesto != b.nivel_propuesto
        or _codigos(a.banderas) != _codigos(b.banderas)
        or _codigos(a.pisos) != _codigos(b.pisos)
    )


def _cambio(
    a: Evaluacion | None, b: Evaluacion, corte_a: date, corte_b: date, linea: LineaTiempo | None
) -> CambioEntreCortes:
    nuevos = sorted(
        ((r.fecha, r.id_registro) for r in (linea(b) if linea is not None else ()) if corte_a < r.fecha <= corte_b),
    )
    factores_a = {(f.factor, tuple(f.ids_registro)) for f in a.factores} if a is not None else set()
    return CambioEntreCortes(
        id_solicitud=b.id_solicitud,
        nivel_a=a.nivel_propuesto if a is not None else None,
        nivel_b=b.nivel_propuesto,
        puntaje_a=a.puntaje if a is not None else None,
        puntaje_b=b.puntaje,
        tipo_a=a.tipo_resultado if a is not None else None,
        tipo_b=b.tipo_resultado,
        registros_nuevos=tuple(i for _, i in nuevos),
        fechas_registros_nuevos=tuple(f for f, _ in nuevos),
        banderas_nuevas=tuple(sorted(_codigos(b.banderas) - (_codigos(a.banderas) if a is not None else set()))),
        pisos_nuevos=tuple(sorted(_codigos(b.pisos) - (_codigos(a.pisos) if a is not None else set()))),
        factores_nuevos=tuple(
            sorted({f.factor for f in b.factores if (f.factor, tuple(f.ids_registro)) not in factores_a})
        ),
        magnitud_b=magnitud(b),
    )


def _ordenar(cambios: Iterable[CambioEntreCortes]) -> list[CambioEntreCortes]:
    """B4.4: igual que la bandeja (B2.2), con el nivel del corte B."""
    return sorted(cambios, key=lambda c: clave_orden(c.nivel_b, c.magnitud_b, c.puntaje_b, c.id_solicitud))


def comparar(
    propuestas_a: Iterable[Evaluacion],
    propuestas_b: Iterable[Evaluacion],
    corte_a: date,
    corte_b: date,
    linea: LineaTiempo | None = None,
) -> ComparacionCortes:
    """Cambios entre cortes. No valida el orden de los cortes (``validar_cortes`` lo hace para la vista)."""
    por_id_a = {ev.id_solicitud: ev for ev in propuestas_a}
    cambios: list[CambioEntreCortes] = []
    ingresos: list[CambioEntreCortes] = []
    exclusion: list[CambioEntreCortes] = []
    for b in propuestas_b:
        a = por_id_a.get(b.id_solicitud)
        if a is None:
            ingresos.append(_cambio(None, b, corte_a, corte_b, linea))
        elif b.tipo_resultado == "exclusion" and a.tipo_resultado != "exclusion":
            exclusion.append(_cambio(a, b, corte_a, corte_b, linea))
        elif cambio_relevante(a, b):
            cambios.append(_cambio(a, b, corte_a, corte_b, linea))
    return ComparacionCortes(corte_a, corte_b, _ordenar(cambios), _ordenar(ingresos), _ordenar(exclusion))
