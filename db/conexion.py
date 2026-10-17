"""Conexión a PostgreSQL. Las credenciales nunca van en el código ni en el repositorio.

Orden de resolución:
1. HLF_DATABASE_URL, por ejemplo postgresql://usuario:clave@host:5432/hlf
2. HLF_DB_SECRET_ID: secreto de AWS Secrets Manager (el que crea RDS con --manage-master-user-password).
   Ese secreto solo trae usuario y clave, así que además se necesita HLF_DB_HOST (y opcionalmente
   HLF_DB_PORT, HLF_DB_NAME). Requiere boto3 y credenciales AWS.
3. Variables estándar de libpq: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE.

Fuera de localhost se exige SSL (sslmode=require) salvo que la URL diga otra cosa.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import quote, urlparse

import psycopg

LOCALES = {"localhost", "127.0.0.1", "::1", ""}


class ErrorConfiguracion(RuntimeError):
    pass


def _url_desde_secreto(secret_id: str) -> str:
    try:
        import boto3
    except ImportError as e:
        raise ErrorConfiguracion("HLF_DB_SECRET_ID requiere boto3: pip install boto3") from e
    host = os.environ.get("HLF_DB_HOST")
    if not host:
        raise ErrorConfiguracion("Con HLF_DB_SECRET_ID hay que definir también HLF_DB_HOST (endpoint de RDS)")
    cliente = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION"))
    secreto = json.loads(cliente.get_secret_value(SecretId=secret_id)["SecretString"])
    puerto = os.environ.get("HLF_DB_PORT", secreto.get("port", 5432))
    base = os.environ.get("HLF_DB_NAME", secreto.get("dbname", "hlf"))
    return (f"postgresql://{quote(secreto['username'], safe='')}:{quote(secreto['password'], safe='')}"
            f"@{host}:{puerto}/{base}")


def url_conexion() -> str:
    if url := os.environ.get("HLF_DATABASE_URL"):
        return url
    if secret_id := os.environ.get("HLF_DB_SECRET_ID"):
        return _url_desde_secreto(secret_id)
    if os.environ.get("PGHOST"):
        return ""          # libpq toma PGHOST, PGUSER, PGPASSWORD, etc.
    raise ErrorConfiguracion(
        "No hay conexión configurada. Define HLF_DATABASE_URL, o HLF_DB_SECRET_ID + HLF_DB_HOST, o PGHOST/PGUSER/...")


def _host(url: str) -> str:
    if not url:
        return os.environ.get("PGHOST", "")
    return urlparse(url).hostname or ""


def conectar(url: str | None = None) -> psycopg.Connection:
    url = url_conexion() if url is None else url
    extra = {}
    if "sslmode" not in url and _host(url) not in LOCALES and not os.environ.get("PGSSLMODE"):
        extra["sslmode"] = "require"
    return psycopg.connect(url, connect_timeout=15, application_name="hlf-db", **extra)


def describir(url: str | None = None) -> str:
    """URL sin la clave, para mostrar en pantalla."""
    url = url_conexion() if url is None else url
    if not url:
        return f"libpq PGHOST={os.environ.get('PGHOST')} PGDATABASE={os.environ.get('PGDATABASE', '')}"
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:****@", url)
