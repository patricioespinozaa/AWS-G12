"""Consolidación nocturna: recalcula la prioridad de cada solicitud activa, noche a noche.

Para probar con el dataset se re-procesa la historia completa: cada noche usa solo los datos con
fecha ≤ esa noche, como si el proceso hubiera corrido todos los días. En AWS es un job programado
(EventBridge → Lambda/Glue) que corre una vez por noche.

Uso:  python -m priorizacion.nocturno
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import pandas as pd

from . import config
from . import reglas as R
from .datos import Repositorio, Solicitud
from .explicacion import explicacion_plantilla
from .motor import Decision, evaluar, huella_datos
from .registro import Registro


def _serie_solicitud(repo: Repositorio, sol: Solicitud, decisiones: list[Decision], hasta: date):
    """Evalúa una solicitud cada noche desde su ingreso hasta su egreso o `hasta`.

    Devuelve las filas de la serie y los resultados de las noches en que conviene registrar una
    propuesta: cuando cambia el nivel propuesto o se enciende una alerta.
    """
    hist = repo.historias[sol.id_paciente]
    filas, cambios = [], []
    fin = min(sol.fecha_egreso or hasta + timedelta(days=1), hasta + timedelta(days=1))
    noche, previo = sol.fecha_ingreso, None
    while noche < fin:
        r = evaluar(sol, hist, noche, decisiones)
        filas.append((noche.isoformat(), sol.id_solicitud, sol.id_paciente, sol.especialidad, r.puntaje,
                      r.puntaje_nivel, r.nivel_propuesto, r.prioridad_vigente, r.prioridad_inicial, r.cambio, int(r.alerta),
                      r.motivo_principal, sol.fecha_ingreso.isoformat()))
        if previo is None:
            if r.cambio != "igual" or r.alerta:
                cambios.append(r)
        elif r.nivel_propuesto != previo.nivel_propuesto or (r.alerta and not previo.alerta) \
                or r.prioridad_vigente != previo.prioridad_vigente:
            cambios.append(r)
        previo = r
        noche += timedelta(days=1)
    return filas, cambios


COLUMNAS = ["fecha", "id_solicitud", "id_paciente", "especialidad", "puntaje", "puntaje_nivel", "nivel_propuesto",
            "prioridad_vigente", "prioridad_inicial", "cambio", "alerta", "motivo_principal", "fecha_ingreso"]


def calcular_posiciones(serie: pd.DataFrame) -> pd.DataFrame:
    """Posición en la cola de su especialidad, cada noche.

    - estática (lista congelada): prioridad inicial y luego orden de llegada.
    - dinámica (si se aceptan las propuestas): alerta, nivel propuesto, puntaje y orden de llegada.
    """
    s = serie.copy()
    s["_ini"] = -s["prioridad_inicial"].map(R.ORDEN_NIVEL)
    s["_prop"] = -s["nivel_propuesto"].map(R.ORDEN_NIVEL)
    s["_alerta"] = -s["alerta"]
    s["_puntaje"] = -s["puntaje"]
    grupo = ["fecha", "especialidad"]
    s = s.sort_values(grupo + ["_ini", "fecha_ingreso", "id_solicitud"])
    s["posicion_estatica"] = s.groupby(grupo).cumcount() + 1
    s = s.sort_values(grupo + ["_alerta", "_prop", "_puntaje", "fecha_ingreso", "id_solicitud"])
    s["posicion_dinamica"] = s.groupby(grupo).cumcount() + 1
    s["total_cola"] = s.groupby(grupo)["id_solicitud"].transform("size")
    return s.drop(columns=["_ini", "_prop", "_alerta", "_puntaje", "fecha_ingreso"])


def _guardar_cambios(repo: Repositorio, registro: Registro, cambios, decisiones_por_sol, con) -> int:
    for r in cambios:
        sol = repo.solicitudes[r.id_solicitud]
        huella = huella_datos(sol, repo.historias[sol.id_paciente], r.fecha_corte, decisiones_por_sol.get(sol.id_solicitud))
        registro.guardar_propuesta(r, huella, explicacion_plantilla(r), "plantilla", "nocturno", con=con)
    return len(cambios)


def ejecutar(repo: Repositorio, registro: Registro, hasta: date = config.FECHA_REFERENCIA, progreso=None) -> dict:
    """Re-procesa la historia completa noche a noche."""
    t0, inicio = time.time(), datetime.now().isoformat(timespec="seconds")
    repo.aplicar_registro(registro.evidencias(), registro.mensajes())
    decisiones = registro.decisiones_por_solicitud()
    filas, cambios = [], []
    sols = list(repo.solicitudes.values())
    for i, sol in enumerate(sols):
        f, c = _serie_solicitud(repo, sol, decisiones.get(sol.id_solicitud, []), hasta)
        filas += f
        cambios += c
        if progreso and i % 25 == 0:
            progreso(i / len(sols), f"Evaluando {sol.id_solicitud} ({i + 1}/{len(sols)})")
    serie = calcular_posiciones(pd.DataFrame(filas, columns=COLUMNAS))
    if progreso:
        progreso(0.95, "Guardando serie y propuestas")
    registro.reemplazar_serie(serie)
    with registro.conexion() as con:
        registro.borrar_propuestas_nocturnas(con=con)
        n_prop = _guardar_cambios(repo, registro, cambios, decisiones, con)
    resumen = dict(inicio=inicio, fin=datetime.now().isoformat(timespec="seconds"),
                   desde=repo.fecha_min.isoformat(), hasta=hasta.isoformat(), alcance="historia completa",
                   version_reglas=R.VERSION_REGLAS, n_evaluaciones=len(serie), n_propuestas=n_prop,
                   segundos=round(time.time() - t0, 1))
    registro.registrar_corrida(**resumen)
    return resumen


def recalcular_solicitud(repo: Repositorio, registro: Registro, id_solicitud: str,
                         hasta: date = config.FECHA_REFERENCIA) -> dict:
    """Recalcula una solicitud tras una decisión clínica o evidencia nueva (reevaluación inmediata)."""
    t0, inicio = time.time(), datetime.now().isoformat(timespec="seconds")
    sol = repo.solicitudes[id_solicitud]
    repo.aplicar_registro(registro.evidencias(), registro.mensajes(), sol.id_paciente)
    decisiones = registro.decisiones_por_solicitud()
    filas, cambios = _serie_solicitud(repo, sol, decisiones.get(id_solicitud, []), hasta)
    # La posición de los demás en la misma cola también cambia: se recalcula la especialidad completa
    otras = registro.serie(especialidad=sol.especialidad)
    otras = otras[otras["id_solicitud"] != id_solicitud]
    otras = otras.merge(pd.DataFrame([(s.id_solicitud, s.fecha_ingreso.isoformat()) for s in repo.solicitudes.values()],
                                     columns=["id_solicitud", "fecha_ingreso"]), on="id_solicitud")
    nueva = pd.concat([otras[COLUMNAS], pd.DataFrame(filas, columns=COLUMNAS)], ignore_index=True)
    registro.reemplazar_serie(calcular_posiciones(nueva), especialidad=sol.especialidad)
    with registro.conexion() as con:
        registro.borrar_propuestas_nocturnas(id_solicitud, con=con)
        n_prop = _guardar_cambios(repo, registro, cambios, decisiones, con)
    resumen = dict(inicio=inicio, fin=datetime.now().isoformat(timespec="seconds"),
                   desde=sol.fecha_ingreso.isoformat(), hasta=hasta.isoformat(), alcance=id_solicitud,
                   version_reglas=R.VERSION_REGLAS, n_evaluaciones=len(filas), n_propuestas=n_prop,
                   segundos=round(time.time() - t0, 1))
    registro.registrar_corrida(**resumen)
    return resumen


if __name__ == "__main__":
    repo = Repositorio.desde_csv()
    registro = Registro()
    print("Consolidación nocturna: re-procesando la historia completa…")
    res = ejecutar(repo, registro, progreso=lambda p, msg: print(f"  {p:4.0%} {msg}") if int(p * 100) % 20 == 0 else None)
    print(f"Listo: {res['n_evaluaciones']:,} evaluaciones, {res['n_propuestas']:,} propuestas, {res['segundos']} s")
    print(f"Base: {config.DB_PATH}")
