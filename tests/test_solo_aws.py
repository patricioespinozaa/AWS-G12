"""Regla del hackatón (F0008): solo IA del ecosistema AWS.

Falla si el código, las dependencias o la configuración introducen un SDK, un endpoint o una clave de un proveedor
de IA fuera de AWS. Los modelos se invocan por Amazon Bedrock (boto3) con credenciales IAM; un ID de modelo de
Bedrock como `us.anthropic.claude-…` está permitido porque se invoca dentro de Bedrock.
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETAS = ["api", "priorizacion", "db", "servicios", "scripts", "infra/stacks", "infra/config", "infra/app.py",
            "web/src", "docker", "requirements", "requirements.txt", "web/package.json", ".github"]
EXTENSIONES = {".py", ".ts", ".tsx", ".js", ".json", ".txt", ".sh", ".yml", ".yaml", ".toml", ""}
PROHIBIDOS = [
    (r"^\s*(?:import|from)\s+(?:anthropic|openai|google\.generativeai|google\.genai|mistralai|cohere|groq)\b",
     "SDK de un proveedor de IA externo"),
    (r"(?i)api\.anthropic\.com|api\.openai\.com|generativelanguage\.googleapis\.com|api\.mistral\.ai|api\.cohere\.",
     "endpoint de IA fuera de AWS"),
    (r"(?:ANTHROPIC|OPENAI|GEMINI|GOOGLE|MISTRAL|COHERE|GROQ)_API_KEY", "clave de API de un proveedor externo"),
    (r"(?i)AnthropicBedrock|anthropic\[bedrock\]|\"@anthropic-ai/|\"openai\"\s*:", "SDK de proveedor (usar boto3)"),
]
DEPENDENCIAS = re.compile(r"(?im)^\s*(anthropic|openai|google-generativeai|google-genai|mistralai|cohere|groq|"
                          r"langchain-openai|langchain-anthropic)\b")


def _archivos():
    for nombre in CARPETAS:
        ruta = RAIZ / nombre
        if ruta.is_file():
            yield ruta
        elif ruta.is_dir():
            for p in ruta.rglob("*"):
                if p.is_file() and p.suffix in EXTENSIONES and "node_modules" not in p.parts \
                        and "__pycache__" not in p.parts:
                    yield p


def test_sin_sdks_endpoints_ni_claves_de_ia_externa():
    hallazgos = []
    for archivo in _archivos():
        if archivo.name == Path(__file__).name:
            continue
        texto = archivo.read_text(encoding="utf-8", errors="ignore")
        for patron, motivo in PROHIBIDOS:
            for m in re.finditer(patron, texto, re.MULTILINE):
                linea = texto.count("\n", 0, m.start()) + 1
                hallazgos.append(f"{archivo.relative_to(RAIZ)}:{linea}: {motivo} ({m.group(0).strip()})")
    assert not hallazgos, "IA fuera del ecosistema AWS:\n" + "\n".join(hallazgos)


def test_dependencias_sin_sdks_de_proveedores():
    for req in (RAIZ / "requirements").glob("*.txt"):
        assert not DEPENDENCIAS.search(req.read_text(encoding="utf-8")), f"{req.name} incluye un SDK de IA externo"
    assert "boto3" in (RAIZ / "requirements" / "base.txt").read_text(encoding="utf-8")


def test_el_modelo_configurado_es_de_bedrock():
    from priorizacion import config
    # Perfiles de inferencia (us./global./eu./apac.) o IDs de modelo base de Bedrock
    assert re.match(r"^(?:(?:us|eu|apac|global)\.)?(?:anthropic|amazon|meta|mistral|cohere)\.", config.BEDROCK_MODEL_ID)
