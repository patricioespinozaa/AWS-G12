"""Simulación noche a noche: evalúa cada solicitud activa con solo los datos conocidos hasta esa noche.

Es el motor de la consolidación (priorizacion/consolidacion.py, F0006): la primera vez re-procesa la historia
completa; después, cada exportación nueva solo recalcula a los pacientes afectados y suma las noches nuevas.

Uso:  python -m priorizacion.nocturno          # rehace la historia completa (p. ej. tras cambiar las reglas)
      python -m servicios.nocturno             # la consolidación con buzón que corre cada noche en AWS
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from . import config
from . import reglas as R
from .datos import Repositorio, Solicitud
from .explicacion import explicacion_plantilla
from .motor import Decision, evaluar, huella_datos
from .registro import Registro, crear_registro

# Una sola escritura de la serie a la vez (la consolidación y los recálculos puntuales lo comparten)
CANDADO = "hlf_consolidacion"


@dataclass(frozen=True)
class EstadoNoche:
    """Lo que se necesita de la noche anterior para detectar un cambio (la simulación incremental parte de aquí)."""
    nivel_propuesto: str
    alerta: bool
    prioridad_vigente: str


def _serie_solicitud(repo: Repositorio, sol: Solicitud, decisiones: list[Decision], hasta: date,
                     desde: date | None = None, previo: EstadoNoche | None = None):
    """Evalúa una solicitud cada noche desde `desde` (por defecto, su ingreso) hasta su egreso o `hasta`.

    Devuelve las filas de la serie y los resultados de las noches en que conviene registrar una
    propuesta: cuando cambia el nivel propuesto o se enciende una alerta. Para continuar una simulación ya
    guardada (F0006) se pasa `desde` = la noche siguiente y `previo` = el estado de la última noche guardada.
    """
    hist = repo.historias[sol.id_paciente]
    filas, cambios = [], []
    fin = min(sol.fecha_egreso or hasta + timedelta(days=1), hasta + timedelta(days=1))
    noche = max(sol.fecha_ingreso, desde) if desde else sol.fecha_ingreso
    while noche < fin:
        r = evaluar(sol, hist, noche, decisiones)
        filas.append((noche.isoformat(), sol.id_solicitud, sol.id_paciente, sol.especialidad, r.puntaje,
                      r.puntaje_nivel, r.nivel_propuesto, r.prioridad_vigente, r.prioridad_inicial, r.cambio, int(r.alerta),
                      r.motivo_principal, sol.fecha_ingreso.isoformat(), r.ajuste_puntaje))
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
            "prioridad_vigente", "prioridad_inicial", "cambio", "alerta", "motivo_principal", "fecha_ingreso",
            "ajuste_puntaje"]


def calcular_posiciones(serie: pd.DataFrame) -> pd.DataFrame:
    """Posición en la cola de su especialidad, cada noche.

    - estática (lista congelada): prioridad inicial y luego orden de llegada.
    - dinámica (si se aceptan las propuestas): alerta, nivel propuesto, puntaje vigente (el del motor más el ajuste
      de la Administradora, F0007) y orden de llegada.
    """
    s = serie.copy()
    if "ajuste_puntaje" not in s:
        s["ajuste_puntaje"] = 0.0
    s["ajuste_puntaje"] = s["ajuste_puntaje"].fillna(0.0)
    s["_ini"] = -s["prioridad_inicial"].map(R.ORDEN_NIVEL)
    s["_prop"] = -s["nivel_propuesto"].map(R.ORDEN_NIVEL)
    s["_alerta"] = -s["alerta"]
    s["_puntaje"] = -(s["puntaje"] + s["ajuste_puntaje"])
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


def ejecutar(repo: Repositorio, registro: Registro, hasta: date | None = None, progreso=None,
             registrar: bool = True) -> dict:
    """Re-procesa la historia completa noche a noche."""
    hasta = hasta or config.FECHA_REFERENCIA      # en tiempo de ejecución: con RDS cambia al cargar datos
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
    if registrar:                      # la consolidación (F0006) lleva su propia bitácora
        registro.registrar_corrida(**resumen)
    return resumen


def recalcular_solicitud(repo: Repositorio, registro: Registro, id_solicitud: str,
                         hasta: date | None = None) -> dict:
    """Recalcula una solicitud tras una decisión clínica o evidencia nueva (reevaluación inmediata)."""
    return recalcular_solicitudes(repo, registro, [id_solicitud], hasta, alcance=id_solicitud)


def recalcular_solicitudes(repo: Repositorio, registro: Registro, ids: list[str],
                           hasta: date | None = None, alcance: str | None = None) -> dict:
    """Recalcula varias solicitudes (por ejemplo, las de los pacientes afectados por una carga, F0005).

    La posición de los demás en la misma cola también cambia: se recalcula cada especialidad afectada
    una sola vez, no una vez por solicitud.
    """
    with registro.candado(CANDADO):
        return _recalcular_solicitudes(repo, registro, ids, hasta or config.FECHA_REFERENCIA, alcance)


def _recalcular_solicitudes(repo: Repositorio, registro: Registro, ids: list[str], hasta: date,
                            alcance: str | None) -> dict:
    t0, inicio = time.time(), datetime.now().isoformat(timespec="seconds")
    sols = [repo.solicitudes[i] for i in dict.fromkeys(ids) if i in repo.solicitudes]
    decisiones = registro.decisiones_por_solicitud()
    evidencias, mensajes = registro.evidencias(), registro.mensajes()
    for pid in {s.id_paciente for s in sols}:
        repo.aplicar_registro(evidencias, mensajes, pid)
    filas_por_esp: dict[str, list] = {}
    cambios = []
    for sol in sols:
        f, c = _serie_solicitud(repo, sol, decisiones.get(sol.id_solicitud, []), hasta)
        filas_por_esp.setdefault(sol.especialidad, []).extend(f)
        cambios += c
    ingreso = pd.DataFrame([(s.id_solicitud, s.fecha_ingreso.isoformat()) for s in repo.solicitudes.values()],
                           columns=["id_solicitud", "fecha_ingreso"])
    recalculadas = {s.id_solicitud for s in sols}
    for especialidad, filas in filas_por_esp.items():
        otras = registro.serie(especialidad=especialidad)
        otras = otras[~otras["id_solicitud"].isin(recalculadas)].merge(ingreso, on="id_solicitud")
        nueva = pd.concat([otras[COLUMNAS], pd.DataFrame(filas, columns=COLUMNAS)], ignore_index=True)
        registro.reemplazar_serie(calcular_posiciones(nueva), especialidad=especialidad)
    with registro.conexion() as con:
        for sol in sols:
            registro.borrar_propuestas_nocturnas(sol.id_solicitud, con=con)
        n_prop = _guardar_cambios(repo, registro, cambios, decisiones, con)
    resumen = dict(inicio=inicio, fin=datetime.now().isoformat(timespec="seconds"),
                   desde=min((s.fecha_ingreso for s in sols), default=hasta).isoformat(), hasta=hasta.isoformat(),
                   alcance=alcance or f"{len(sols)} solicitudes", version_reglas=R.VERSION_REGLAS,
                   n_evaluaciones=sum(len(f) for f in filas_por_esp.values()), n_propuestas=n_prop,
                   segundos=round(time.time() - t0, 1))
    registro.registrar_corrida(**resumen)
    return resumen


if __name__ == "__main__":
    from .consolidacion import consolidar
    repo = Repositorio.crear()
    registro = crear_registro()
    print("Recalculando la historia completa (para la consolidación con buzón: python -m servicios.nocturno)…")
    res = consolidar(repo, registro, origen="completo", desde_cero=True)
    print(f"Listo al {res['fecha_corte']}: {res['evaluaciones']:,} evaluaciones, {res['propuestas']:,} propuestas, "
          f"{res['estimaciones']:,} estimaciones, {res['segundos']} s")
    print(f"Base: {'RDS' if config.usa_rds() else config.DB_PATH}")
