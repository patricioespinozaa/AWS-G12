"""Cargas por periodo (F0005 fase B): la Administradora sube los CSV exportados de un periodo nuevo.

Flujo: subir → vista previa (nada se escribe en raw) → confirmar o descartar. Al confirmar, los datos se SUMAN
a lo existente (nunca se borra) y queda una versión nueva; la respuesta vuelve de inmediato y la consolidación
(F0006) corre en segundo plano: recalcula los pacientes afectados, suma las noches nuevas al histórico y estima la
espera a la nueva fecha de corte. La app sigue su avance en /api/nocturno/estado. Requiere RDS.
"""
from __future__ import annotations

import base64
import binascii
import shutil
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from priorizacion import archivos, config

from .. import estado as E
from ..seguridad import Persona, administradora
from ..serializacion import a_json

router = APIRouter()
MAX_CARGA = 20 * 1024 * 1024


class ArchivoIn(BaseModel):
    nombre: str
    contenido_base64: str


class CargaIn(BaseModel):
    periodo_desde: str | None = None
    periodo_hasta: str | None = None
    archivos: list[ArchivoIn]


def _conexion():
    if not config.usa_rds():
        raise HTTPException(409, "Las cargas por periodo requieren la base de datos (RDS). En modo local los datos "
                                 "se leen de los CSV de HLF_DATA_DIR.")
    from db.conexion import conectar
    return conectar()


def _fecha_opcional(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise HTTPException(422, f"Fecha inválida: {valor}")


def _a_json_carga(c: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in c.items()}


@router.get("/api/cargas")
def historial():
    from db import carga
    with _conexion() as conn:
        return [_a_json_carga(c) for c in carga.historial(conn)]


@router.post("/api/cargas")
def subir(c: CargaIn, quien: Persona = Depends(administradora)):
    from db import carga
    periodo = (_fecha_opcional(c.periodo_desde), _fecha_opcional(c.periodo_hasta))
    if periodo[0] and periodo[1] and periodo[1] < periodo[0]:
        raise HTTPException(422, "El periodo termina antes de empezar.")
    if not c.archivos:
        raise HTTPException(422, "Sube al menos un archivo CSV.")
    contenidos: dict[str, bytes] = {}
    for a in c.archivos:
        try:
            contenidos[a.nombre] = base64.b64decode(a.contenido_base64.split(",")[-1], validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, f"{a.nombre}: no viene en base64 válido.")
    if sum(len(v) for v in contenidos.values()) > MAX_CARGA:
        raise HTTPException(413, "La carga supera 20 MB.")
    try:
        carpeta = archivos.carpeta_temporal(contenidos)
    except archivos.ErrorArchivo as e:
        raise HTTPException(422, str(e))
    try:
        with _conexion() as conn:
            previa = carga.vista_previa(conn, carpeta, periodo, cargado_por=quien.id_usuario)
            uri = archivos.guardar_carga(previa["id_carga"], contenidos)
            carga.registrar_ubicacion(conn, previa["id_carga"], uri)
    except carga.ErrorCarga as e:
        raise HTTPException(409, str(e))
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
    return a_json({**previa, "archivos": sorted(contenidos)})


@router.get("/api/cargas/{id_carga}")
def detalle(id_carga: int):
    from db import carga
    with _conexion() as conn:
        fila = next((c for c in carga.historial(conn) if c["id_carga"] == id_carga), None)
        if fila is None:
            raise HTTPException(404, f"No existe la carga {id_carga}")
        return {**_a_json_carga(fila), "cambios": carga.cambios_de_carga(conn, id_carga, limite=300)}


@router.post("/api/cargas/{id_carga}/confirmar")
def confirmar(id_carga: int):
    from db import carga
    E.exigir_sin_recalculo()
    with _conexion() as conn:
        fila = next((c for c in carga.historial(conn) if c["id_carga"] == id_carga), None)
        if fila is None:
            raise HTTPException(404, f"No existe la carga {id_carga}")
        if not fila["uri_archivos"]:
            raise HTTPException(409, "La carga no tiene archivos guardados: súbela de nuevo.")
        carpeta = archivos.recuperar_carga(fila["uri_archivos"])
        try:
            resultado = carga.aplicar_incremental(conn, id_carga, carpeta)
        except carga.ErrorValidacion as e:
            raise HTTPException(422, {"mensaje": "La carga tiene errores", "errores": [p.a_dict() for p in e.problemas]})
        except carga.ErrorCarga as e:
            raise HTTPException(409, str(e))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)
    # Los datos nuevos ya están en raw: la consolidación corre en segundo plano (recarga el repositorio primero)
    E.consolidar_en_segundo_plano("carga", resultado["pacientes_afectados"], resultado["id_carga"], recargar=True)
    return a_json({**resultado, "recalculo": "en_curso"})


@router.post("/api/cargas/{id_carga}/descartar")
def descartar(id_carga: int):
    from db import carga
    with _conexion() as conn:
        try:
            carga.descartar(conn, id_carga)
        except carga.ErrorCarga as e:
            raise HTTPException(409, str(e))
    return {"ok": True}


@router.get("/api/cargas/{id_carga}/archivos/{nombre}")
def descargar(id_carga: int, nombre: str):
    from db import carga
    with _conexion() as conn:
        fila = next((c for c in carga.historial(conn) if c["id_carga"] == id_carga), None)
    if fila is None or not fila["uri_archivos"]:
        raise HTTPException(404, f"No hay archivos para la carga {id_carga}")
    try:
        contenido = archivos.leer_archivo_carga(fila["uri_archivos"], nombre)
    except archivos.ErrorArchivo as e:
        raise HTTPException(404, str(e))
    return Response(contenido, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="carga{id_carga}_{nombre}"'})
