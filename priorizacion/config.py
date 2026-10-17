"""Rutas y parámetros de entorno."""
import os
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get(
    "HLF_DATA_DIR", RAIZ / "data" / "dataset_hlf_ambulatorio" / "dataset_hlf_ambulatorio"))

# Base local del MVP (equivale a RDS/DynamoDB en AWS). data/processed/ está en .gitignore.
DB_PATH = Path(os.environ.get("HLF_DB_PATH", RAIZ / "data" / "processed" / "priorizacion.sqlite"))
EVIDENCIA_DIR = DB_PATH.parent / "evidencia_externa"

# "Hoy" del dataset sintético. Con RDS la app lo adelanta a la última fecha con datos, para que una carga
# de un periodo nuevo se vea en la bandeja (api/estado.py). F0006 lo reemplaza por el reloj de la base.
FECHA_REFERENCIA_BASE = date(2026, 10, 13)
FECHA_REFERENCIA = FECHA_REFERENCIA_BASE

# IA generativa (opcional). Sin estas variables, las explicaciones usan la plantilla determinista.
LLM_PROVEEDOR = os.environ.get("LLM_PROVEEDOR", "").lower()          # "bedrock" para activar
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-opus-5-5")

# Base de datos (F0005). Con HLF_DATABASE_URL o HLF_DB_SECRET_ID (+ HLF_DB_HOST) la app lee raw de RDS y guarda
# en los esquemas priorizacion y canal. Sin ellas, modo local: CSV + SQLite (respaldo de la demo).
DATABASE_URL = os.environ.get("HLF_DATABASE_URL", "")
DB_SECRET_ID = os.environ.get("HLF_DB_SECRET_ID", "")


def usa_rds() -> bool:
    return bool(os.environ.get("HLF_DATABASE_URL") or os.environ.get("HLF_DB_SECRET_ID"))


# Única usuaria de la plataforma (definido por el HLF): revisa propuestas, valida el canal y sube cargas.
# Hasta F0007 (autenticación) toda escritura se registra a su nombre.
USUARIA = os.environ.get("HLF_USUARIA", "administradora")

# S3 para archivos (evidencias del canal y cargas por periodo). Sin bucket, se guardan en disco local.
S3_BUCKET = os.environ.get("HLF_S3_BUCKET", "")
S3_PREFIJO = os.environ.get("HLF_S3_PREFIJO", "hlf").strip("/")
CARGAS_DIR = DB_PATH.parent / "cargas"

# Consolidación nocturna (F0006). El buzón es donde llegan las exportaciones sin intervención de la Administradora:
# en AWS, s3://<bucket>/<prefijo>/entrada/<carpeta>/; en local, la carpeta HLF_BUZON (si se define).
BUZON_LOCAL = os.environ.get("HLF_BUZON", "")
# Con errores de validación la carga queda "fallida" y se avisa; sin errores se confirma sola (=0: solo vista previa).
AUTOCONFIRMAR = os.environ.get("HLF_AUTOCONFIRMAR", "1") == "1"
# Publicar en Athena (raw y las noches tocadas de la serie) al terminar cada consolidación.
ATHENA_PUBLICAR = os.environ.get("HLF_ATHENA_PUBLICAR", "0") == "1"
