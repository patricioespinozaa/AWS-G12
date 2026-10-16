"""``auditar(ctx)``: hallazgos de calidad de datos sobre un contexto (R4, sección 7).

Lo marcado ``descartar`` se quita antes del puntaje; ``verificar`` baja la confianza; ``info`` se informa.
Función pura sobre el contexto.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from hlf_priorizacion.calidad.reglas import (
    DQ_ASISTIO_EN_ESPERA,
    DQ_ESPECIALIDAD_INFERIDA,
    DQ_FUERA_PLAUSIBILIDAD,
    DQ_FUERA_RANGO_INCONSISTENTE,
    DQ_POSTERIOR_DEFUNCION,
    DQ_PREVIO_INGRESO,
    DQ_REPETIDA_IMPLAUSIBLE,
    FRACCION_REPETIDA_MISMO_DIA,
    RANGOS_NORMALES_ORIGEN,
    es_plausible,
    fuera_de_rango_origen_esperado,
)
from hlf_priorizacion.modelos import ContextoPaciente, HallazgoDQ, RegistroMedicion


def _registros_con_fecha(ctx: ContextoPaciente) -> list[tuple[str, date]]:
    return (
        [(e.id_evento, e.fecha_evento) for e in ctx.eventos]
        + [(m.id_medicion, m.fecha_medicion) for m in ctx.mediciones]
        + [(c.id_cita, c.fecha_cita) for c in ctx.citas]
    )


def auditar(ctx: ContextoPaciente) -> list[HallazgoDQ]:
    hallazgos: list[HallazgoDQ] = []

    implausibles = sorted(m.id_medicion for m in ctx.mediciones if not es_plausible(m.tipo_medicion, m.valor))
    if implausibles:
        hallazgos.append(
            HallazgoDQ(
                codigo=DQ_FUERA_PLAUSIBILIDAD,
                nivel="descartar",
                ids_registro=implausibles,
                detalle="medición fuera de los límites de plausibilidad",
            )
        )
    descartadas = set(implausibles)

    if ctx.fecha_defuncion is not None:
        posteriores = sorted(i for i, f in _registros_con_fecha(ctx) if f > ctx.fecha_defuncion)
        if posteriores:
            hallazgos.append(
                HallazgoDQ(
                    codigo=DQ_POSTERIOR_DEFUNCION,
                    nivel="descartar",
                    ids_registro=posteriores,
                    detalle="registro posterior a la fecha de defunción",
                )
            )
            descartadas.update(posteriores)

    validas = [m for m in ctx.mediciones if m.id_medicion not in descartadas]

    por_dia: dict[tuple[str, date], list[RegistroMedicion]] = defaultdict(list)
    for m in validas:
        por_dia[(m.tipo_medicion, m.fecha_medicion)].append(m)
    for (tipo, _fecha), grupo in sorted(por_dia.items()):
        if len(grupo) < 2:
            continue
        inf, sup = RANGOS_NORMALES_ORIGEN[tipo]
        valores = [m.valor for m in grupo]
        if max(valores) - min(valores) > FRACCION_REPETIDA_MISMO_DIA * (sup - inf):
            hallazgos.append(
                HallazgoDQ(
                    codigo=DQ_REPETIDA_IMPLAUSIBLE,
                    nivel="verificar",
                    ids_registro=sorted(m.id_medicion for m in grupo),
                    detalle=f"{tipo}: valores incompatibles el mismo día",
                )
            )

    inconsistentes = sorted(
        m.id_medicion
        for m in validas
        if m.fuera_de_rango_origen != fuera_de_rango_origen_esperado(m.tipo_medicion, m.valor)
    )
    if inconsistentes:
        hallazgos.append(
            HallazgoDQ(
                codigo=DQ_FUERA_RANGO_INCONSISTENTE,
                nivel="verificar",
                ids_registro=inconsistentes,
                detalle="fuera_de_rango de origen no coincide con el rango de referencia; el motor usa su cálculo",
            )
        )

    previos = sorted(i for i, f in _registros_con_fecha(ctx) if f < ctx.solicitud.fecha_ingreso_lista)
    if previos:
        hallazgos.append(
            HallazgoDQ(
                codigo=DQ_PREVIO_INGRESO,
                nivel="info",
                ids_registro=previos,
                detalle="registro anterior a fecha_ingreso_lista (antecedente)",
            )
        )

    if ctx.solicitud.estado_a_la_fecha == "en_espera":
        asistidas = sorted(
            c.id_cita for c in ctx.citas if c.estado_cita == "asistio" and c.especialidad == ctx.solicitud.especialidad
        )
        if asistidas:
            hallazgos.append(
                HallazgoDQ(
                    codigo=DQ_ASISTIO_EN_ESPERA,
                    nivel="verificar",
                    ids_registro=asistidas,
                    detalle="asistió a la especialidad pero sigue en_espera",
                )
            )

    inferidas = sorted(e.id_evento for e in ctx.eventos if e.especialidad_inferida)
    if inferidas:
        hallazgos.append(
            HallazgoDQ(
                codigo=DQ_ESPECIALIDAD_INFERIDA,
                nivel="info",
                ids_registro=inferidas,
                detalle="especialidad del evento no legible en detalle; se asume la de la solicitud",
            )
        )
    return hallazgos


def ids_descartados(hallazgos: list[HallazgoDQ]) -> set[str]:
    return {i for h in hallazgos if h.nivel == "descartar" for i in h.ids_registro}
