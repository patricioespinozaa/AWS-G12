"""Ruta de texto (F0009): RetrieveAndGenerate sobre la Knowledge Base del equipo clínico, con guardrail y filtros.

La respuesta cita los fragmentos recuperados; cada cita trae la URI S3 del documento, que se cruza con
consulta.documento_kb para dejar la fuente registrada. Sin citas no hay respuesta de texto.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from priorizacion import config
from priorizacion.explicacion import limpiar_formato

from ..comun import bedrock

# $output_format_instructions$ es obligatorio en una plantilla propia: sin él, Bedrock no devuelve las citas
VERSION_PROMPT = "rag-v2"
N_RESULTADOS = 8
PLANTILLA = """Eres un asistente para la Administradora de la lista de espera de especialidad de un hospital público. Respondes en español de Chile, de forma breve y precisa.

Usa solo la información de los resultados de búsqueda. Si no está ahí, di que no encontraste la información en los documentos. No diagnostiques, no indiques tratamientos ni anticipes la evolución de la salud de nadie. Identifica a los pacientes solo por su ID (PAC-HLF-…) y conserva las referencias entre corchetes ([EV-…], [CT-…]) de los hechos que menciones. Recuerda que la decisión de priorizar es del equipo clínico.

Responde en prosa, sin títulos ni negritas.

Resultados de búsqueda:
$search_results$

$output_format_instructions$

Pregunta: $query$"""


@dataclass
class Cita:
    s3_uri: str
    fragmento: str
    metadatos: dict


@dataclass
class RespuestaRag:
    texto: str
    citas: list[Cita] = field(default_factory=list)
    guardrail_intervino: bool = False
    latencia_ms: int = 0


_cuenta: str | None = None


def modelo_arn() -> str:
    """RetrieveAndGenerate pide el ARN del perfil de inferencia (no solo su ID)."""
    global _cuenta
    modelo = config.BEDROCK_MODEL_ID
    if modelo.startswith("arn:"):
        return modelo
    if modelo.split(".")[0] in ("us", "eu", "apac", "global"):
        if _cuenta is None:
            import boto3
            _cuenta = boto3.client("sts", region_name=config.BEDROCK_REGION).get_caller_identity()["Account"]
        return f"arn:aws:bedrock:{config.BEDROCK_REGION}:{_cuenta}:inference-profile/{modelo}"
    return f"arn:aws:bedrock:{config.BEDROCK_REGION}::foundation-model/{modelo}"


def filtro(id_paciente: str | None, especialidad: str | None) -> dict | None:
    condiciones = [{"equals": {"key": "id_paciente", "value": id_paciente}}] if id_paciente else []
    if especialidad:
        condiciones.append({"equals": {"key": "especialidad", "value": especialidad}})
    if not condiciones:
        return None
    return condiciones[0] if len(condiciones) == 1 else {"andAll": condiciones}


def responder(pregunta: str, kb_id: str, id_paciente: str | None = None, especialidad: str | None = None) -> RespuestaRag:
    busqueda: dict = {"numberOfResults": N_RESULTADOS}
    if f := filtro(id_paciente, especialidad):
        busqueda["filter"] = f
    generacion: dict = {"promptTemplate": {"textPromptTemplate": PLANTILLA},
                        "inferenceConfig": {"textInferenceConfig": {"maxTokens": config.BEDROCK_MAX_TOKENS}}}
    if config.BEDROCK_GUARDRAIL_ID:
        generacion["guardrailConfiguration"] = {"guardrailId": config.BEDROCK_GUARDRAIL_ID,
                                                "guardrailVersion": config.BEDROCK_GUARDRAIL_VERSION}
    t0 = time.perf_counter()
    r = bedrock.cliente("bedrock-agent-runtime").retrieve_and_generate(
        input={"text": pregunta},
        retrieveAndGenerateConfiguration={"type": "KNOWLEDGE_BASE", "knowledgeBaseConfiguration": {
            "knowledgeBaseId": kb_id, "modelArn": modelo_arn(),
            "retrievalConfiguration": {"vectorSearchConfiguration": busqueda},
            "generationConfiguration": generacion}})
    citas, vistas = [], set()
    for c in r.get("citations", []):
        for ref in c.get("retrievedReferences", []):
            uri = ref.get("location", {}).get("s3Location", {}).get("uri")
            texto = (ref.get("content", {}).get("text") or "").strip()
            if uri and texto and (uri, texto) not in vistas:
                vistas.add((uri, texto))
                citas.append(Cita(uri, texto, ref.get("metadata") or {}))
    return RespuestaRag(limpiar_formato(r.get("output", {}).get("text") or ""), citas,
                        r.get("guardrailAction") == "INTERVENED", round((time.perf_counter() - t0) * 1000))
