"""API REST (FastAPI). Expone el motor de priorización a la app React (web/).

Ejecutar desde la raíz del repositorio:
    uvicorn api.main:app --reload --port 8000

Sin variables de base de datos usa los CSV de HLF_DATA_DIR y SQLite (modo local). Con HLF_DATABASE_URL o
HLF_DB_SECRET_ID lee y escribe en RDS (F0005). En AWS corre en ECS Fargate detrás de CloudFront (F0004).

Las rutas están separadas por dominio en api/rutas/; el estado compartido, en api/estado.py.
"""
from __future__ import annotations

import threading

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from priorizacion import config
from priorizacion import reglas as R

from . import estado as E
from .rutas import agenda, bandeja, canal, cargas, kpis, meta, nocturno, solicitudes

E.iniciar()

app = FastAPI(title="Priorización dinámica HLF", version=R.VERSION_REGLAS)
for modulo in (meta, bandeja, solicitudes, agenda, canal, kpis, nocturno, cargas):
    # Antes de cada petición: si otra tarea escribió o se aplicó una carga, se refresca (solo con RDS)
    app.include_router(modulo.router, dependencies=[Depends(E.sincronizar)])

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
