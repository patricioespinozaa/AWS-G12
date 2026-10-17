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

# "Hoy" del dataset sintético
FECHA_REFERENCIA = date(2026, 10, 13)

# IA generativa (opcional). Sin estas variables, las explicaciones usan la plantilla determinista.
LLM_PROVEEDOR = os.environ.get("LLM_PROVEEDOR", "").lower()          # "bedrock" para activar
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-opus-5-5")
