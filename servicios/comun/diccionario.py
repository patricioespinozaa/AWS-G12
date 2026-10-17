"""Diccionario de datos de las tablas que se pueden consultar en Athena (F0009).

Una sola fuente para dos usos: el documento "diccionario" de la Knowledge Base y el esquema que recibe el generador
de SQL. Las columnas y tipos salen de db/carga.py (raw) y db/athena.py (historial); aquí solo van las descripciones.
"""
from __future__ import annotations

from db.athena import HISTORIAL, TIPOS_ATHENA, TIPOS_HISTORIAL_ATHENA
from db.carga import TABLAS

BASE_RAW = "hlf_raw"
BASE_HISTORIAL = "hlf_historial"
# Columnas que identifican a una persona: nunca se devuelven en una consulta (el validador de SQL las rechaza)
IDENTIFICATORIAS = {"nombre_fantasia"}

TABLAS_DESC = {
    "pacientes": "Una fila por paciente (datos demográficos). PK id_paciente.",
    "lista_espera": "Una fila por solicitud (interconsulta) en la lista de espera de especialidad. PK id_solicitud. "
                    "estado: en_espera, atendido, fallecido. prioridad_inicial es la asignada al derivar.",
    "eventos_clinicos": "Eventos durante la espera: urgencias, hospitalizaciones, exámenes alterados, cambios de "
                        "fármaco y controles en APS. PK id_evento.",
    "mediciones": "Mediciones objetivas (presión, HbA1c, glicemia, saturación, peak flow, EVA, PHQ-9).",
    "box": "Catálogo de boxes de atención.",
    "agenda_box": "Un bloque por box y día hábil, con capacidad y cupos usados.",
    "citaciones": "Citas de especialidad con su resultado. PK id_cita.",
    "serie_nocturna": "Simulación noche a noche (particionada por fecha): puntaje, nivel propuesto, prioridad vigente "
                      "y posición en la cola de cada solicitud activa esa noche.",
    "estimacion_espera": "Estimación de días de espera por solicitud activa (particionada por fecha de cálculo).",
}
COLUMNAS_DESC = {
    "id_paciente": "Identificador del paciente (PAC-HLF-#####)",
    "nombre_fantasia": "Nombre ficticio (identifica a la persona: no se consulta)",
    "edad": "Edad en años", "sexo": "F o M",
    "comuna": "La Florida, La Granja, La Pintana, Pirque, Puente Alto, San José de Maipo o San Ramón",
    "prevision": "FONASA A–D o ISAPRE", "nivel_socioeconomico": "bajo, medio-bajo o medio",
    "fallecido": "Si falleció", "fecha_defuncion": "Fecha de defunción, si aplica",
    "id_solicitud": "Identificador de la interconsulta (IC-HLF-#####)",
    "especialidad": "Broncopulmonar, Cardiología, Endocrinología, Gastroenterología, Neurología, Salud Mental o "
                    "Traumatología",
    "sub_especialidad": "Subespecialidad", "diagnostico_cie10": "Código CIE-10 de 3 caracteres (p. ej. I20)",
    "diagnostico_texto": "Descripción del diagnóstico",
    "prioridad_inicial": "alta, media o baja (asignada al derivar; nunca cambia)",
    "fecha_ingreso_lista": "Ingreso a la lista: desde aquí se cuentan los días de espera",
    "origen_derivacion": "CESFAM/APS, Urgencia, Hospitalización u Otro hospital red",
    "estado": "en_espera, atendido o fallecido",
    "id_evento": "Identificador del evento (EV-######)", "fecha_evento": "Fecha del evento",
    "tipo_evento": "visita_urgencia, hospitalizacion, examen_alterado, cambio_farmaco o control_aps",
    "subtipo": "Detalle del tipo (triage ESI 2, ingreso UCI, aumento dosis, ...)",
    "severidad": "leve, moderada o grave", "detalle": "Texto de plantilla del evento",
    "fecha_medicion": "Fecha de la medición",
    "tipo_medicion": "presion_sistolica, presion_diastolica, HbA1c, glicemia, saturacion_o2, peak_flow, "
                     "escala_dolor_eva o PHQ9",
    "valor": "Valor medido", "unidad": "Unidad", "fuera_de_rango": "Si está fuera del rango normal",
    "id_box": "Box (BOX-01 a BOX-20)", "fecha": "Fecha (en serie_nocturna: la noche simulada)",
    "bloque_inicio": "Hora de inicio del bloque (HH:MM)", "bloque_fin": "Hora de fin del bloque (HH:MM)",
    "capacidad_cupos": "Cupos del bloque", "cupos_usados": "Cupos usados",
    "minutos_sobretiempo": "Atraso acumulado del box ese día",
    "id_cita": "Identificador de la cita (CT-######)", "fecha_cita": "Fecha de la cita",
    "estado_cita": "asistio, no_asistio, reprogramo o cancelo",
    "minutos_atencion_real": "Duración real de la atención (solo si asistió)",
    "puntaje": "Puntaje de orden calculado por el motor", "puntaje_nivel": "Puntaje que decide el nivel",
    "nivel_propuesto": "Nivel propuesto por el motor esa noche (alta, media o baja)",
    "prioridad_vigente": "Prioridad decidida por la Administradora (o la inicial si no hay decisión)",
    "cambio": "sube, baja o igual (propuesta respecto de la vigente)", "alerta": "Si hay alerta clínica",
    "motivo_principal": "Factor que más pesó", "posicion_dinamica": "Posición en la cola con las propuestas",
    "posicion_estatica": "Posición en la lista congelada", "total_cola": "Tamaño de la cola de la especialidad",
    "posicion_vigente": "Posición en la cola vigente", "dias_estimados_min": "Cota optimista de días de espera",
    "dias_estimados_max": "Cota pesimista de días de espera", "confianza": "alta, media o baja",
    "metodo": "Método de estimación", "version_metodo": "Versión del método",
    "publicable": "Si se puede informar al paciente",
}


def tablas() -> list[dict]:
    """[{base, tabla, descripcion, columnas: [(columna, tipo_athena, descripcion)]}] de hlf_raw y hlf_historial."""
    salida = []
    for t in TABLAS:
        salida.append({"base": BASE_RAW, "tabla": t.nombre, "descripcion": TABLAS_DESC.get(t.nombre, ""),
                       "columnas": [(c, TIPOS_ATHENA[tipo], COLUMNAS_DESC.get(c, "")) for c, tipo in t.columnas]})
    for h in HISTORIAL:
        columnas = [(c, TIPOS_HISTORIAL_ATHENA[tipo], COLUMNAS_DESC.get(c, "")) for c, tipo in h.columnas]
        # Ambas tablas del historial están particionadas por `fecha` (db/athena.py, partition projection)
        columnas.append(("fecha", "date", "Partición: la noche (serie) o la fecha de cálculo (estimación)"))
        salida.append({"base": BASE_HISTORIAL, "tabla": h.nombre, "descripcion": TABLAS_DESC.get(h.nombre, ""),
                       "columnas": columnas})
    return salida


def nombres_permitidos() -> set[str]:
    """`base.tabla` que el SQL generado puede leer."""
    return {f"{t['base']}.{t['tabla']}" for t in tablas()}


def como_texto() -> str:
    """El esquema en texto compacto, para el prompt del generador de SQL."""
    lineas = []
    for t in tablas():
        lineas.append(f"{t['base']}.{t['tabla']}: {t['descripcion']}")
        lineas += [f"  - {c} ({tipo}){': ' + d if d else ''}" for c, tipo, d in t["columnas"]]
    return "\n".join(lineas)


def como_markdown(fecha_corte: str) -> str:
    """El documento "diccionario" de la Knowledge Base."""
    partes = [f"# Diccionario de datos de la lista de espera del HLF\n\nDatos a la fecha de corte {fecha_corte}. "
              "Describe las tablas que se pueden consultar y qué significa cada columna.\n"]
    for t in tablas():
        partes.append(f"## {t['tabla']} ({t['base']})\n\n{t['descripcion']}\n")
        partes += [f"- **{c}** ({tipo}): {d}" for c, tipo, d in t["columnas"]]
        partes.append("")
    return "\n".join(partes)
