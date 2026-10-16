"""Pipeline de consolidación (F0006): el mismo para la vista Cargas y para la consolidación nocturna.

Después de que una exportación se suma a raw (F0005), deja al día lo que depende de los datos:
1. Simulación histórica: los pacientes afectados se recalculan completos (su historia cambió); las demás
   solicitudes solo agregan las noches nuevas, continuando desde su última noche guardada.
2. Posiciones: se recalculan solo las noches tocadas y se reemplazan esas noches en la serie.
3. Propuestas: las de los afectados se rehacen; las demás solo suman las de las noches nuevas.
4. Estimación de espera a la fecha de corte.
5. Bitácora de la corrida (origen, estado, detalle).
6. (Opcional) Publicación en Athena, que se pasa como función para no atar el motor a AWS.

Una corrida a la vez: corre con un candado en la base (en SQLite, un candado del proceso).
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Callable

import pandas as pd

from . import config
from .bandeja import construir_bandeja
from .datos import Repositorio
from .estimacion import estimar
from .nocturno import (CANDADO, COLUMNAS, EstadoNoche, _guardar_cambios, _serie_solicitud,
                       calcular_posiciones, ejecutar)
from .registro import Registro

log = logging.getLogger("hlf.consolidacion")


def fecha_de_corte(repo: Repositorio, registro: Registro) -> date:
    """La fecha de los datos: la de la base (versión aplicada o manual) o, en modo local, la última con datos."""
    return registro.fecha_corte() or max(config.FECHA_REFERENCIA_BASE, repo.fecha_max_datos)


def consolidar(repo: Repositorio, registro: Registro, *, origen: str, hasta: date | None = None,
               afectados: set[str] | frozenset = frozenset(), id_carga: int | None = None,
               publicar: Callable[[set[str], date], dict] | None = None, desde_cero: bool = False,
               extra: dict | None = None) -> dict:
    """Deja la simulación, las posiciones, las propuestas y la estimación al día con los datos de `repo`.

    `desde_cero` rehace la historia completa aunque ya haya serie (por ejemplo, tras cambiar las reglas).
    `extra` se agrega al detalle de la bitácora (por ejemplo, las exportaciones que procesó la noche).
    """
    hasta = hasta or fecha_de_corte(repo, registro)
    id_corrida = registro.iniciar_corrida(origen, _alcance(origen, afectados, id_carga), repo.fecha_min, hasta, id_carga)
    t0 = time.time()
    try:
        with registro.candado(CANDADO):
            detalle = _consolidar(repo, registro, hasta, set(afectados), desde_cero)
            detalle["estimaciones"] = _estimar(repo, registro, hasta)
            if publicar is not None:
                detalle["athena"] = publicar(set(detalle.pop("_noches")), hasta)
            else:
                detalle.pop("_noches")
        detalle.update(extra or {})
        detalle["segundos"] = round(time.time() - t0, 1)
        registro.terminar_corrida(id_corrida, "completa", detalle["evaluaciones"], detalle["propuestas"], detalle)
        return {"id_corrida": id_corrida, "fecha_corte": hasta.isoformat(), **detalle}
    except Exception as e:
        log.exception("Consolidación fallida")
        registro.terminar_corrida(id_corrida, "fallida", detalle=extra, error=f"{type(e).__name__}: {e}")
        raise


def _alcance(origen: str, afectados, id_carga) -> str:
    if origen == "carga":
        return f"carga {id_carga}: {len(afectados)} pacientes afectados"
    return {"nocturno": "consolidación nocturna", "completo": "historia completa",
            "solicitud": "puesta al día"}.get(origen, origen)


def _consolidar(repo: Repositorio, registro: Registro, hasta: date, afectados: set[str], desde_cero: bool) -> dict:
    existente = registro.serie()
    if existente.empty or desde_cero:                     # primera vez (o a pedido): la historia completa
        resumen = ejecutar(repo, registro, hasta, registrar=False)
        return {"modo": "completo", "evaluaciones": resumen["n_evaluaciones"], "propuestas": resumen["n_propuestas"],
                "noches_tocadas": int(registro.serie_resumen()["fecha"].nunique()), "pacientes_afectados": 0,
                "_noches": set(registro.serie_resumen()["fecha"])}

    decisiones = registro.decisiones_por_solicitud()
    evidencias, mensajes = registro.evidencias(), registro.mensajes()
    for pid in afectados:
        if pid in repo.historias:
            repo.aplicar_registro(evidencias, mensajes, pid)

    ultima = existente.sort_values("fecha").groupby("id_solicitud").tail(1).set_index("id_solicitud")
    nuevas, cambios_afectados, cambios_otros, recalculadas = [], [], [], set()
    for sol in repo.solicitudes.values():
        decs = decisiones.get(sol.id_solicitud, [])
        if sol.id_paciente in afectados or sol.id_solicitud not in ultima.index:
            filas, cambios = _serie_solicitud(repo, sol, decs, hasta)          # historia completa
            cambios_afectados += cambios
            recalculadas.add(sol.id_solicitud)
        else:
            u = ultima.loc[sol.id_solicitud]
            ultima_noche = date.fromisoformat(u["fecha"])
            if ultima_noche >= hasta:
                continue
            previo = EstadoNoche(u["nivel_propuesto"], bool(u["alerta"]), u["prioridad_vigente"])
            filas, cambios = _serie_solicitud(repo, sol, decs, hasta, desde=ultima_noche + timedelta(days=1),
                                              previo=previo)
            cambios_otros += cambios
        nuevas += filas

    nuevas_df = pd.DataFrame(nuevas, columns=COLUMNAS)
    claves_nuevas = set(zip(nuevas_df["id_solicitud"], nuevas_df["fecha"]))
    noches = set(nuevas_df["fecha"]) | set(existente.loc[existente["id_solicitud"].isin(recalculadas), "fecha"])
    if noches:
        ingreso = pd.DataFrame([(s.id_solicitud, s.fecha_ingreso.isoformat()) for s in repo.solicitudes.values()],
                               columns=["id_solicitud", "fecha_ingreso"])
        conservar = existente[existente["fecha"].isin(noches) & ~existente["id_solicitud"].isin(recalculadas)]
        conservar = conservar[[k not in claves_nuevas for k in zip(conservar["id_solicitud"], conservar["fecha"])]]
        conservar = conservar.merge(ingreso, on="id_solicitud")[COLUMNAS]
        combinada = pd.concat([conservar, nuevas_df], ignore_index=True)
        registro.reemplazar_noches(calcular_posiciones(combinada), noches)

    with registro.conexion() as con:
        for id_sol in recalculadas:
            registro.borrar_propuestas_nocturnas(id_sol, con=con)
        n_prop = _guardar_cambios(repo, registro, cambios_afectados + cambios_otros, decisiones, con)
    return {"modo": "incremental", "evaluaciones": len(nuevas_df), "propuestas": n_prop,
            "noches_tocadas": len(noches), "pacientes_afectados": len(afectados),
            "solicitudes_recalculadas": len(recalculadas), "_noches": noches}


def _estimar(repo: Repositorio, registro: Registro, hasta: date) -> int:
    bandeja, _ = construir_bandeja(repo, registro, hasta)
    if bandeja.empty:
        registro.guardar_estimaciones(hasta, pd.DataFrame())
        return 0
    cola = bandeja[["id_solicitud", "especialidad", "prioridad_vigente", "puntaje_vigente", "fecha_ingreso"]]
    est = estimar(cola, repo.tablas["citas"], hasta)
    registro.guardar_estimaciones(hasta, est)
    return len(est)
