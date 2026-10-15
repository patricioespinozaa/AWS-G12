import os
import anthropic



load_dotenv()

AWI = os.getenv("ANTHROPIC_WORKSPACE_ID")


# El SDK envía el header anthropic-version automáticamente.
MODEL = os.environ["ANTHROPIC_MODEL"]          # modelo habilitado en tu workspace
PROMPT_VERSION = "copiloto-le-v0.1"            # versiona cada cambio del prompt
SALT_PSEUDONIMO = os.environ["SALT_PSEUDONIMO"]  # secreto para hashear RUT

def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        # Scoping del proyecto vía workspace, según la configuración de tu plataforma
        default_headers={
            "anthropic-workspace-id": os.environ["ANTHROPIC_WORKSPACE_ID"],
        },
        max_retries=3,
        timeout=120.0,
    )