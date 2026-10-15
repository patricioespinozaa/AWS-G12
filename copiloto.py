from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from config import MAX_TOKENS

import pandas as pd

import auditoria
from config import MODEL, PROMPT_VERSION, get_client
from herramientas import TOOLS, TOOLS_BARRIDO, TOOL_REGISTRAR, ejecutar_tool, _sanitizar
from prompts import SYSTEM_PROMPT

try:
    from config import FECHA_REFERENCIA
except ImportError:
    FECHA_REFERENCIA = "2026-10-13"


FORZAR_REGISTRO = {"type": "tool", "name": TOOL_REGISTRAR["name"]}
RANGO_PRIORIDAD = {"baja": 0, "media": 1, "alta": 2, "critica": 3}
_PATRON_ID = re.compile(r"^(?:EV|MED|CT|IC)-[A-Za-z0-9-]+$")
# Documentos de docs/ que no son glosario: contienen datos, conteos o decisiones internas.
DOCS_EXCLUIDOS = {"decisiones.md", "informe_calidad.md"}
DIR_BATCHES = Path("batches")   # manifiestos de barrido (agregar a .gitignore)


# ---------------------------------------------------------------------------
# Infraestructura
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _cliente():
    return get_client()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _sha256(value: Any) -> str:
    texto = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _system() -> tuple[list[dict], str, list[str]]:
    """Bloques de sistema, huella del prompt efectivo (sistema + tools) y docs cargados."""
    docs = Path(__file__).resolve().parent / "docs"
    if not docs.is_dir():
        docs = Path("docs")
    archivos = [p for p in sorted(docs.glob("*.md")) if p.name not in DOCS_EXCLUIDOS]
    glosario = "\n\n".join(p.read_text(encoding="utf-8") for p in archivos)
    bloques = [{"type": "text", "text": SYSTEM_PROMPT}]
    if glosario.strip():
        bloques.append({"type": "text", "text": "# Glosario institucional\n\n" + glosario,
                        "cache_control": {"type": "ephemeral"}})
    return bloques, _sha256({"system": bloques, "tools": TOOLS}), [p.name for p in archivos]


def _log_error_batch(alerta_id: str, resultado: str) -> None:
    log = getattr(auditoria, "log_error_batch", None)
    if log:
        log(alerta_id, resultado)
    else:
        auditoria._escribir({"tipo": "error_batch", "alerta_id": alerta_id,
                             "resultado": resultado})


# ---------------------------------------------------------------------------
# Utilidades de dominio
# ---------------------------------------------------------------------------
def _corte(alerta: dict) -> pd.Timestamp:
    fecha = pd.Timestamp(alerta["fecha_corte"])
    if pd.isna(fecha):
        raise ValueError("fecha_corte no puede ser NaT")
    return fecha.normalize()


def _antes_de_referencia(corte: pd.Timestamp) -> bool:
    return corte < pd.Timestamp(FECHA_REFERENCIA)


def _fecha_permitida(valor: Any, corte: pd.Timestamp) -> bool:
    if valor is None or valor == "":
        return False  # sin fecha verificable no puede asumirse que existía
    try:
        fecha = pd.Timestamp(valor)
    except (TypeError, ValueError, OverflowError):
        return False
    return not pd.isna(fecha) and fecha.normalize() <= corte


def _ids_citables(obj: Any, acc: set[str] | None = None) -> set[str]:
    """Recolecta los registro_id (EV-, MED-, CT-, IC-) presentes en un contexto."""
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for v in obj.values():
            _ids_citables(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _ids_citables(v, acc)
    elif isinstance(obj, str) and _PATRON_ID.match(obj):
        acc.add(obj)
    return acc


def _consultar(repo: Any, nombre: str, args: dict, alerta: dict) -> str:
    """Única puerta de acceso a datos: restricciones impuestas desde la alerta."""
    return ejecutar_tool(repo, nombre, args,
                         pid_alerta=alerta["id_paciente"], corte=_corte(alerta))


# ---------------------------------------------------------------------------
# Verificación y cierre (no modifica el contenido del modelo: solo lo marca)
# ---------------------------------------------------------------------------
def _verificar(alerta: dict, analisis: dict, ids_citables: set[str] | None) -> dict:
    requeridos = TOOL_REGISTRAR["input_schema"]["required"]
    faltantes = [c for c in requeridos if c not in analisis]

    citados: set[str] = set()
    documentados_sin_cita: list[str] = []
    for h in analisis.get("hallazgos") or []:
        ids = [i for i in (h.get("registro_ids") or []) if isinstance(i, str)]
        citados.update(ids)
        if h.get("tipo") == "documentado" and not ids:
            documentados_sin_cita.append(str(h.get("hallazgo", ""))[:160])
    for e in analisis.get("linea_tiempo_relevante") or []:
        if isinstance(e.get("registro_id"), str):
            citados.add(e["registro_id"])
    for i in analisis.get("inconsistencias_datos") or []:
        citados.update(x for x in (i.get("registro_ids") or []) if isinstance(x, str))

    no_verificables = None if ids_citables is None else sorted(citados - ids_citables)

    discrepancias: list[str] = []
    sugerida, motor = analisis.get("prioridad_sugerida"), alerta.get("prioridad_calculada")
    if sugerida in RANGO_PRIORIDAD and motor in RANGO_PRIORIDAD:
        declarado = analisis.get("acuerdo_con_motor_reglas")
        real = sugerida == motor
        if isinstance(declarado, bool) and declarado != real:
            discrepancias.append(f"acuerdo_con_motor_reglas={declarado}, pero la IA sugiere "
                                 f"'{sugerida}' y el motor calculó '{motor}'.")
        if motor == "critica" and sugerida != "critica":
            discrepancias.append("El motor calculó 'critica' y la IA sugiere una prioridad "
                                 "menor: revisar antes que el resto.")

    return {
        "campos_faltantes": faltantes,
        "citas_verificadas": ids_citables is not None,
        "citas_no_verificables": no_verificables,
        "documentados_sin_cita": documentados_sin_cita,
        "discrepancias_motor": discrepancias,
        "requiere_atencion": bool(faltantes or documentados_sin_cita or discrepancias
                                  or no_verificables or ids_citables is None),
    }


def _finalizar(alerta: dict, bloque: Any, *, ids_citables: set[str] | None,
               meta_llamada: dict) -> dict:
    if not isinstance(bloque.input, dict):
        raise ValueError("registrar_analisis debe devolver un objeto JSON")
    # Los metadatos son propiedad del backend: se descarta cualquier clave '_' del modelo.
    analisis = {k: v for k, v in bloque.input.items() if not str(k).startswith("_")}
    verificacion = _verificar(alerta, analisis, ids_citables)
    analisis["_meta"] = {
        **meta_llamada,
        "fecha_corte": str(_corte(alerta).date()),
        "estado": "pendiente_revision_medica",
        "verificacion": verificacion,
    }
    auditoria.log_analisis(alerta["alerta_id"], alerta, analisis)
    return analisis


# ---------------------------------------------------------------------------
# Modo reactivo
# ---------------------------------------------------------------------------
def analizar_alerta(repo: Any, alerta: dict, max_turnos: int = 8) -> dict:
    """Ejecuta consultas restringidas y exige un registro estructurado."""
    if max_turnos < 1:
        raise ValueError("max_turnos debe ser mayor que cero")
    alerta_id = alerta["alerta_id"]
    _corte(alerta), alerta["id_paciente"]          # validar campos requeridos
    system, huella, docs = _system()

    ids_citables = _ids_citables(alerta)           # IDs del motor de reglas
    messages: list[dict] = [{
        "role": "user",
        "content": "Analiza esta alerta de lista de espera usando exclusivamente evidencia "
                   "disponible a la fecha de corte. Registra el resultado con "
                   "registrar_analisis.\n\n" + _json(_sanitizar(alerta)),
    }]
    request_ids: list[str] = []

    for turno in range(max_turnos):
        forzar = {"tool_choice": FORZAR_REGISTRO} if turno == max_turnos - 1 else {}
        resp = _cliente().messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=system,
                                          tools=TOOLS, messages=messages, **forzar)
        auditoria.log_llamada(alerta_id, resp, MODEL, PROMPT_VERSION)
        if rid := getattr(resp, "_request_id", None):
            request_ids.append(rid)
        if resp.stop_reason == "max_tokens":
            raise RuntimeError(f"Alerta {alerta_id}: respuesta truncada (max_tokens="
                               f"{MAX_TOKENS}); no se acepta un registro incompleto.")

        messages.append({"role": "assistant", "content": resp.content})
        usos = [b for b in resp.content if b.type == "tool_use"]

        registro = next((b for b in usos if b.name == TOOL_REGISTRAR["name"]), None)
        if registro is not None:   # entrega final: no se ejecutan otras consultas
            return _finalizar(alerta, registro, ids_citables=ids_citables, meta_llamada={
                "model": resp.model, "prompt_version": PROMPT_VERSION,
                "system_sha256": huella, "docs_sistema": docs,
                "modo": "reactivo", "request_ids": request_ids, "turnos": turno + 1,
            })

        if not usos:
            messages.append({"role": "user",
                             "content": "Entrega el resultado con registrar_analisis."})
            continue

        resultados = []
        for b in usos:
            salida = _consultar(repo, b.name, b.input, alerta)
            auditoria.log_tool(alerta_id, b.name, b.input, salida)
            try:
                datos = json.loads(salida)
            except json.JSONDecodeError:
                datos = {}
            es_error = isinstance(datos, dict) and "error" in datos
            if not es_error:
                ids_citables |= _ids_citables(datos)
            resultados.append({"type": "tool_result", "tool_use_id": b.id,
                               "content": salida, "is_error": es_error})
        messages.append({"role": "user", "content": resultados})

    raise RuntimeError(f"Alerta {alerta_id}: no se obtuvo análisis tras {max_turnos} turnos")


# ---------------------------------------------------------------------------
# Contexto precargado (modo barrido)
# ---------------------------------------------------------------------------
def _perfil_legacy(perfiles_por_id: Any, alerta: dict, corte: pd.Timestamp) -> dict:
    paciente = perfiles_por_id[alerta["id_paciente"]]
    perfil = paciente.model_dump(mode="json") if hasattr(paciente, "model_dump") else dict(paciente)
    perfil = json.loads(_json(perfil))             # copia profunda
    for coleccion, campo in (("eventos_clinicos", "fecha_evento"),
                             ("mediciones", "fecha_medicion"),
                             ("citaciones", "fecha_cita")):
        perfil[coleccion] = [e for e in perfil.get(coleccion, [])
                             if _fecha_permitida(e.get(campo), corte)]
    perfil["citaciones"].sort(key=lambda e: e["fecha_cita"])
    # El estado es una fotografía a la fecha de referencia (§4).
    espera = perfil.get("lista_espera")
    if isinstance(espera, dict) and _antes_de_referencia(corte):
        fecha_estado = espera.get("fecha_estado") or espera.get("fecha_actualizacion_estado")
        if not _fecha_permitida(fecha_estado, corte):
            espera["estado"] = "desconocido_a_la_fecha"
    return _sanitizar(perfil)


def _calidad_por_paciente(dq: Any, pid: str, ids_visibles: set[str],
                          corte: pd.Timestamp) -> list[dict]:
    """Solo hallazgos DQ sobre registros visibles al corte y sin depender del futuro."""
    if dq is None:
        return []
    if not isinstance(dq, pd.DataFrame) or "id_paciente" not in dq.columns:
        raise TypeError("dq debe ser DataFrame con columna id_paciente")
    salida = []
    for fila in dq.loc[dq["id_paciente"] == pid].to_dict("records"):
        if _antes_de_referencia(corte) and fila.get("codigo") == "DQ-06":
            continue                               # depende del estado al 13-10
        ids = fila.get("registro_ids") or []
        ids = [ids] if isinstance(ids, str) else list(ids)
        if not ids or not set(ids) <= ids_visibles:
            continue
        salida.append({k: (None if not isinstance(v, (list, dict, tuple)) and pd.isna(v) else v)
                       for k, v in fila.items()})
    return _sanitizar(salida)


def _contexto_precargado(repo: Any, alerta: dict, *, perfiles_por_id: Any = None,
                         dq: Any = None) -> dict:
    corte = _corte(alerta)
    if perfiles_por_id is None:
        lt = json.loads(_consultar(repo, "obtener_linea_tiempo",
                                   {"pid": alerta["id_paciente"]}, alerta))
        if "error" in lt:
            raise RuntimeError(lt["error"])
        edad = lt["perfil"]["edad"]
        contexto = {"alerta": _sanitizar(alerta), "linea_tiempo": lt}
    else:
        perfil = _perfil_legacy(perfiles_por_id, alerta, corte)
        edad = perfil["paciente"]["edad"]
        contexto = {"alerta": _sanitizar(alerta), "perfil": perfil}

    contexto["problemas_calidad_datos"] = _calidad_por_paciente(
        dq, alerta["id_paciente"], _ids_citables(contexto), corte)
    contexto["cohorte"] = json.loads(_consultar(repo, "obtener_cohorte", {
        "grupo_cie10": alerta["cie10"],
        "edad_min": max(0, edad - 10), "edad_max": min(120, edad + 10)}, alerta))
    if "especialidad" in alerta:
        contexto["capacidad_box"] = json.loads(_consultar(
            repo, "obtener_capacidad_box", {"especialidad": alerta["especialidad"]}, alerta))
    return contexto


# ---------------------------------------------------------------------------
# Modo barrido (Batches API)
# ---------------------------------------------------------------------------
def _ruta_manifiesto(batch_id: str) -> Path:
    return DIR_BATCHES / f"{batch_id}.json"


def lanzar_barrido(repo: Any, alertas: list[dict], *, perfiles_por_id: Any = None,
                   dq: Any = None) -> str:
    """Envía a Batches API las alertas con contexto precomputado y guarda un manifiesto."""
    if not alertas:
        raise ValueError("No hay alertas para enviar")
    ids = [a["alerta_id"] for a in alertas]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", x) for x in ids):
        raise ValueError("alerta_id duplicado o inválido para custom_id")

    system, huella, docs = _system()
    requests, manifiesto = [], {}
    for alerta in alertas:
        try:
            contexto = _contexto_precargado(repo, alerta, perfiles_por_id=perfiles_por_id, dq=dq)
        except Exception as e:                     # una alerta no detiene el barrido
            _log_error_batch(alerta["alerta_id"],
                             f"contexto_no_disponible: {type(e).__name__}: {e}")
            continue
        manifiesto[alerta["alerta_id"]] = {
            "ids_citables": sorted(_ids_citables(contexto)),
            "contexto_sha256": _sha256(contexto),
        }
        requests.append({"custom_id": alerta["alerta_id"], "params": {
            "model": MODEL, "max_tokens": MAX_TOKENS, "system": system,
            "tools": TOOLS_BARRIDO, "tool_choice": FORZAR_REGISTRO,
            "messages": [{"role": "user", "content":
                          "Analiza esta alerta con el contexto a fecha de corte. "
                          "No hay herramientas de consulta. Registra la recomendación "
                          "para revisión médica.\n\n" + _json(contexto)}],
        }})
    if not requests:
        raise RuntimeError("Ninguna alerta tuvo contexto válido; no se envió el batch")

    batch = _cliente().messages.batches.create(requests=requests)
    DIR_BATCHES.mkdir(parents=True, exist_ok=True)
    _ruta_manifiesto(batch.id).write_text(_json({
        "batch_id": batch.id, "model": MODEL, "prompt_version": PROMPT_VERSION,
        "system_sha256": huella, "docs_sistema": docs, "alertas": manifiesto,
    }), encoding="utf-8")
    return batch.id


def recoger_barrido(batch_id: str, alertas_por_id: dict) -> list[dict]:
    """Recupera resultados de un batch terminado; tolera resultados fallidos."""
    estado = _cliente().messages.batches.retrieve(batch_id).processing_status
    if estado != "ended":
        raise RuntimeError(f"Batch {batch_id} aún en estado '{estado}'")

    ruta = _ruta_manifiesto(batch_id)
    manifiesto = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None
    if manifiesto is None:
        _log_error_batch(batch_id, "manifiesto_ausente: citas y versión no verificables")

    salidas = []
    for r in _cliente().messages.batches.results(batch_id):
        alerta = alertas_por_id.get(r.custom_id)
        if alerta is None:
            _log_error_batch(r.custom_id, "alerta_desconocida")
            continue
        if r.result.type != "succeeded":
            _log_error_batch(r.custom_id, r.result.type)
            continue
        msg = r.result.message
        if msg.stop_reason == "max_tokens":
            _log_error_batch(r.custom_id, "respuesta_truncada")
            continue
        registros = [b for b in msg.content
                     if b.type == "tool_use" and b.name == TOOL_REGISTRAR["name"]]
        if len(registros) != 1:
            _log_error_batch(r.custom_id, "registro_ausente_o_duplicado")
            continue

        info = (manifiesto or {}).get("alertas", {}).get(r.custom_id)
        salidas.append(_finalizar(
            alerta, registros[0],
            ids_citables=set(info["ids_citables"]) if info else None,
            meta_llamada={
                "model": msg.model,
                # Versión con la que se LANZÓ el batch, no la vigente al recoger.
                "prompt_version": (manifiesto or {}).get("prompt_version", "desconocida"),
                "system_sha256": (manifiesto or {}).get("system_sha256"),
                "docs_sistema": (manifiesto or {}).get("docs_sistema"),
                "modo": "barrido", "batch_id": batch_id, "custom_id": r.custom_id,
                "contexto_sha256": info["contexto_sha256"] if info else None,
            }))
    return salidas