"""API REST (FastAPI). Expone el motor de priorización a la app React (web/).

Ejecutar desde la raíz del repositorio:
    uvicorn api.main:app --reload --port 8000

Sin variables de base de datos usa los CSV de HLF_DATA_DIR y SQLite (modo local). Con HLF_DATABASE_URL o
HLF_DB_SECRET_ID lee y escribe en RDS (F0005). En AWS corre en ECS Fargate detrás de CloudFront (F0004).

Las rutas están separadas por dominio en api/rutas/; el estado compartido, en api/estado.py.
"""
from __future__ import annotations

import logging
import sys
import threading

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from priorizacion import config
from priorizacion import reglas as R

from . import estado as E
from . import seguridad
from .rutas import agenda, bandeja, canal, cargas, kpis, meta, nocturno, publico, solicitudes


def _configurar_logs() -> None:
    """Los loggers de la app (hlf.*) a stdout en INFO: en AWS llegan a CloudWatch Logs. Uvicorn solo configura los
    suyos; sin esto, los INFO de la app (p. ej. el registro de cada llamada a Bedrock, F0008) se descartan."""
    raiz = logging.getLogger("hlf")
    if not raiz.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        raiz.addHandler(h)
        raiz.setLevel(logging.INFO)


_configurar_logs()
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


# Sin sesión: solo el health check y la configuración del login (no devuelven datos de pacientes)
app.include_router(publico.router)
for modulo in (meta, bandeja, solicitudes, agenda, canal, kpis, nocturno, cargas):
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
