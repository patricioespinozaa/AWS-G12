"""Archivos que suben las personas: exámenes externos del canal y CSV de las cargas por periodo (F0005).

En AWS van a S3 (bucket del proyecto, cifrado y versionado); en modo local, a data/processed/. La base guarda
solo la URI y el sha256: nunca el contenido.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import config

TIPOS_EVIDENCIA = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


class ErrorArchivo(ValueError):
    pass


@dataclass(frozen=True)
class ArchivoGuardado:
    uri: str             # s3://bucket/clave, o el nombre del archivo en disco local
    sha256: str
    tipo_mime: str
    nombre: str


def _nombre_seguro(nombre: str) -> str:
    base = Path(nombre).name
    limpio = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if not limpio or limpio.startswith("."):
        raise ErrorArchivo(f"Nombre de archivo inválido: {nombre!r}")
    return limpio


def _s3():
    import boto3
    return boto3.client("s3", region_name=config.AWS_REGION)


def _usa_s3() -> bool:
    return bool(config.S3_BUCKET)


def guardar_evidencia(id_paciente: str, nombre: str, contenido: bytes) -> ArchivoGuardado:
    nombre = _nombre_seguro(nombre)
    tipo = TIPOS_EVIDENCIA.get(Path(nombre).suffix.lower())
    if tipo is None:
        raise ErrorArchivo(f"Tipo de archivo no admitido: {nombre}. Se aceptan PDF, JPG y PNG")
    huella = hashlib.sha256(contenido).hexdigest()
    if _usa_s3():
        clave = f"{config.S3_PREFIJO}/canal/evidencias/{id_paciente}/{huella[:16]}-{nombre}"
        _s3().put_object(Bucket=config.S3_BUCKET, Key=clave, Body=contenido, ContentType=tipo,
                         Metadata={"sha256": huella})
        return ArchivoGuardado(f"s3://{config.S3_BUCKET}/{clave}", huella, tipo, nombre)
    config.EVIDENCIA_DIR.mkdir(parents=True, exist_ok=True)
    local = f"{id_paciente}_{nombre}"
    (config.EVIDENCIA_DIR / local).write_bytes(contenido)
    return ArchivoGuardado(local, huella, tipo, nombre)


# -- Cargas por periodo ---------------------------------------------------------------------------------
def guardar_carga(id_carga: int, archivos: dict[str, bytes]) -> str:
    """Guarda los CSV originales de una carga. Devuelve dónde quedaron (prefijo S3 o carpeta local)."""
    nombres = {_nombre_seguro(n): c for n, c in archivos.items()}
    if _usa_s3():
        prefijo = f"{config.S3_PREFIJO}/cargas/{id_carga}"
        cliente = _s3()
        for nombre, contenido in nombres.items():
            cliente.put_object(Bucket=config.S3_BUCKET, Key=f"{prefijo}/{nombre}", Body=contenido,
                               ContentType="text/csv", Metadata={"sha256": hashlib.sha256(contenido).hexdigest()})
        return f"s3://{config.S3_BUCKET}/{prefijo}/"
    carpeta = config.CARGAS_DIR / str(id_carga)
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in nombres.items():
        (carpeta / nombre).write_bytes(contenido)
    return str(carpeta)


def carpeta_temporal(archivos: dict[str, bytes]) -> Path:
    """Escribe los CSV en una carpeta temporal para validarlos (db.carga lee desde una carpeta)."""
    carpeta = Path(tempfile.mkdtemp(prefix="hlf_carga_"))
    for nombre, contenido in archivos.items():
        (carpeta / _nombre_seguro(nombre)).write_bytes(contenido)
    return carpeta


def recuperar_carga(uri: str) -> Path:
    """Copia los CSV de una carga ya guardada a una carpeta temporal, para confirmarla."""
    if uri.startswith("s3://"):
        bucket, prefijo = uri[5:].split("/", 1)
        cliente = _s3()
        carpeta = Path(tempfile.mkdtemp(prefix="hlf_carga_"))
        for pagina in cliente.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefijo):
            for obj in pagina.get("Contents", []):
                nombre = Path(obj["Key"]).name
                if nombre.endswith(".csv"):
                    (carpeta / nombre).write_bytes(cliente.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read())
        return carpeta
    origen = Path(uri)
    carpeta = Path(tempfile.mkdtemp(prefix="hlf_carga_"))
    for archivo in origen.glob("*.csv"):
        shutil.copy(archivo, carpeta / archivo.name)
    return carpeta


def leer_archivo_carga(uri: str, nombre: str) -> bytes:
    nombre = _nombre_seguro(nombre)
    if uri.startswith("s3://"):
        bucket, prefijo = uri[5:].split("/", 1)
        return _s3().get_object(Bucket=bucket, Key=f"{prefijo.rstrip('/')}/{nombre}")["Body"].read()
    ruta = Path(uri) / nombre
    if not ruta.is_file():
        raise ErrorArchivo(f"No existe {nombre} en la carga")
    return ruta.read_bytes()
