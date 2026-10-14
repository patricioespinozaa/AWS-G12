"""Eje de disponibilidad y agenda de box (propuesta B). Nunca modifica la prioridad clínica.

Un paciente con prioridad alta al que le faltan exámenes no pierde su lugar: no se le asigna la hora
de hoy, se gatilla una acción para que esté listo y se llama al siguiente que sí lo está.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from . import reglas as R
from .datos import Historia, Solicitud


@dataclass
class Disponibilidad:
    estado: str                 # lista | sin_contacto | faltan_examenes | no_confirma
    pendientes: list[str]
    riesgo_no_show: float
    n_citas: int
    n_no_asistio: int
    accion: str | None


def riesgo_no_show(hist: Historia, corte: date) -> tuple[float, int, int]:
    citas = hist.citas_hasta(corte)
    n = len(citas)
    faltas = sum(c.estado == "no_asistio" for c in citas)
    riesgo = (faltas + R.TASA_NO_SHOW_GLOBAL * R.PESO_PRIOR_NO_SHOW) / (n + R.PESO_PRIOR_NO_SHOW)
    return riesgo, n, faltas


def evaluar_disponibilidad(sol: Solicitud, hist: Historia, corte: date, mensajes: pd.DataFrame) -> Disponibilidad:
    riesgo, n, faltas = riesgo_no_show(hist, corte)
    pendientes: list[str] = []
    acciones: list[str] = []

    msj = mensajes[(mensajes["id_paciente"] == sol.id_paciente) & (mensajes["fecha"] <= corte.isoformat())] \
        if len(mensajes) else mensajes
    ultimo = msj.iloc[-1]["tipo"] if len(msj) else None
    recientes = msj[msj["fecha"] >= (pd.Timestamp(corte) - pd.Timedelta(days=R.VENTANA_CONFIRMACION_DIAS)).date().isoformat()] \
        if len(msj) else msj
    confirmo = len(recientes) and (recientes["tipo"] == "confirma_asistencia").any()

    if ultimo == "sin_respuesta":
        pendientes.append("sin_contacto")
        acciones.append("Rescate telefónico o a través del CESFAM")
    requisitos = R.REQUISITO_EXAMEN.get(sol.especialidad)
    if requisitos:
        meds = hist.mediciones_hasta(corte)
        vigente = any((corte - m.fecha).days <= R.VIGENCIA_EXAMEN_DIAS
                      for t in requisitos for m in meds.get(t, []))
        if not vigente:
            pendientes.append("faltan_examenes")
            nombres = " o ".join(R.NOMBRE_MEDICION[t] for t in requisitos)
            acciones.append(f"Emitir orden de {nombres} y pedir que suba el resultado por el canal del paciente")
    if riesgo >= R.UMBRAL_RIESGO_NO_SHOW and not confirmo:
        pendientes.append("no_confirma")
        acciones.append("Confirmar asistencia por WhatsApp o llamada antes de asignar la hora")
    if ultimo == "no_puede_asistir":
        pendientes.append("no_confirma")
        acciones.append("Ofrecer otra fecha")

    return Disponibilidad(pendientes[0] if pendientes else "lista", pendientes, round(riesgo, 2), n, faltas,
                          " · ".join(acciones) if acciones else None)


def proponer_agenda(bandeja: pd.DataFrame, agenda: pd.DataFrame, fecha: date, especialidad: str,
                    n_reemplazos: int = 3) -> dict:
    """Llena los cupos libres de un día con los pacientes de mayor prioridad que están listos.

    `bandeja` es la salida de vistas/servicio.bandeja() a la misma fecha, con posicion_dinamica y disponibilidad.
    """
    bloques = agenda[(agenda["fecha"] == pd.Timestamp(fecha)) & (agenda["especialidad"] == especialidad)].copy()
    bloques["cupos_libres"] = bloques["capacidad_cupos"] - bloques["cupos_usados"]
    cola = bandeja[bandeja["especialidad"] == especialidad].sort_values("posicion_dinamica")
    listos = cola[cola["disponibilidad"] == "lista"]
    no_listos = cola[cola["disponibilidad"] != "lista"]

    cupos = []
    for b in bloques.itertuples():
        cupos += [b.id_box] * int(b.cupos_libres)
    asignados = listos.head(len(cupos)).copy()
    asignados.insert(0, "id_box", cupos[:len(asignados)])
    reemplazos = listos.iloc[len(asignados):len(asignados) + n_reemplazos]
    # Quienes estarían antes en la cola pero no están listos: no pierden su lugar, se gatilla una acción
    corte_pos = asignados["posicion_dinamica"].max() if len(asignados) else cola["posicion_dinamica"].max()
    acciones = no_listos[no_listos["posicion_dinamica"] <= (corte_pos if pd.notna(corte_pos) else 0)]

    # Comparación con la lista congelada: a quién irían los mismos cupos ordenando por prioridad inicial
    estatica = cola.sort_values("posicion_estatica").head(len(cupos))
    return {
        "bloques": bloques,
        "cupos_libres": len(cupos),
        "asignados": asignados,
        "reemplazos": reemplazos,
        "acciones": acciones,
        "alertas_atendidas_dinamica": int(asignados["alerta"].sum()) if len(asignados) else 0,
        "alertas_atendidas_estatica": int(estatica["alerta"].sum()) if len(estatica) else 0,
        "alertas_en_cola": int(cola["alerta"].sum()),
    }
