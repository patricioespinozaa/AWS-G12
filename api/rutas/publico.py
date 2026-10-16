"""Las únicas rutas de /api sin sesión (F0007). Ninguna devuelve datos de pacientes."""
from fastapi import APIRouter

from .. import seguridad

router = APIRouter()


@router.get("/api/salud")
def salud():
    """Health check del ALB y del contenedor: responde mientras la API esté arriba."""
    return {"ok": True}


@router.get("/api/auth/config")
def auth_config():
    """Lo que el frontend necesita para iniciar sesión: dominio del Hosted UI y app client (público, con PKCE)."""
    return seguridad.configuracion().publica()
