"""Estimación del tiempo de espera (F0006): método `throughput_8_semanas`.

Para cada especialidad:
1. La cola se ordena por prioridad VIGENTE (la decidida por la Administradora; nunca la propuesta del motor), luego
   por fecha de ingreso e ID. Esa es la posición vigente.
2. Se cuentan las atenciones (citas con asistencia) de cada una de las 8 semanas previas al corte.
3. Rango de días = posición ÷ atenciones por día, con la semana p75 (cota optimista) y la p25 (cota pesimista).
   Si un percentil es cero (pocas atenciones), se usan la mejor y la peor semana con atenciones.
4. Sin atenciones en la ventana NO hay estimación: no se inventa un número.

Es un rango, no una fecha: la posición en la lista no equivale a una fecha garantizada de atención. Se guarda con
`publicable = False` hasta que el HLF apruebe informarla al paciente.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .reglas import ORDEN_NIVEL

METODO = "throughput_8_semanas"
VERSION_METODO = "v1"
SEMANAS = 8
COLUMNAS = ["id_solicitud", "fecha_calculo", "prioridad_vigente", "posicion_vigente", "total_cola",
            "dias_estimados_min", "dias_estimados_max", "confianza", "metodo", "version_metodo", "publicable"]


def atenciones_por_semana(citas: pd.DataFrame, especialidad: str, corte: date) -> list[int]:
    """Atenciones de cada una de las SEMANAS semanas previas al corte (la 0 es la que termina en el corte)."""
    inicio = corte - timedelta(weeks=SEMANAS)
    fechas = pd.to_datetime(citas["fecha_cita"]).dt.date
    sel = citas[(citas["especialidad"] == especialidad) & (citas["estado_cita"] == "asistio")
                & (fechas > inicio) & (fechas <= corte)]
    conteo = [0] * SEMANAS
    for f in pd.to_datetime(sel["fecha_cita"]).dt.date:
        conteo[min((corte - f).days // 7, SEMANAS - 1)] += 1
    return conteo


def _confianza(semanas: list[int]) -> str:
    con_atenciones = sum(1 for n in semanas if n > 0)
    if con_atenciones == SEMANAS and sum(semanas) >= 2 * SEMANAS:
        return "alta"
    return "media" if con_atenciones >= SEMANAS // 2 + 1 else "baja"


def estimar(cola: pd.DataFrame, citas: pd.DataFrame, corte: date) -> pd.DataFrame:
    """`cola`: solicitudes activas al corte con id_solicitud, especialidad, prioridad_vigente y fecha_ingreso."""
    filas = []
    for especialidad, grupo in cola.groupby("especialidad"):
        semanas = atenciones_por_semana(citas, especialidad, corte)
        if sum(semanas) == 0:
            continue                                         # sin atenciones recientes: no se inventa
        p25, p75 = np.percentile(semanas, [25, 75])
        con_atenciones = [n for n in semanas if n > 0]
        # Con pocas atenciones los percentiles pueden ser 0: se usan la mejor y la peor semana con atenciones
        pesimista = (p25 if p25 > 0 else min(con_atenciones)) / 7
        optimista = max((p75 if p75 > 0 else max(con_atenciones)) / 7, pesimista)
        ordenada = grupo.assign(_nivel=-grupo["prioridad_vigente"].map(ORDEN_NIVEL)) \
            .sort_values(["_nivel", "fecha_ingreso", "id_solicitud"])
        total, confianza = len(ordenada), _confianza(semanas)
        for posicion, f in enumerate(ordenada.itertuples(index=False), start=1):
            dias_min = math.ceil(posicion / optimista)
            dias_max = max(dias_min, math.ceil(posicion / pesimista))
            filas.append((f.id_solicitud, corte.isoformat(), f.prioridad_vigente, posicion, total, dias_min, dias_max,
                          confianza, METODO, VERSION_METODO, False))
    return pd.DataFrame(filas, columns=COLUMNAS)
