import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = os.environ["ANTHROPIC_MODEL"]           # modelo habilitado en el workspace
PROMPT_VERSION = "copiloto-le-hlf-v0.3.1"       # subir con cada cambio de prompt o tools
FECHA_REFERENCIA = "2026-10-13"                 # fotografía del campo 'estado'

# Solo se exige con datos reales (RUT). El dataset sintético no lo necesita.
SALT_PSEUDONIMO = os.getenv("SALT_PSEUDONIMO")
MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))

def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=os.environ["APIK"],
        default_headers={"anthropic-workspace-id": os.environ["ANTHROPIC_WORKSPACE_ID"]},
        max_retries=3,
        timeout=120.0,
    )  