"""Buzón de exportaciones: donde dejan el HLF (o un proceso automático) los CSV de cada periodo.

Cada entrega es una carpeta con los CSV del periodo y, opcionalmente, un `periodo.json` ({"desde", "hasta"}):
- AWS:   s3://<bucket>/<prefijo>/entrada/<carpeta>/
- local: <HLF_BUZON>/<carpeta>/
Las carpetas se procesan en orden de nombre (conviene nombrarlas con la fecha de cierre: 2026-09-30).

El buzón no lleva su propio registro de lo procesado: la base ya lo tiene. Una entrega cuenta como procesada
si hay una carga en raw.carga_lote con su URI de origen y los mismos archivos (sha256). Si el HLF corrige los
archivos de una carpeta, las huellas cambian y la entrega se vuelve a procesar.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from priorizacion import config

PERIODO = "periodo.json"


class ErrorBuzon(ValueError):
    pass


@dataclass(frozen=True)
class Entrega:
    nombre: str
    uri: str             # s3://bucket/prefijo/entrada/<carpeta>/ o la ruta local de la carpeta


@dataclass
class Descarga:
    entrega: Entrega
    carpeta: Path                                    # copia temporal con los CSV
    periodo: tuple[date | None, date | None]
    huellas: dict[str, str]                          # nombre → sha256 (lo que guarda raw.carga_lote.archivos)

    def limpiar(self):
        shutil.rmtree(self.carpeta, ignore_errors=True)


def _periodo(contenido: bytes | None) -> tuple[date | None, date | None]:
    if not contenido:
        return None, None
    try:
        p = json.loads(contenido)
        desde, hasta = (date.fromisoformat(p[k]) if p.get(k) else None for k in ("desde", "hasta"))
    except (ValueError, TypeError, AttributeError) as e:
        raise ErrorBuzon(f"{PERIODO} inválido: {e}")
    if desde and hasta and hasta < desde:
        raise ErrorBuzon(f"{PERIODO}: el periodo termina antes de empezar")
    return desde, hasta


def _huellas(carpeta: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(carpeta.glob("*.csv"))}


class BuzonLocal:
    def __init__(self, raiz: Path | str):
        self.raiz = Path(raiz)

    def __str__(self) -> str:
        return str(self.raiz)

    def entregas(self) -> list[Entrega]:
        if not self.raiz.is_dir():
            return []
        return [Entrega(c.name, str(c.resolve())) for c in sorted(self.raiz.iterdir())
                if c.is_dir() and any(c.glob("*.csv"))]

    def descargar(self, e: Entrega) -> Descarga:
        origen = Path(e.uri)
        carpeta = Path(tempfile.mkdtemp(prefix="hlf_buzon_"))
        for archivo in origen.glob("*.csv"):
            shutil.copy(archivo, carpeta / archivo.name)
        periodo = origen / PERIODO
        return Descarga(e, carpeta, _periodo(periodo.read_bytes() if periodo.exists() else None), _huellas(carpeta))


class BuzonS3:
    def __init__(self, bucket: str, prefijo: str, cliente=None):
        self.bucket, self.prefijo = bucket, f"{prefijo.strip('/')}/entrada/"
        self._cliente = cliente

    def __str__(self) -> str:
        return f"s3://{self.bucket}/{self.prefijo}"

    @property
    def s3(self):
        if self._cliente is None:
            import boto3
            self._cliente = boto3.client("s3", region_name=config.AWS_REGION)
        return self._cliente

    def entregas(self) -> list[Entrega]:
        nombres = []
        for pagina in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefijo,
                                                                        Delimiter="/"):
            nombres += [p["Prefix"][len(self.prefijo):].rstrip("/") for p in pagina.get("CommonPrefixes", [])]
        return [Entrega(n, f"s3://{self.bucket}/{self.prefijo}{n}/") for n in sorted(nombres)]

    def descargar(self, e: Entrega) -> Descarga:
        prefijo = f"{self.prefijo}{e.nombre}/"
        carpeta = Path(tempfile.mkdtemp(prefix="hlf_buzon_"))
        periodo = None
        for pagina in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefijo):
            for obj in pagina.get("Contents", []):
                nombre = obj["Key"][len(prefijo):]
                if "/" in nombre:                    # solo el primer nivel de la carpeta
                    continue
                if nombre.endswith(".csv"):
                    (carpeta / nombre).write_bytes(self.s3.get_object(Bucket=self.bucket, Key=obj["Key"])["Body"].read())
                elif nombre == PERIODO:
                    periodo = self.s3.get_object(Bucket=self.bucket, Key=obj["Key"])["Body"].read()
        return Descarga(e, carpeta, _periodo(periodo), _huellas(carpeta))


def desde_config():
    """El buzón configurado: la carpeta HLF_BUZON si se define; si no, S3 si hay bucket; si no, ninguno."""
    if config.BUZON_LOCAL:
        return BuzonLocal(config.BUZON_LOCAL)
    if config.S3_BUCKET:
        return BuzonS3(config.S3_BUCKET, config.S3_PREFIJO)
    return None
