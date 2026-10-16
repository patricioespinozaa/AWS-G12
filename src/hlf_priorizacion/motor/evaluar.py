"""Motor de reglas determinista: ``evaluar(ctx, dq, params) -> Evaluacion``.

Función pura: no lee archivos, no consulta el reloj y no usa aleatoriedad. Todo lo que necesita
llega en sus argumentos. Reglas R3, R5-R8 de ``business-rules.md``; algoritmo de
``business-logic-model.md``.

Orden: exclusión -> quitar descartados -> factores (base, eventos, aceleración, mediciones con tope,
espera) -> acotar -> nivel calculado -> límite de bajada -> pisos -> banderas -> alertas -> tipo y confianza.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from hlf_priorizacion.calidad.auditoria import ids_descartados
from hlf_priorizacion.contrato.catalogos import (
    ESPECIALIDADES_POR_MEDICION,
    SUBTIPOS_MEJORIA,
    TIPOS_MEDICION,
    es_evento_grave,
)
from hlf_priorizacion.ingesta.conciliacion import CODIGO_CONCILIACION
from hlf_priorizacion.ingesta.normalizacion import normalizar_valor
from hlf_priorizacion.modelos import (
    NIVELES,
    ORDEN_NIVEL,
    AlertaGestion,
    Bandera,
    Confianza,
    ContextoPaciente,
    Contradiccion,
    Evaluacion,
    Factor,
    HallazgoDQ,
    MarcaInferido,
    Nivel,
    Piso,
    RegistroCita,
    RegistroEvento,
    RegistroMedicion,
    TipoResultado,
)
from hlf_priorizacion.motor.parametros import ParametrosReglas, RangoMedicion, ReglaUmbral

# Códigos de exclusión (R3) y de alertas de gestión (R7).
EX_FALLECIDO = "EX_FALLECIDO"
EX_ATENDIDO = "EX_ATENDIDO"
EX_ATENDIDO_INFERIDO = "EX_ATENDIDO_INFERIDO"
BR_EVENTO_GRAVE_30D = "BR_EVENTO_GRAVE_30D"
BR_PHQ9_ALTO = "BR_PHQ9_ALTO"

ACCIONES_ALERTA = {
    "citas_fallidas": "Contactar y evaluar barreras de acceso",
    "limite_inasistencias": "Proponer salida de la lista; la decide el gestor",
    "silencio_clinico": "Verificar vigencia y contactar",
    "estado_inconsistente": "Verificación administrativa",
    "fallecido_en_lista": "Egreso administrativo",
}
ESTADOS_FALLIDOS = frozenset({"no_asistio", "reprogramo", "cancelo"})


# --------------------------------------------------------------------------- utilidades de medición


def direccion_danina(rango: RangoMedicion, ultimo: float) -> int:
    """+1 si lo dañino es subir, -1 si es bajar, 0 si no hay dirección (bidireccional en el centro)."""
    if rango.direccion == "alta":
        return 1
    if rango.direccion == "baja":
        return -1
    if ultimo > rango.medio:
        return 1
    if ultimo < rango.medio:
        return -1
    return 0


def distancia_danina(rango: RangoMedicion, valor: float) -> float:
    """Distancia al rango normal en la dirección dañina (0 si está en rango)."""
    arriba = max(0.0, valor - rango.maximo)
    abajo = max(0.0, rango.minimo - valor)
    if rango.direccion == "alta":
        return arriba
    if rango.direccion == "baja":
        return abajo
    return max(arriba, abajo)


def en_rango(rango: RangoMedicion, valor: float) -> bool:
    return rango.minimo <= valor <= rango.maximo


def pendiente(puntos: Sequence[tuple[float, float]]) -> float:
    """Pendiente de la regresión lineal simple (mínimos cuadrados)."""
    n = len(puntos)
    mx = sum(x for x, _ in puntos) / n
    my = sum(y for _, y in puntos) / n
    sxx = sum((x - mx) ** 2 for x, _ in puntos)
    if sxx == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in puntos) / sxx


def _dias(corte: date, fecha: date) -> int:
    return (corte - fecha).days


def _r2(x: float) -> float:
    return round(x, 2) + 0.0  # + 0.0 evita "-0.0" en la salida


# --------------------------------------------------------------------------- piezas del cálculo


@dataclass(frozen=True)
class _Eventos:
    factores: list[Factor]
    contradicciones: list[Contradiccion]
    mejoria_sin_contradiccion: list[RegistroEvento]


def _medicion_en_riesgo(m: RegistroMedicion, params: ParametrosReglas) -> bool:
    return distancia_danina(params.mediciones.rangos[m.tipo_medicion], float(m.valor)) > 0


def _factores_eventos(
    ctx: ContextoPaciente, eventos: list[RegistroEvento], mediciones: list[RegistroMedicion], params: ParametrosReglas
) -> _Eventos:
    pe = params.eventos
    corte = ctx.fecha_corte
    factores: list[Factor] = []
    contradicciones: list[Contradiccion] = []
    mejoria_ok: list[RegistroEvento] = []
    for e in eventos:
        dt = _dias(corte, e.fecha_evento)
        w = pe.peso(e.tipo_evento, e.subtipo)
        misma = e.especialidad_evento == ctx.solicitud.especialidad
        r = pe.relacion_misma_especialidad if misma else pe.relacion_otra_especialidad
        aporte = w * r * math.exp(-pe.lambda_decaimiento * dt)
        detalle = f"{e.tipo_evento}: {e.subtipo}, hace {dt} días"
        if not misma:
            detalle += f" (otra especialidad: {e.especialidad_evento})"
        if e.subtipo in SUBTIPOS_MEJORIA:
            en_riesgo = sorted(
                m.id_medicion
                for m in mediciones
                if e.especialidad_evento in ESPECIALIDADES_POR_MEDICION[m.tipo_medicion]
                and -params.contradiccion.dias_antes
                <= (m.fecha_medicion - e.fecha_evento).days
                <= params.contradiccion.dias_despues
                and _medicion_en_riesgo(m, params)
            )
            if en_riesgo:
                contradicciones.append(
                    Contradiccion(
                        id_evento=e.id_evento,
                        ids_medicion=en_riesgo,
                        pregunta_clinica=(
                            f"¿Es compatible '{e.subtipo}' del {e.fecha_evento.isoformat()} con "
                            f"{len(en_riesgo)} medición(es) en zona de riesgo cercanas al evento?"
                        ),
                    )
                )
                if aporte < 0:
                    aporte = 0.0
                    detalle += " (aporte anulado por contradicción)"
            else:
                mejoria_ok.append(e)
        factores.append(Factor(factor="evento", detalle=detalle, aporte=_r2(aporte), ids_registro=[e.id_evento]))
    return _Eventos(factores, contradicciones, mejoria_ok)


def _factor_aceleracion(
    ctx: ContextoPaciente, eventos: list[RegistroEvento], params: ParametrosReglas
) -> Factor | None:
    v = params.aceleracion.ventana_dias
    graves = [e for e in eventos if es_evento_grave(e.tipo_evento, e.severidad)]
    recientes = [e for e in graves if 0 <= _dias(ctx.fecha_corte, e.fecha_evento) < v]
    previos = [e for e in graves if v <= _dias(ctx.fecha_corte, e.fecha_evento) < 2 * v]
    if len(recientes) <= len(previos):
        return None
    return Factor(
        factor="aceleracion",
        detalle=f"{len(recientes)} eventos graves en {v} días frente a {len(previos)} en los {v} previos",
        aporte=_r2(params.aceleracion.aporte),
        ids_registro=sorted(e.id_evento for e in recientes + previos),
    )


def _factores_mediciones(mediciones: list[RegistroMedicion], params: ParametrosReglas) -> list[Factor]:
    pm = params.mediciones
    brutos: list[Factor] = []
    for tipo in TIPOS_MEDICION:
        serie = sorted(
            (m for m in mediciones if m.tipo_medicion == tipo), key=lambda m: (m.fecha_medicion, m.id_medicion)
        )
        if not serie:
            continue
        rango = pm.rangos[tipo]
        ultimo = serie[-1]
        v = float(ultimo.valor)
        texto_valor = f"{tipo} {normalizar_valor(ultimo.valor)} {ultimo.unidad}"
        dist = distancia_danina(rango, v)
        if dist > 0:
            brutos.append(
                Factor(
                    factor="medicion_zona",
                    detalle=f"{texto_valor} fuera del rango {rango.minimo:g}-{rango.maximo:g}",
                    aporte=_r2(min(pm.zona_maximo, pm.zona_maximo * dist / rango.ancho)),
                    ids_registro=[ultimo.id_medicion],
                )
            )
        d = direccion_danina(rango, v)
        previos = serie[:-1]
        if previos and d != 0:
            mediana = statistics.median(float(m.valor) for m in previos)
            if (v - mediana) * d > pm.brusco_fraccion_ancho * rango.ancho:
                brutos.append(
                    Factor(
                        factor="medicion_brusco",
                        detalle=f"{texto_valor} se aleja de la mediana previa ({mediana:g}) en la dirección dañina",
                        aporte=_r2(pm.brusco_aporte),
                        ids_registro=[ultimo.id_medicion, *(m.id_medicion for m in previos)],
                    )
                )
        puntos = serie[-pm.tendencia_max_puntos :]
        if (
            d != 0
            and len(puntos) >= pm.tendencia_min_puntos
            and (puntos[-1].fecha_medicion - puntos[0].fecha_medicion).days >= pm.tendencia_span_min_dias
        ):
            origen = puntos[0].fecha_medicion
            b = pendiente([((m.fecha_medicion - origen).days, float(m.valor)) for m in puntos])
            if b * d * 30 >= pm.tendencia_fraccion_ancho_por_30_dias * rango.ancho:
                brutos.append(
                    Factor(
                        factor="medicion_tendencia",
                        detalle=(
                            f"{tipo}: tendencia en la dirección dañina en las últimas {len(puntos)} mediciones "
                            f"({b * 30:+.2f} {ultimo.unidad} cada 30 días)"
                        ),
                        aporte=_r2(pm.tendencia_aporte),
                        ids_registro=[m.id_medicion for m in puntos],
                    )
                )
    # Tope de mediciones por solicitud: se recortan los últimos factores hasta cumplirlo.
    restante = pm.tope
    factores: list[Factor] = []
    for f in brutos:
        aporte = _r2(min(f.aporte, max(0.0, restante)))
        restante -= aporte
        if aporte < f.aporte:
            f = f.model_copy(update={"aporte": aporte, "detalle": f.detalle + f" (acotado por el tope de {pm.tope:g})"})
        factores.append(f)
    return factores


def _factor_espera(ctx: ContextoPaciente, params: ParametrosReglas) -> Factor:
    dias = _dias(ctx.fecha_corte, ctx.solicitud.fecha_ingreso_lista)
    plazo = getattr(params.espera.plazos, ctx.solicitud.prioridad_inicial)
    tope = params.espera.tope
    aporte = min(tope, tope * max(0, dias - plazo) / plazo)
    return Factor(
        factor="espera",
        detalle=f"{dias} días, plazo referencial {plazo}",
        aporte=_r2(aporte),
        ids_registro=[ctx.id_solicitud],
    )


def nivel_por_puntaje(puntaje: float, params: ParametrosReglas) -> Nivel:
    if puntaje < params.umbrales.media:
        return "baja"
    if puntaje < params.umbrales.alta:
        return "media"
    return "alta"


def _en_ventana(corte: date, fecha: date, dias: int) -> bool:
    return 0 <= _dias(corte, fecha) <= dias


def _pisos_y_banderas(
    ctx: ContextoPaciente, eventos: list[RegistroEvento], mediciones: list[RegistroMedicion], params: ParametrosReglas
) -> tuple[list[Piso], list[Bandera]]:
    corte = ctx.fecha_corte
    vm = params.ventanas.mediciones_banderas_pisos_dias
    recientes = [m for m in mediciones if _en_ventana(corte, m.fecha_medicion, vm)]

    def disparan(regla: ReglaUmbral) -> list[str]:
        return sorted(
            m.id_medicion for m in recientes if m.tipo_medicion == regla.tipo and regla.cumple(float(m.valor))
        )

    pisos = []
    for regla in params.pisos:
        ids = disparan(regla)
        if ids:
            pisos.append(Piso(codigo=regla.codigo, ids_registro=ids))
    banderas = []
    for regla in params.banderas_medicion:
        ids = disparan(regla)
        if ids:
            banderas.append(Bandera(codigo=regla.codigo, ids_registro=ids))
    graves = sorted(
        e.id_evento
        for e in eventos
        if es_evento_grave(e.tipo_evento, e.severidad)
        and _en_ventana(corte, e.fecha_evento, params.ventanas.evento_grave_bandera_dias)
    )
    if graves:
        banderas.append(Bandera(codigo=BR_EVENTO_GRAVE_30D, ids_registro=graves))
    return pisos, banderas


def _limitar_bajada(
    calculado: Nivel,
    inicial: Nivel,
    ctx: ContextoPaciente,
    mejoria_ok: list[RegistroEvento],
    mediciones: list[RegistroMedicion],
    params: ParametrosReglas,
) -> Nivel:
    """R6.5: nunca más de un nivel bajo la inicial; bajar exige evidencia de mejoría."""
    if ORDEN_NIVEL[calculado] >= ORDEN_NIVEL[inicial]:
        return calculado
    ventana = params.ventanas.evidencia_mejoria_dias
    eventos_mejoria = [e for e in mejoria_ok if _en_ventana(ctx.fecha_corte, e.fecha_evento, ventana)]
    recientes = [m for m in mediciones if _en_ventana(ctx.fecha_corte, m.fecha_medicion, ventana)]
    evidencia = (
        bool(eventos_mejoria)
        and bool(recientes)
        and all(en_rango(params.mediciones.rangos[m.tipo_medicion], float(m.valor)) for m in recientes)
    )
    if not evidencia:
        return inicial
    return NIVELES[max(ORDEN_NIVEL[calculado], ORDEN_NIVEL[inicial] - 1)]


def _citas_de_la_especialidad(ctx: ContextoPaciente, descartados: set[str]) -> list[RegistroCita]:
    return [c for c in ctx.citas if c.especialidad == ctx.solicitud.especialidad and c.id_cita not in descartados]


def _alertas(
    ctx: ContextoPaciente,
    eventos: list[RegistroEvento],
    mediciones: list[RegistroMedicion],
    descartados: set[str],
    params: ParametrosReglas,
) -> list[AlertaGestion]:
    pa = params.alertas
    citas = _citas_de_la_especialidad(ctx, descartados)
    alertas: list[AlertaGestion] = []

    fallidas = [c.id_cita for c in citas if c.estado_cita in ESTADOS_FALLIDOS]
    if len(fallidas) >= pa.citas_fallidas_minimo:
        alertas.append(_alerta("citas_fallidas", fallidas))
    inasistencias = [c.id_cita for c in citas if c.estado_cita == "no_asistio"]
    if len(inasistencias) > pa.inasistencias_maximo:
        alertas.append(_alerta("limite_inasistencias", inasistencias))

    dias_espera = _dias(ctx.fecha_corte, ctx.solicitud.fecha_ingreso_lista)
    registros: list[tuple[date, str]] = (
        [(e.fecha_evento, e.id_evento) for e in eventos]
        + [(m.fecha_medicion, m.id_medicion) for m in mediciones]
        + [(c.fecha_cita, c.id_cita) for c in ctx.citas if c.id_cita not in descartados]
    )
    ultimo = max(registros) if registros else None
    desde_ultimo = _dias(ctx.fecha_corte, ultimo[0]) if ultimo else dias_espera
    if dias_espera > pa.silencio_dias_espera and desde_ultimo > pa.silencio_dias_sin_registro:
        ids = [ctx.id_solicitud] + ([ultimo[1]] if ultimo else [])
        alertas.append(_alerta("silencio_clinico", ids))

    if ctx.solicitud.estado_a_la_fecha == "en_espera":
        asistidas = [c.id_cita for c in citas if c.estado_cita == "asistio"]
        if asistidas:
            alertas.append(_alerta("estado_inconsistente", asistidas))
    return alertas


def _alerta(codigo: str, ids: list[str]) -> AlertaGestion:
    return AlertaGestion(codigo=codigo, ids_registro=sorted(set(ids)), accion_sugerida=ACCIONES_ALERTA[codigo])


def _confianza(
    ctx: ContextoPaciente,
    dq: list[HallazgoDQ],
    factores: list[Factor],
    mediciones: list[RegistroMedicion],
    banderas: list[Bandera],
    params: ParametrosReglas,
) -> tuple[Confianza, list[str]]:
    """R8.2 / sección 6.8. La condición de cohorte (n >= 30) no aplica: evaluar() no recibe cohortes."""
    aportan = {i for f in factores if f.aporte != 0 for i in f.ids_registro} - {ctx.id_solicitud}
    verificar = [h for h in dq if h.nivel == "verificar"]
    motivos: list[str] = []
    pc = params.confianza
    recientes = [m for m in mediciones if _en_ventana(ctx.fecha_corte, m.fecha_medicion, pc.dias_mediciones_recientes)]
    muy_recientes = [
        m for m in mediciones if _en_ventana(ctx.fecha_corte, m.fecha_medicion, pc.dias_aviso_sin_mediciones)
    ]

    conciliacion = any(h.codigo == CODIGO_CONCILIACION for h in verificar)
    en_aportes = any(aportan.intersection(h.ids_registro) for h in verificar if h.codigo != CODIGO_CONCILIACION)
    if conciliacion:
        motivos.append("perfil con diferencias de conciliación perfil ↔ tablas")
    if en_aportes:
        motivos.append("hallazgos de calidad 'verificar' en registros que aportan al puntaje")
    if not recientes:
        motivos.append(f"sin mediciones en los últimos {pc.dias_mediciones_recientes} días")
    elif not muy_recientes:
        motivos.append(f"sin mediciones en los últimos {pc.dias_aviso_sin_mediciones} días")
    if verificar and not (conciliacion or en_aportes):
        motivos.append("hay hallazgos de calidad 'verificar' en el perfil")
    if any(b.codigo == BR_PHQ9_ALTO for b in banderas):
        motivos.append("PHQ-9 >= 20: falta el ítem 9 (ideación suicida) para completar la evaluación")

    if conciliacion or en_aportes:
        motivos.append("revisar manualmente")
        return "baja", motivos
    if recientes and not verificar:
        return "alta", motivos
    return "media", motivos


def _exclusion(
    ctx: ContextoPaciente,
    params: ParametrosReglas,
    codigo: str,
    confianza: Confianza,
    motivos: list[str],
    marcas: list[MarcaInferido],
    alertas: list[AlertaGestion],
) -> Evaluacion:
    return Evaluacion(
        id_solicitud=ctx.id_solicitud,
        fecha_corte=ctx.fecha_corte,
        version_reglas=params.version,
        huella_contexto=ctx.huella,
        prioridad_inicial=ctx.solicitud.prioridad_inicial,
        puntaje=None,
        nivel_calculado=None,
        nivel_propuesto=None,
        tipo_resultado="exclusion",
        codigo_exclusion=codigo,
        alertas_gestion=alertas,
        confianza=confianza,
        motivo_confianza=motivos,
        marcas_inferido=marcas,
    )


def _evaluar_exclusion(ctx: ContextoPaciente, params: ParametrosReglas) -> Evaluacion | None:
    s = ctx.solicitud
    if ctx.fallecido_a_la_fecha:
        alertas = []
        if s.estado_extraccion != "fallecido":
            alertas.append(_alerta("fallecido_en_lista", [ctx.id_solicitud, ctx.id_paciente]))
        return _exclusion(ctx, params, EX_FALLECIDO, "alta", ["fecha_defuncion <= fecha_corte"], [], alertas)
    if ctx.fecha_corte == ctx.fecha_extraccion and s.estado_extraccion == "atendido":
        return _exclusion(ctx, params, EX_ATENDIDO, "alta", ["estado atendido en la extracción"], [], [])
    if ctx.fecha_egreso_inferida is not None and ctx.id_cita_egreso_inferido is not None:
        marca = MarcaInferido(
            campo="fecha_egreso",
            valor=ctx.fecha_egreso_inferida.isoformat(),
            ids_registro=[ctx.id_cita_egreso_inferido],
        )
        motivos = ["egreso inferido desde la última cita 'asistio' de la especialidad (R3.3)"]
        return _exclusion(ctx, params, EX_ATENDIDO_INFERIDO, "media", motivos, [marca], [])
    return None


# --------------------------------------------------------------------------- función principal


def evaluar(ctx: ContextoPaciente, dq: list[HallazgoDQ], params: ParametrosReglas) -> Evaluacion:
    """Evalúa una solicitud a su fecha de corte. Misma entrada => misma salida."""
    excl = _evaluar_exclusion(ctx, params)
    if excl is not None:
        return excl

    descartados = ids_descartados(dq)
    eventos = [e for e in ctx.eventos if e.id_evento not in descartados]
    mediciones = [m for m in ctx.mediciones if m.id_medicion not in descartados]
    inicial = ctx.solicitud.prioridad_inicial

    factores: list[Factor] = [
        Factor(
            factor="base",
            detalle=f"prioridad inicial {inicial}",
            aporte=_r2(getattr(params.base, inicial)),
            ids_registro=[ctx.id_solicitud],
        )
    ]
    ev = _factores_eventos(ctx, eventos, mediciones, params)
    factores.extend(ev.factores)
    acel = _factor_aceleracion(ctx, eventos, params)
    if acel is not None:
        factores.append(acel)
    factores.extend(_factores_mediciones(mediciones, params))
    factores.append(_factor_espera(ctx, params))

    puntaje = _r2(min(100.0, max(0.0, sum(f.aporte for f in factores))))
    calculado = nivel_por_puntaje(puntaje, params)
    nivel = _limitar_bajada(calculado, inicial, ctx, ev.mejoria_sin_contradiccion, mediciones, params)
    pisos, banderas = _pisos_y_banderas(ctx, eventos, mediciones, params)
    if pisos and ORDEN_NIVEL[nivel] < ORDEN_NIVEL["alta"]:
        nivel = "alta"
    if banderas:
        nivel = "critica"

    alertas = _alertas(ctx, eventos, mediciones, descartados, params)
    tipo: TipoResultado
    if nivel != inicial or banderas:
        tipo = "priorizacion"
    elif alertas:
        tipo = "gestion"
    else:
        tipo = "sin_alerta"
    confianza, motivos = _confianza(ctx, dq, factores, mediciones, banderas, params)

    return Evaluacion(
        id_solicitud=ctx.id_solicitud,
        fecha_corte=ctx.fecha_corte,
        version_reglas=params.version,
        huella_contexto=ctx.huella,
        prioridad_inicial=inicial,
        puntaje=puntaje,
        nivel_calculado=calculado,
        nivel_propuesto=nivel,
        tipo_resultado=tipo,
        banderas=banderas,
        pisos=pisos,
        contradicciones=ev.contradicciones,
        factores=factores,
        alertas_gestion=alertas,
        confianza=confianza,
        motivo_confianza=motivos,
    )
