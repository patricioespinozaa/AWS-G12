from __future__ import annotations

import inspect
import json
from datetime import date, datetime
from typing import Any

PRIORIDADES = ["critica", "alta", "media", "baja"]

# Nunca deben llegar al modelo (§10.4 y §14: minimización).
CAMPOS_IDENTIFICATORIOS = {
    "nombre", "nombres", "nombre_fantasia", "apellido", "apellidos", "nombre_completo",
    "rut", "run", "telefono", "direccion", "email", "correo",
}

class RestriccionNoSoportada(RuntimeError):
    """El repositorio no permite imponer una restricción obligatoria."""


# ---------------------------------------------------------------------------
# Calculadoras clínicas (deterministas)
# ---------------------------------------------------------------------------
def cha2ds2_vasc(edad: int, sexo_femenino: bool, insuficiencia_cardiaca: bool, hta: bool,
                 diabetes: bool, acv_ait_previo: bool, enfermedad_vascular: bool) -> dict:
    if not isinstance(edad, int) or not 0 <= edad <= 120:
        return {"error": f"edad inválida: {edad!r}"}
    s = (int(insuficiencia_cardiaca) + int(hta) + int(diabetes) + int(enfermedad_vascular)
         + int(sexo_femenino) + (2 if acv_ait_previo else 0)
         + (2 if edad >= 75 else 1 if edad >= 65 else 0))
    return {
        "score": s,
        "nota": "Válido solo en fibrilación auricular documentada. "
                "Cada criterio debe estar respaldado por un registro_id. "
                "Interpretación final: clínico.",
    }


# ---------------------------------------------------------------------------
# Esquemas
# ---------------------------------------------------------------------------
_CRITERIOS_CHA2DS2 = ["sexo_femenino", "insuficiencia_cardiaca", "hta", "diabetes",
                      "acv_ait_previo", "enfermedad_vascular"]

TOOLS_CONSULTA: list[dict] = [
    {
        "name": "obtener_linea_tiempo",
        "description": "Devuelve perfil (sin nombre), solicitud, eventos clínicos, mediciones "
                       "y citas del paciente de la alerta, cada uno con registro_id para citar. "
                       "Solo incluye registros hasta la fecha de corte.",
        "input_schema": {"type": "object",
                         "properties": {"pid": {"type": "string",
                                                "description": "Debe ser el paciente de la alerta"}},
                         "required": ["pid"]},
    },
    {
        "name": "obtener_cohorte",
        "description": "Desenlaces durante la espera de pacientes similares (mismo grupo CIE-10 "
                       "y rango de edad), con n e IC95 (Wilson). Excluye al propio paciente y "
                       "solo usa seguimiento completo antes del corte. Úsala para anticipar "
                       "riesgo, sobre todo en pacientes sin historial propio. Informa siempre n "
                       "e IC95; si n < 10, decláralo.",
        "input_schema": {"type": "object",
                         "properties": {
                             "grupo_cie10": {"type": "string", "description": "Ej: I20, I50"},
                             "edad_min": {"type": "integer", "minimum": 0, "maximum": 120},
                             "edad_max": {"type": "integer", "minimum": 0, "maximum": 120},
                             "ventana_dias": {"type": "integer", "default": 180,
                                              "minimum": 30, "maximum": 730}},
                         "required": ["grupo_cie10", "edad_min", "edad_max"]},
    },
    {
        "name": "obtener_capacidad_box",
        "description": "Cupos libres, ocupación y sobretiempo de una especialidad en la ventana "
                       "previa a la fecha de corte. Úsala para la propuesta de agenda.",
        "input_schema": {"type": "object",
                         "properties": {
                             "especialidad": {"type": "string"},
                             "ventana_dias": {"type": "integer", "default": 30,
                                              "minimum": 7, "maximum": 180}},
                         "required": ["especialidad"]},
    },
    {
        "name": "calcular_cha2ds2_vasc",
        "description": "Calcula CHA2DS2-VASc. Úsala solo si hay fibrilación auricular "
                       "documentada. Extrae cada criterio de registros citables; si un criterio "
                       "no está registrado, decláralo en datos_faltantes.",
        "input_schema": {"type": "object",
                         "properties": {k: {"type": "boolean"} for k in _CRITERIOS_CHA2DS2}
                                       | {"edad": {"type": "integer"}},
                         "required": ["edad", *_CRITERIOS_CHA2DS2]},
    },
]

_ITEM_LINEA_TIEMPO = {
    "type": "object",
    "properties": {"fecha": {"type": "string"}, "descripcion": {"type": "string"},
                   "registro_id": {"type": "string"}},
    "required": ["descripcion", "registro_id"],
}

TOOL_REGISTRAR: dict = {
    "name": "registrar_analisis",
    "description": "Entrega FINAL del análisis. Llamar una sola vez, al terminar. "
                   "Es una sugerencia para revisión médica, no una decisión.",
    "input_schema": {
        "type": "object",
        "properties": {
            "resumen": {"type": "string"},
            "relacion_con_derivacion": {"type": "string"},
            "linea_tiempo_relevante": {"type": "array", "items": _ITEM_LINEA_TIEMPO},
            "hallazgos": {"type": "array", "items": {
                "type": "object",
                "properties": {"hallazgo": {"type": "string"},
                               "tipo": {"type": "string", "enum": ["documentado", "inferido"]},
                               "registro_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["hallazgo", "tipo", "registro_ids"]}},
            "riesgo_poblacional": {"type": "string"},
            "prioridad_sugerida": {"type": "string", "enum": PRIORIDADES},
            "acuerdo_con_motor_reglas": {"type": "boolean"},
            "justificacion": {"type": "string",
                              "description": "Si discrepas del motor de reglas, explica por qué."},
            "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
            "acciones_sugeridas": {"type": "array", "items": {"type": "string"}},
            "propuesta_agenda": {"type": "string"},
            "datos_faltantes": {"type": "array", "items": {"type": "string"}},
            "inconsistencias_datos": {"type": "array", "items": {
                "type": "object",
                "properties": {"descripcion": {"type": "string"},
                               "registro_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["descripcion"]}},
            "nota_preconsulta": {"type": "string",
                                 "description": "Texto breve y citado para la ficha del "
                                                "especialista antes de la consulta inicial."},
        },
        "required": ["resumen", "relacion_con_derivacion", "hallazgos", "prioridad_sugerida",
                     "acuerdo_con_motor_reglas", "confianza", "justificacion",
                     "acciones_sugeridas", "datos_faltantes", "nota_preconsulta"],
    },
}

TOOLS: list[dict] = [*TOOLS_CONSULTA, TOOL_REGISTRAR]     # modo reactivo
TOOLS_BARRIDO: list[dict] = [TOOL_REGISTRAR]              # modo barrido

_PROPIEDADES = {t["name"]: set(t["input_schema"]["properties"]) for t in TOOLS}
_ALIAS = {"obtener_estadisticas_cohorte": "obtener_cohorte"}   # compatibilidad v0.2


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _sanitizar(obj: Any) -> Any:
    """Elimina recursivamente campos identificatorios."""
    if isinstance(obj, dict):
        return {k: _sanitizar(v) for k, v in obj.items()
                if str(k).lower() not in CAMPOS_IDENTIFICATORIOS}
    if isinstance(obj, (list, tuple)):
        return [_sanitizar(v) for v in obj]
    return obj


def _invocar(metodo, args: dict, restricciones: dict):
    """Llama al método del repositorio imponiendo las restricciones (falla en cerrado)."""
    params = inspect.signature(metodo).parameters
    acepta_kwargs = any(p.kind is p.VAR_KEYWORD for p in params.values())
    faltan = [k for k in restricciones if k not in params and not acepta_kwargs]
    if faltan:
        raise RestriccionNoSoportada(
            f"{metodo.__name__} no acepta {faltan}; no se puede garantizar la restricción.")
    return metodo(**args, **restricciones)


def _json(out: Any) -> str:
    def _default(o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return str(o)
    return json.dumps(_sanitizar(out), ensure_ascii=False, default=_default)


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
def ejecutar_tool(repo, nombre: str, args: dict, *, pid_alerta: str, corte: str | date) -> str:
    """Ejecuta una herramienta con las restricciones de la alerta.

    pid_alerta y corte los entrega copiloto.py desde la alerta, nunca desde el modelo.
    """
    nombre = _ALIAS.get(nombre, nombre)
    if nombre not in _PROPIEDADES or nombre == TOOL_REGISTRAR["name"]:
        return _json({"error": f"herramienta no ejecutable: {nombre}"})

    # Solo claves del esquema: el modelo no puede inyectar 'corte', 'excluir_pid', etc.
    args = {k: v for k, v in (args or {}).items() if k in _PROPIEDADES[nombre]}

    try:
        if nombre == "obtener_linea_tiempo":
            if args.get("pid") != pid_alerta:
                return _json({"error": "solo se permite consultar al paciente de la alerta",
                              "pid_permitido": pid_alerta})
            out = _invocar(repo.linea_tiempo, {"pid": pid_alerta}, {"corte": corte})

        elif nombre == "obtener_cohorte":
            if args["edad_min"] > args["edad_max"]:
                return _json({"error": "edad_min mayor que edad_max"})
            args.setdefault("ventana_dias", 180)
            args["ventana_dias"] = max(30, min(int(args["ventana_dias"]), 730))
            out = _invocar(repo.estadisticas_cohorte, args,
                           {"corte": corte, "excluir_pid": pid_alerta})
            if isinstance(out, dict) and isinstance(out.get("n"), int) and out["n"] < 10:
                out["advertencia"] = "n < 10: intervalo amplio, interpretar con cautela."

        elif nombre == "obtener_capacidad_box":
            metodo = getattr(repo, "capacidad_box", None)
            if metodo is None:
                return _json({"error": "capacidad de box no disponible en esta versión"})
            args.setdefault("ventana_dias", 30)
            out = _invocar(metodo, args, {"corte": corte})

        elif nombre == "calcular_cha2ds2_vasc":
            out = cha2ds2_vasc(**args)

    except RestriccionNoSoportada as e:
        out = {"error": f"restricción no soportada: {e}"}
    except (KeyError, TypeError, ValueError) as e:
        out = {"error": f"argumentos inválidos para {nombre}: {e}"}
    except Exception as e:   # el bucle del agente no debe caerse
        out = {"error": f"fallo interno en {nombre}: {type(e).__name__}"}

    return _json(out)