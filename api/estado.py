"""Estado compartido de la API: repositorio en memoria, registro, caché y utilidades de las rutas.

Las rutas lo usan como `E.repo` y `E.registro` (atributos del módulo, no copias), porque una carga nueva
reemplaza el repositorio completo (F0005). Con RDS puede haber varias tareas detrás del ALB: `sincronizar()`
corre antes de cada petición y, si otra tarea escribió o se aplicó una carga, refresca lo que hay en memoria.

"Hoy" es la fecha de corte de los datos (F0006): la de la última versión aplicada en RDS, o la última fecha con
datos en modo local. Una carga confirmada dispara la consolidación en segundo plano (`consolidar_en_segundo_plano`).
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime

import pandas as pd
from fastapi import HTTPException

from priorizacion import config
from priorizacion.bandeja import construir_bandeja
from priorizacion.consolidacion import consolidar, fecha_de_corte
from priorizacion.datos import Repositorio
from priorizacion.motor import Decision, Resultado
from priorizacion.registro import Registro, crear_registro

from .serializacion import a_json

log = logging.getLogger("hlf.api")

CASOS_REFERENCIA = {
    "PAC-HLF-00002": "Deterioro agudo",
    "PAC-HLF-00001": "Deterioro progresivo",
    "PAC-HLF-00028": "Mejora",
    "PAC-HLF-00020": "Inasistencia",
    "PAC-HLF-00032": "Estable / atendido",
    "PAC-HLF-00009": "Fallecido en espera",
}

escritura = threading.Lock()
_tarea_lock = threading.Lock()
_tarea: dict = {"hilo": None, "origen": None, "inicio": None, "fin": None, "resultado": None, "error": None}
_cache: dict[tuple, object] = {}
_visto: dict[str, str | None] = {"app": None, "datos": None}

repo: Repositorio
registro: Registro


def iniciar() -> None:
    """Carga el repositorio y el registro. La primera vez calcula la serie nocturna completa."""
    global repo, registro
    if config.usa_rds():
        _migrar()
    registro = crear_registro()
    repo = Repositorio.crear()
    _ajustar_fecha_referencia(repo)
    repo.aplicar_registro(registro.evidencias(), registro.mensajes())
    # Con varias tareas arrancando a la vez, solo una calcula la serie inicial; las demás la esperan
    with registro.candado("hlf_serie_inicial"):
        if not registro.hay_serie():
            log.info("Calculando la serie nocturna completa (primer arranque)")
            consolidar(repo, registro, origen="completo")
        elif _desactualizada():
            log.info("Poniendo al día la serie y la estimación a la fecha de corte %s", config.FECHA_REFERENCIA)
            consolidar(repo, registro, origen="solicitud")
    _recordar_version()


def _desactualizada() -> bool:
    """La serie no llega a la fecha de corte o falta la estimación (por ejemplo, datos cargados por la CLI)."""
    ultima = registro.serie_resumen()["fecha"].max()
    return str(ultima) < config.FECHA_REFERENCIA.isoformat() or registro.estimaciones().empty


def _migrar() -> None:
    """Con RDS, aplica las migraciones pendientes antes de leer: una versión nueva de la API nunca arranca sobre
    un esquema viejo."""
    from db import esquema
    from db.conexion import conectar
    with conectar() as conn:
        esquema.migrar(conn)


def _recordar_version() -> None:
    app, _, datos = registro.version().partition("-") if config.usa_rds() else (None, "", None)
    _visto.update(app=app, datos=datos)


def recargar_datos() -> None:
    """Reconstruye el repositorio desde raw (después de una carga aplicada)."""
    global repo
    nuevo = Repositorio.crear()
    _ajustar_fecha_referencia(nuevo)
    nuevo.aplicar_registro(registro.evidencias(), registro.mensajes())
    repo = nuevo
    _cache.clear()


def _ajustar_fecha_referencia(r: Repositorio) -> None:
    """"Hoy" es la fecha de corte de los datos: una carga de un periodo nuevo se ve en la bandeja (F0006)."""
    config.FECHA_REFERENCIA = fecha_de_corte(r, registro)


# -- consolidación en segundo plano (F0006) -----------------------------------------------------------
def consolidar_en_segundo_plano(origen: str, afectados=frozenset(), id_carga: int | None = None,
                                recargar: bool = False, desde_cero: bool = False) -> bool:
    """Lanza el pipeline en un hilo y vuelve de inmediato. False si ya hay uno corriendo en esta tarea."""
    with _tarea_lock:
        if _tarea["hilo"] is not None and _tarea["hilo"].is_alive():
            return False
        hilo = threading.Thread(target=_correr_consolidacion, daemon=True, name="consolidacion",
                                args=(origen, frozenset(afectados), id_carga, recargar, desde_cero))
        _tarea.update(hilo=hilo, origen=origen, inicio=datetime.now().isoformat(timespec="seconds"), fin=None,
                      resultado=None, error=None)
        hilo.start()
        return True


def _correr_consolidacion(origen, afectados, id_carga, recargar, desde_cero) -> None:
    try:
        if recargar:                       # los datos nuevos ya están en raw
            with escritura:
                recargar_datos()
                _recordar_version()
        resultado = consolidar(repo, registro, origen=origen, afectados=afectados, id_carga=id_carga,
                               publicar=publicador(), desde_cero=desde_cero)
        _tarea["resultado"] = {k: v for k, v in resultado.items() if k != "athena"}
    except Exception as e:  # noqa: BLE001 — queda en la bitácora y en el estado
        log.exception("Consolidación en segundo plano fallida")
        _tarea["error"] = f"{type(e).__name__}: {e}"
    finally:
        _tarea["fin"] = datetime.now().isoformat(timespec="seconds")
        _cache.clear()


def estado_consolidacion() -> dict:
    """Lo que ve la app: si hay un recálculo corriendo (en esta u otra tarea) y cómo terminó el último."""
    hilo = _tarea["hilo"]
    return {"en_curso": bool(hilo is not None and hilo.is_alive()) or registro.corrida_en_curso(),
            "origen": _tarea["origen"], "inicio": _tarea["inicio"], "fin": _tarea["fin"],
            "resultado": _tarea["resultado"], "error": _tarea["error"],
            "fecha_corte": config.FECHA_REFERENCIA.isoformat()}


def exigir_sin_recalculo() -> None:
    """Las escrituras que recalculan una solicitud esperan a que termine la consolidación en curso."""
    if estado_consolidacion()["en_curso"]:
        raise HTTPException(409, "Se están recalculando las prioridades con los datos nuevos. Intenta en un minuto.")


def publicador():
    """Publicación en Athena después de consolidar, si está configurada (HLF_ATHENA_PUBLICAR=1 y RDS)."""
    if not (config.usa_rds() and config.ATHENA_PUBLICAR):
        return None
    from db import athena
    return athena.publicador_consolidacion()


def sincronizar() -> None:
    """Antes de cada petición (solo con RDS): si otra tarea escribió o se aplicó una carga, refresca."""
    if not config.usa_rds():
        return
    app, _, datos = registro.version().partition("-")
    if datos != _visto["datos"]:
        with escritura:
            recargar_datos()
    elif app != _visto["app"]:
        repo.aplicar_registro(registro.evidencias(), registro.mensajes())
    _visto.update(app=app, datos=datos)


# -- utilidades de las rutas --------------------------------------------------------------------------
def fecha(valor: str | None) -> date:
    if not valor:
        return config.FECHA_REFERENCIA
    try:
        f = date.fromisoformat(valor)
    except ValueError:
        raise HTTPException(400, f"Fecha inválida: {valor}")
    return min(max(f, repo.fecha_min), config.FECHA_REFERENCIA)


def solicitud(id_solicitud: str):
    if id_solicitud not in repo.solicitudes:
        raise HTTPException(404, f"No existe la solicitud {id_solicitud}")
    return repo.solicitudes[id_solicitud]


def paciente(id_paciente: str):
    try:
        return repo.solicitud_de_paciente(id_paciente)
    except StopIteration:
        raise HTTPException(404, f"No existe el paciente {id_paciente}")


def decisiones(id_solicitud: str) -> list[Decision]:
    return [Decision(date.fromisoformat(d.fecha_corte), d.prioridad_final)
            for d in registro.decisiones(id_solicitud).itertuples(index=False)]


def cacheado(clave: tuple, calcular):
    clave = clave + (registro.version(),)
    if clave not in _cache:
        if len(_cache) > 40:
            _cache.clear()
        _cache[clave] = calcular()
    return _cache[clave]


def bandeja(corte: date) -> tuple[pd.DataFrame, dict[str, Resultado]]:
    return cacheado(("bandeja", corte), lambda: construir_bandeja(repo, registro, corte))


def serie() -> pd.DataFrame:
    return cacheado(("serie",), registro.serie_resumen)


def resultado_json(r: Resultado) -> dict:
    d = a_json(r)
    d["motivo_principal"] = r.motivo_principal
    return d
