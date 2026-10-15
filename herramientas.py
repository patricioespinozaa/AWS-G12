import json

def cha2ds2_vasc(edad: int, sexo_femenino: bool, insuficiencia_cardiaca: bool, hta: bool,
                 diabetes: bool, acv_ait_previo: bool, enfermedad_vascular: bool) -> dict:
    s = (int(insuficiencia_cardiaca) + int(hta) + int(diabetes) + int(enfermedad_vascular)
         + int(sexo_femenino) + (2 if acv_ait_previo else 0)
         + (2 if edad >= 75 else 1 if edad >= 65 else 0))
    return {"score": s, "nota": "Válido solo en fibrilación auricular. Interpretación final: clínico."}


TOOLS = [
    {
        "name": "obtener_linea_tiempo",
        "description": "Devuelve perfil y todos los eventos clínicos del paciente "
                       "(SIC, urgencias, interconsultas, laboratorio, antecedentes), "
                       "cada uno con registro_id para citar.",
        "input_schema": {"type": "object",
                         "properties": {"pid": {"type": "string"}},
                         "required": ["pid"]},
    },
    {
        "name": "obtener_estadisticas_cohorte",
        "description": "Desenlaces históricos durante la espera de pacientes similares "
                       "(mismo grupo CIE-10 y rango de edad). Úsala para anticipar riesgo, "
                       "sobre todo en pacientes sin historial propio.",
        "input_schema": {"type": "object",
                         "properties": {
                             "grupo_cie10": {"type": "string", "description": "Ej: I20, I50"},
                             "edad_min": {"type": "integer"},
                             "edad_max": {"type": "integer"},
                             "ventana_dias": {"type": "integer", "default": 180}},
                         "required": ["grupo_cie10", "edad_min", "edad_max"]},
    },
    {
        "name": "calcular_cha2ds2_vasc",
        "description": "Calcula CHA2DS2-VASc. Úsala solo si hay fibrilación auricular "
                       "documentada. Extrae cada criterio de registros citables.",
        "input_schema": {"type": "object",
                         "properties": {k: {"type": "boolean"} for k in [
                             "sexo_femenino", "insuficiencia_cardiaca", "hta", "diabetes",
                             "acv_ait_previo", "enfermedad_vascular"]} | {"edad": {"type": "integer"}},
                         "required": ["edad", "sexo_femenino", "insuficiencia_cardiaca", "hta",
                                      "diabetes", "acv_ait_previo", "enfermedad_vascular"]},
    },
    {
        "name": "registrar_analisis",
        "description": "Entrega FINAL del análisis. Llamar una sola vez, al terminar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "resumen": {"type": "string"},
                "linea_tiempo_relevante": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"fecha": {"type": "string"}, "descripcion": {"type": "string"},
                                   "registro_id": {"type": "string"}},
                    "required": ["descripcion", "registro_id"]}},
                "hallazgos": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"hallazgo": {"type": "string"},
                                   "tipo": {"type": "string", "enum": ["documentado", "inferido"]},
                                   "registro_ids": {"type": "array", "items": {"type": "string"}}},
                    "required": ["hallazgo", "tipo", "registro_ids"]}},
                "riesgo_poblacional": {"type": "string"},
                "prioridad_sugerida": {"type": "string",
                                       "enum": ["critica", "alta", "media", "baja", "sin_cambio"]},
                "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
                "justificacion": {"type": "string"},
                "acciones_sugeridas": {"type": "array", "items": {"type": "string"}},
                "datos_faltantes": {"type": "array", "items": {"type": "string"}},
                "inconsistencias_datos": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"descripcion": {"type": "string"},
                                   "registro_ids": {"type": "array", "items": {"type": "string"}}},
                    "required": ["descripcion"]}},
                "nota_preconsulta": {"type": "string",
                                     "description": "Texto breve para adjuntar a la ficha "
                                                    "del especialista antes de la consulta inicial."},
            },
            "required": ["resumen", "hallazgos", "prioridad_sugerida", "confianza",
                         "justificacion", "acciones_sugeridas", "nota_preconsulta"],
        },
    },
]


def ejecutar_tool(repo, nombre: str, args: dict) -> str:
    if nombre == "obtener_linea_tiempo":
        out = repo.linea_tiempo(**args)
    elif nombre == "obtener_estadisticas_cohorte":
        out = repo.estadisticas_cohorte(**args)
    elif nombre == "calcular_cha2ds2_vasc":
        out = cha2ds2_vasc(**args)
    else:
        out = {"error": f"herramienta desconocida: {nombre}"}
    return json.dumps(out, ensure_ascii=False, default=str)