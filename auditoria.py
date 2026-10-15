import hashlib, json, datetime
from pathlib import Path

LOG = Path("auditoria.jsonl")

def _escribir(registro: dict):
    registro["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")

def hash_obj(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()

def log_llamada(alerta_id, resp, model, prompt_version):
    _escribir({"tipo": "llamada_modelo", "alerta_id": alerta_id,
               "request_id": getattr(resp, "_request_id", None),
               "model": model, "prompt_version": prompt_version,
               "stop_reason": resp.stop_reason,
               "usage": resp.usage.model_dump()})

def log_tool(alerta_id, nombre, args, resultado):
    _escribir({"tipo": "tool", "alerta_id": alerta_id, "tool": nombre,
               "args": args, "hash_resultado": hash_obj(resultado)})

def log_analisis(alerta_id, alerta, analisis):
    _escribir({"tipo": "analisis_ia", "alerta_id": alerta_id,
               "hash_alerta": hash_obj(alerta), "analisis": analisis})

def registrar_decision_medica(alerta_id, medico_id, decision, prioridad_final, comentario=""):
    """Se llama desde la bandeja de revisión. Esta es la parte legalmente crítica."""
    _escribir({"tipo": "decision_medica", "alerta_id": alerta_id, "medico_id": medico_id,
               "decision": decision,  # aceptada | modificada | rechazada
               "prioridad_final": prioridad_final, "comentario": comentario})