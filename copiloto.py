import json
from pathlib import Path
from config import get_client, MODEL, PROMPT_VERSION
from prompts import SYSTEM_PROMPT
from herramientas import TOOLS, ejecutar_tool
import auditoria

client = get_client()

def _system_blocks() -> list[dict]:
    glosarios = "\n\n".join(p.read_text(encoding="utf-8") for p in sorted(Path("docs").glob("*.md")))
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        # Caché: herramientas + prompt + glosario se reutilizan entre alertas (menor costo y latencia)
        {"type": "text", "text": glosarios, "cache_control": {"type": "ephemeral"}},
    ]

SYSTEM = _system_blocks()


def analizar_alerta(repo, alerta: dict, max_turnos: int = 8) -> dict:
    alerta_id = alerta["alerta_id"]
    messages = [{
        "role": "user",
        "content": "Analiza la siguiente alerta de lista de espera:\n\n"
                   + json.dumps(alerta, ensure_ascii=False, indent=2),
    }]

    for _ in range(max_turnos):
        resp = client.messages.create(
            model=MODEL, max_tokens=4096, system=SYSTEM,
            tools=TOOLS, messages=messages,
        )
        auditoria.log_llamada(alerta_id, resp, MODEL, PROMPT_VERSION)

        if resp.stop_reason != "tool_use":
            # El modelo respondió sin usar registrar_analisis: se le exige la entrega estructurada
            messages += [{"role": "assistant", "content": resp.content},
                         {"role": "user", "content": "Entrega el resultado usando registrar_analisis."}]
            continue

        messages.append({"role": "assistant", "content": resp.content})
        resultados = []
        for bloque in resp.content:
            if bloque.type != "tool_use":
                continue
            if bloque.name == "registrar_analisis":
                analisis = bloque.input | {"_meta": {"model": MODEL,
                                                    "prompt_version": PROMPT_VERSION,
                                                    "estado": "pendiente_revision_medica"}}
                auditoria.log_analisis(alerta_id, alerta, analisis)
                return analisis
            salida = ejecutar_tool(repo, bloque.name, bloque.input)
            auditoria.log_tool(alerta_id, bloque.name, bloque.input, salida)
            resultados.append({"type": "tool_result", "tool_use_id": bloque.id, "content": salida})
        messages.append({"role": "user", "content": resultados})

    raise RuntimeError(f"Alerta {alerta_id}: no se obtuvo análisis en {max_turnos} turnos")

def _contexto_precargado(repo, perfiles_por_id, dq, alerta):
    corte = pd.Timestamp(alerta["fecha_corte"]).date()
    p = perfiles_por_id[alerta["id_paciente"]]
    perfil = p.model_dump(mode="json")
    # La IA solo ve lo que el hospital sabía a la fecha de corte
    perfil["eventos_clinicos"] = [e for e in perfil["eventos_clinicos"] if e["fecha_evento"] <= str(corte)]
    perfil["mediciones"] = [m | {"id_medicion": id_medicion(p.id_paciente, m["fecha_medicion"],
                                                            m["tipo_medicion"], m["valor"])}
                            for m in perfil["mediciones"] if m["fecha_medicion"] <= str(corte)]
    perfil["citaciones"] = sorted([c for c in perfil["citaciones"] if c["fecha_cita"] <= str(corte)],
                                  key=lambda c: c["fecha_cita"])
    if str(corte) < "2026-10-13":
        perfil["lista_espera"]["estado"] = "desconocido_a_la_fecha"
    edad = perfil["paciente"]["edad"]
    perfil["paciente"].pop("nombre_fantasia")   # minimización: el modelo no necesita el nombre
    return {
        "alerta_motor_reglas": alerta,
        "perfil": perfil,
        "problemas_calidad_datos": dq[dq.id_paciente == p.id_paciente].to_dict("records"),
        "cohorte": repo.cohorte(alerta["cie10"], edad - 10, edad + 10, pd.Timestamp(corte),
                                excluir_id=p.id_paciente),
}