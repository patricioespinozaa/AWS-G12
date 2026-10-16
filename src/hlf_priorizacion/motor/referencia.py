"""Implementación de referencia, simple y legible, del puntaje y los niveles.

Existe SOLO como oráculo de pruebas (PBT-05): se compara contra ``motor.evaluar``. Está escrita de
forma independiente (sin reutilizar las funciones del motor) para que un error en uno no se copie en
el otro. No se usa en el lote.
"""

from __future__ import annotations

import math
from datetime import date
from statistics import median

from hlf_priorizacion.contrato.catalogos import TipoMedicion
from hlf_priorizacion.modelos import ContextoPaciente, HallazgoDQ
from hlf_priorizacion.motor.parametros import ParametrosReglas

ORDEN = ["baja", "media", "alta", "critica"]
GRAVES = ("visita_urgencia", "hospitalizacion")
MEJORIA = ("buena respuesta", "reducción dosis", "estabilización")
ESPECIALIDADES = {
    "presion_sistolica": ["Cardiología"],
    "presion_diastolica": ["Cardiología"],
    "HbA1c": ["Endocrinología"],
    "glicemia": ["Endocrinología", "Gastroenterología"],
    "saturacion_o2": ["Broncopulmonar"],
    "peak_flow": ["Broncopulmonar"],
    "escala_dolor_eva": ["Traumatología", "Neurología"],
    "PHQ9": ["Salud Mental"],
}


def _redondear(x: float) -> float:
    return round(x, 2) + 0.0


def _fuera(params: ParametrosReglas, tipo: TipoMedicion, valor: float) -> float:
    r = params.mediciones.rangos[tipo]
    sobre = valor - r.maximo if valor > r.maximo else 0.0
    bajo = r.minimo - valor if valor < r.minimo else 0.0
    if r.direccion == "alta":
        return sobre
    if r.direccion == "baja":
        return bajo
    return max(sobre, bajo)


def _sentido(params: ParametrosReglas, tipo: TipoMedicion, valor: float) -> int:
    r = params.mediciones.rangos[tipo]
    if r.direccion == "alta":
        return 1
    if r.direccion == "baja":
        return -1
    centro = (r.minimo + r.maximo) / 2
    return 1 if valor > centro else -1 if valor < centro else 0


def _pendiente(xs: list[float], ys: list[float]) -> float:
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return 0.0 if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den


def puntaje_y_niveles(ctx: ContextoPaciente, dq: list[HallazgoDQ], params: ParametrosReglas) -> tuple[float, str, str]:
    """Devuelve (puntaje, nivel_calculado, nivel_propuesto) para un contexto que no es exclusión."""
    corte: date = ctx.fecha_corte
    fuera = {i for h in dq if h.nivel == "descartar" for i in h.ids_registro}
    eventos = [e for e in ctx.eventos if e.id_evento not in fuera]
    meds = [m for m in ctx.mediciones if m.id_medicion not in fuera]
    inicial = ctx.solicitud.prioridad_inicial

    total = _redondear(getattr(params.base, inicial))
    doc = params.documento_relaciones

    # Eventos con decaimiento y contradicción.
    lam = math.log(2) / params.eventos.vida_media_dias
    mejoria_valida = []
    for e in eventos:
        peso = next(p.peso for p in params.eventos.pesos if p.tipo == e.tipo_evento and p.subtipo == e.subtipo)
        if e.especialidad_evento == ctx.solicitud.especialidad:
            rel = params.eventos.relacion_misma_especialidad
        elif doc is None:
            rel = params.eventos.relacion_otra_especialidad
        else:
            rel = doc.especialidades.por_defecto_otra_especialidad
            for par in doc.especialidades.pares:
                if par.de == e.especialidad_evento and par.a == ctx.solicitud.especialidad:
                    rel = par.factor
        valor = peso * rel * math.exp(-lam * (corte - e.fecha_evento).days)
        if e.subtipo in MEJORIA:
            contradice = False
            for m in meds:
                diferencia = (m.fecha_medicion - e.fecha_evento).days
                if (
                    e.especialidad_evento in ESPECIALIDADES[m.tipo_medicion]
                    and -params.contradiccion.dias_antes <= diferencia <= params.contradiccion.dias_despues
                    and _fuera(params, m.tipo_medicion, float(m.valor)) > 0
                ):
                    contradice = True
            if contradice:
                valor = max(valor, 0.0)
            else:
                mejoria_valida.append(e)
        total += _redondear(valor)

    # Aceleración.
    v = params.aceleracion.ventana_dias
    g_rec = g_prev = 0
    for e in eventos:
        if e.tipo_evento in GRAVES and e.severidad == "grave":
            d = (corte - e.fecha_evento).days
            if 0 <= d < v:
                g_rec += 1
            elif v <= d < 2 * v:
                g_prev += 1
    if g_rec > g_prev:
        total += _redondear(params.aceleracion.aporte)

    # Mediciones con tope.
    pm = params.mediciones
    suma_med = 0.0
    for tipo in pm.rangos:
        serie = sorted([m for m in meds if m.tipo_medicion == tipo], key=lambda m: (m.fecha_medicion, m.id_medicion))
        if not serie:
            continue
        r = pm.rangos[tipo]
        ancho = r.maximo - r.minimo
        ultimo = float(serie[-1].valor)
        dist = _fuera(params, tipo, ultimo)
        if dist > 0:
            suma_med += _redondear(min(pm.zona_maximo, pm.zona_maximo * dist / ancho))
        s = _sentido(params, tipo, ultimo)
        if s != 0 and len(serie) > 1:
            med = median([float(m.valor) for m in serie[:-1]])
            if (ultimo - med) * s > pm.brusco_fraccion_ancho * ancho:
                suma_med += _redondear(pm.brusco_aporte)
        ult = serie[-pm.tendencia_max_puntos :]
        if s != 0 and len(ult) >= pm.tendencia_min_puntos:
            dias = [(m.fecha_medicion - ult[0].fecha_medicion).days for m in ult]
            if dias[-1] >= pm.tendencia_span_min_dias:
                b = _pendiente([float(x) for x in dias], [float(m.valor) for m in ult])
                if b * s * 30 >= pm.tendencia_fraccion_ancho_por_30_dias * ancho:
                    suma_med += _redondear(pm.tendencia_aporte)
    total += _redondear(min(pm.tope, suma_med))

    # Espera.
    plazo = getattr(params.espera.plazos, inicial)
    dias_espera = (corte - ctx.solicitud.fecha_ingreso_lista).days
    total += _redondear(min(params.espera.tope, params.espera.tope * max(0, dias_espera - plazo) / plazo))

    # Otras solicitudes abiertas del mismo paciente (R11), solo si la versión trae documento de relaciones.
    if doc is not None and params.otras_solicitudes is not None:
        propia = ctx.solicitud
        suma_otras = 0.0
        for otra in ctx.otras_solicitudes:
            if otra.fecha_ingreso_lista > corte:
                continue
            atendida = otra.estado_extraccion == "atendido" and (
                corte == ctx.fecha_extraccion
                or any(c.estado_cita == "asistio" and c.especialidad == otra.especialidad for c in ctx.citas)
            )
            if atendida:
                continue
            misma_esp = otra.especialidad == propia.especialidad
            if misma_esp and otra.diagnostico_cie10 == propia.diagnostico_cie10:
                continue
            par_buscado = {propia.diagnostico_cie10, otra.diagnostico_cie10}
            relacion = (
                doc.diagnosticos.por_defecto_misma_especialidad
                if misma_esp
                else doc.diagnosticos.por_defecto_otra_especialidad
            )
            for par_dx in doc.diagnosticos.pares:
                if {par_dx.a, par_dx.b} == par_buscado:
                    relacion = par_dx.factor
            suma_otras += _redondear(getattr(params.otras_solicitudes.pesos, otra.prioridad_inicial) * relacion)
        total += _redondear(min(params.otras_solicitudes.tope, suma_otras))

    puntaje = _redondear(min(100.0, max(0.0, total)))
    calculado = "baja" if puntaje < params.umbrales.media else "media" if puntaje < params.umbrales.alta else "alta"

    # Límite de bajada.
    propuesto = calculado
    if ORDEN.index(calculado) < ORDEN.index(inicial):
        vent = params.ventanas.evidencia_mejoria_dias
        rec = [m for m in meds if 0 <= (corte - m.fecha_medicion).days <= vent]
        ev_ok = [e for e in mejoria_valida if 0 <= (corte - e.fecha_evento).days <= vent]
        todo_en_rango = all(
            params.mediciones.rangos[m.tipo_medicion].minimo
            <= float(m.valor)
            <= params.mediciones.rangos[m.tipo_medicion].maximo
            for m in rec
        )
        if ev_ok and rec and todo_en_rango:
            propuesto = ORDEN[max(ORDEN.index(calculado), ORDEN.index(inicial) - 1)]
        else:
            propuesto = inicial

    # Pisos y banderas.
    vm = params.ventanas.mediciones_banderas_pisos_dias
    recientes = [m for m in meds if 0 <= (corte - m.fecha_medicion).days <= vm]
    if any(regla.tipo == m.tipo_medicion and regla.cumple(float(m.valor)) for regla in params.pisos for m in recientes):
        propuesto = ORDEN[max(ORDEN.index(propuesto), ORDEN.index("alta"))]
    bandera_med = any(
        regla.tipo == m.tipo_medicion and regla.cumple(float(m.valor))
        for regla in params.banderas_medicion
        for m in recientes
    )
    bandera_ev = any(
        e.tipo_evento in GRAVES
        and e.severidad == "grave"
        and 0 <= (corte - e.fecha_evento).days <= params.ventanas.evento_grave_bandera_dias
        for e in eventos
    )
    if bandera_med or bandera_ev:
        propuesto = "critica"
    return puntaje, calculado, propuesto
