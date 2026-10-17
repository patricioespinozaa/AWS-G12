"""Bandeja priorizada a una fecha de corte: todas las solicitudes activas, evaluadas y ordenadas."""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import reglas as R
from .datos import Repositorio
from .disponibilidad import evaluar_disponibilidad
from .motor import Resultado, evaluar
from .nocturno import calcular_posiciones
from .registro import Registro


def construir_bandeja(repo: Repositorio, registro: Registro, corte: date) -> tuple[pd.DataFrame, dict[str, Resultado]]:
    decisiones = registro.decisiones_por_solicitud()
    mensajes = registro.mensajes()
    filas, resultados = [], {}
    for sol in repo.activas(corte):
        hist = repo.historias[sol.id_paciente]
        r = evaluar(sol, hist, corte, decisiones.get(sol.id_solicitud))
        disp = evaluar_disponibilidad(sol, hist, corte, mensajes)
        resultados[sol.id_solicitud] = r
        filas.append({
            "fecha": corte.isoformat(), "id_solicitud": sol.id_solicitud, "id_paciente": sol.id_paciente,
            "nombre": sol.nombre, "edad": sol.edad, "sexo": sol.sexo, "comuna": sol.comuna,
            "prevision": sol.prevision, "nivel_socioeconomico": sol.nivel_socioeconomico,
            "especialidad": sol.especialidad, "sub_especialidad": sol.sub_especialidad,
            "cie10": sol.cie10, "diagnostico": sol.diagnostico,
            "riesgo_basal": R.RIESGO_BASAL_DX.get(sol.cie10, ("medio",))[0],
            "canal_origen": R.CANAL_ORIGEN.get(sol.origen_derivacion, sol.origen_derivacion),
            "prioridad_inicial": sol.prioridad_inicial, "prioridad_vigente": r.prioridad_vigente,
            "nivel_propuesto": r.nivel_propuesto, "cambio": r.cambio, "alerta": int(r.alerta),
            "puntaje": r.puntaje, "puntaje_nivel": r.puntaje_nivel, "motivo_principal": r.motivo_principal,
            "ajuste_puntaje": r.ajuste_puntaje, "puntaje_vigente": r.puntaje_vigente,
            "dias_espera": (corte - sol.fecha_ingreso).days, "fecha_ingreso": sol.fecha_ingreso.isoformat(),
            "disponibilidad": disp.estado, "accion": disp.accion, "riesgo_no_show": disp.riesgo_no_show,
        })
    if not filas:
        return pd.DataFrame(), resultados
    df = calcular_posiciones(pd.DataFrame(filas))   # descarta fecha_ingreso: se vuelve a agregar
    df["fecha_ingreso"] = df["id_solicitud"].map({f["id_solicitud"]: f["fecha_ingreso"] for f in filas})
    df["avance_posiciones"] = df["posicion_estatica"] - df["posicion_dinamica"]
    return df.sort_values(["especialidad", "posicion_dinamica"]).reset_index(drop=True), resultados
