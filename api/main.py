"""API REST (FastAPI). Expone el motor de priorización a la app React (web/).

Ejecutar desde la raíz del repositorio:
    uvicorn api.main:app --reload --port 8000

Sin variables de base de datos usa los CSV de HLF_DATA_DIR y SQLite (modo local). Con HLF_DATABASE_URL o
HLF_DB_SECRET_ID lee y escribe en RDS (F0005). En AWS corre en ECS Fargate detrás de CloudFront (F0004).

Las rutas están separadas por dominio en api/rutas/; el estado compartido, en api/estado.py.
"""
from __future__ import annotations

import json
import logging
import threading
import time

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from priorizacion import config
from priorizacion import reglas as R
from servicios.comun import logs

from . import estado as E
from . import seguridad
from .rutas import (agenda, asistente, bandeja, canal, cargas, consulta, examenes, kpis, meta, nocturno, publico,
                    solicitudes)


# Los loggers de la app (hlf.*) a stdout en INFO: en AWS llegan a CloudWatch Logs como JSON (F0013). Uvicorn solo
# configura los suyos; sin esto, los INFO de la app (p. ej. el registro de cada llamada a Bedrock, F0008) se descartan
logs.configurar()
log_peticiones = logging.getLogger("hlf.api.peticiones")
seguridad.validar_arranque()
E.iniciar()

app = FastAPI(title="Priorización dinámica HLF", version=R.VERSION_REGLAS)


@app.middleware("http")
async def sin_cache(request: Request, call_next):
    """Las respuestas de /api tienen datos de pacientes y dependen de la sesión: nunca se guardan en caché."""
    respuesta = await call_next(request)
    if request.url.path.startswith("/api/"):
        respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@app.middleware("http")
async def correlacion(request: Request, call_next):
    """F0013: cada petición lleva un id de correlación (el que manda la Lambda o CloudFront, o uno nuevo) que aparece
    en todos sus logs y vuelve en la cabecera X-Correlation-Id. Una línea por petición a /api, sin cuerpo ni query."""
    entrante = request.headers.get("x-correlation-id") or request.headers.get("x-amz-cf-id")
    with logs.correlacion(entrante) as cid:
        inicio = time.perf_counter()
        estado = 500
        try:
            respuesta = await call_next(request)
            estado = respuesta.status_code
            respuesta.headers["X-Correlation-Id"] = cid
            return respuesta
        finally:
            ruta = request.url.path
            if ruta.startswith("/api/") and ruta != "/api/salud":
                plantilla = getattr(request.scope.get("route"), "path", ruta)      # /api/pacientes/{id_paciente}
                log_peticiones.log(logging.ERROR if estado >= 500 else logging.INFO, json.dumps(
                    {"evento": "peticion", "metodo": request.method, "ruta": plantilla, "estado": estado,
                     "ms": round((time.perf_counter() - inicio) * 1000)}))


# Sin sesión: solo el health check y la configuración del login (no devuelven datos de pacientes)
app.include_router(publico.router)
# Entrada interna de la Lambda de WhatsApp: secreto de servicio en vez de sesión (api/rutas/asistente.py)
app.include_router(asistente.router_interno)
app.include_router(examenes.router_interno)
for modulo in (meta, bandeja, solicitudes, agenda, examenes, canal, kpis, nocturno, cargas, consulta, asistente):
    # Todas exigen la sesión de la Administradora (F0007), antes de tocar la base. Después: si otra tarea
    # escribió o se aplicó una carga, se refresca (solo con RDS)
    app.include_router(modulo.router, dependencies=[Depends(seguridad.administradora), Depends(E.sincronizar)])

# Compatibilidad con quien importe a_json o el registro desde api.main
from .serializacion import a_json  # noqa: E402,F401


def _precalentar():
    """Calcula en segundo plano la bandeja y los KPIs del día de referencia para que la demo abra rápido."""
    try:
        kpis.kpis(config.FECHA_REFERENCIA.isoformat())
        agenda.panel_box(config.FECHA_REFERENCIA.isoformat())
    except Exception:  # noqa: BLE001 — el precalentado es opcional
        pass


threading.Thread(target=_precalentar, daemon=True).start()


# -- app React compilada (npm run build en web/) ----------------------------------------------------
DIST = config.RAIZ / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{ruta:path}", include_in_schema=False)
    def spa(ruta: str):
        archivo = DIST / ruta
        if ruta and archivo.is_file():
            return FileResponse(archivo)
        return FileResponse(DIST / "index.html")
