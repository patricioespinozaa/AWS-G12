"""Reglas, pesos y umbrales del puntaje de priorización.

Todo lo que cambia el resultado vive aquí y se versiona en VERSION_REGLAS. Los valores son un
punto de partida para calibrar con el equipo clínico del HLF, no un estándar clínico.

Estos son los valores de fábrica. La Administradora puede cambiar los editables desde la vista Reglas (F0014): cada
cambio es una versión nueva (`priorizacion/parametros.py`) que reemplaza estos atributos y deja VERSION_REGLAS como
"reglas-v0.1+c<n>". Por eso el resto del motor lee siempre `R.X` al calcular, nunca `from .reglas import X`.
Ver docs/enfoque.md y docs/arquitectura.md.
"""

VERSION_REGLAS = "reglas-v0.1"

# --- Niveles ---------------------------------------------------------------------------------
NIVELES = ("alta", "media", "baja")
ORDEN_NIVEL = {"alta": 3, "media": 2, "baja": 1}          # mayor = más prioritario
BASE_PRIORIDAD = {"alta": 20.0, "media": 10.0, "baja": 0.0}
UMBRAL_ALTA = 20.0
UMBRAL_MEDIA = 10.0

# --- Eventos clínicos --------------------------------------------------------------------------
PESO_EVENTO = {
    ("hospitalizacion", "ingreso UCI"): 12.0,
    ("hospitalizacion", "ingreso hospitalario"): 9.0,
    ("visita_urgencia", "descompensación grave"): 9.0,
    ("visita_urgencia", "triage ESI 2"): 8.0,
    ("visita_urgencia", "descompensación"): 5.0,
    ("examen_alterado", "resultado alterado"): 3.0,
    ("cambio_farmaco", "aumento dosis"): 3.0,
    ("control_aps", "control"): 0.0,
    ("control_aps", "control crónico"): 0.0,
    ("control_aps", "control de rutina"): 0.0,
    ("control_aps", "estabilización"): -1.0,
    ("control_aps", "buena respuesta"): -2.0,
    ("cambio_farmaco", "reducción dosis"): -2.0,
}
SUBTIPOS_MEJORA = {"estabilización", "buena respuesta", "reducción dosis"}
VIDA_MEDIA_DIAS = 90            # un evento pierde la mitad de su peso cada 90 días
VENTANA_EVENTOS_DIAS = 365      # eventos más antiguos no aportan
VENTANA_REGLA_DURA_DIAS = 30    # evento grave reciente → alta + alerta
VENTANA_MEJORA_DIAS = 90

NOMBRE_TIPO_EVENTO = {
    "visita_urgencia": "Urgencia",
    "hospitalizacion": "Hospitalización",
    "examen_alterado": "Examen alterado",
    "cambio_farmaco": "Cambio de fármaco",
    "control_aps": "Control APS",
}

# --- Riesgo basal por diagnóstico (pendiente de validar con clínicos) ------------------------------
# Resuelve que dos pacientes con riesgo basal distinto queden con el mismo puntaje.
RIESGO_BASAL_DX = {
    "I50": ("alto", "Insuficiencia cardíaca: descompensación con riesgo vital"),
    "I20": ("alto", "Angina de pecho: riesgo de infarto"),
    "J44": ("alto", "EPOC: exacerbaciones que terminan en hospitalización"),
    "K70": ("alto", "Enfermedad hepática: progresión y descompensación"),
    "G40": ("alto", "Epilepsia: crisis no controladas con riesgo de lesión"),
    "F32": ("alto", "Episodio depresivo: riesgo suicida"),
    "E11": ("medio", "Diabetes tipo 2: daño de órgano blanco progresivo"),
    "I10": ("medio", "Hipertensión: daño de órgano blanco progresivo"),
    "J45": ("medio", "Asma: crisis con riesgo si no hay control"),
    "F41": ("medio", "Trastorno de ansiedad: deterioro funcional"),
    "E03": ("bajo", "Hipotiroidismo: manejo estable en APS"),
    "E66": ("bajo", "Obesidad: riesgo a largo plazo"),
    "G43": ("bajo", "Migraña: sin riesgo vital inmediato"),
    "K21": ("bajo", "Reflujo: sin riesgo vital inmediato"),
    "M17": ("bajo", "Artrosis de rodilla: dolor y limitación funcional"),
    "M54": ("bajo", "Lumbago: dolor y limitación funcional"),
    "M75": ("bajo", "Lesión de hombro: dolor y limitación funcional"),
}
PUNTOS_RIESGO_BASAL = {"alto": 4.0, "medio": 2.0, "bajo": 0.0}
# Relevancia de las señales según el riesgo basal: la misma señal pesa más si la condición de base
# es de alto riesgo (opción 3 de docs/enfoque.md). Se aplica sobre la suma de señales clínicas positivas.
AJUSTE_SENALES_RIESGO_BASAL = {"alto": 0.25, "medio": 0.0, "bajo": -0.20}
# Plazo clínico de referencia para la posición en la cola (días)
PLAZO_REFERENCIA_DIAS = {"alto": 90, "medio": 180, "bajo": 365}
MAX_APORTE_ESPERA = 3.0

# Edad (dos tramos)
EDAD_UMBRAL_MAYOR = 75
EDAD_PUNTOS_MAYOR = 2.0
EDAD_UMBRAL = 65
EDAD_PUNTOS = 1.0


def puntos_edad(edad: int) -> float:
    if edad >= EDAD_UMBRAL_MAYOR:
        return EDAD_PUNTOS_MAYOR
    if edad >= EDAD_UMBRAL:
        return EDAD_PUNTOS
    return 0.0

# Dos puntajes:
# - puntaje_nivel = base de la prioridad inicial + señales clínicas (+ ajuste por riesgo basal).
#   Es el único que decide el nivel: solo las señales clínicas mueven a un paciente de nivel.
# - puntaje (orden) = puntaje_nivel + contexto (riesgo basal, edad, espera). Ordena dentro del nivel,
#   así dos pacientes del mismo nivel con distinto riesgo basal no quedan empatados.

# --- Mediciones ---------------------------------------------------------------------------------
RANGOS_NORMALES = {
    "presion_sistolica": (90.0, 139.0),
    "presion_diastolica": (60.0, 89.0),
    "HbA1c": (4.0, 6.4),
    "glicemia": (70.0, 140.0),
    "saturacion_o2": (95.0, 100.0),
    "peak_flow": (350.0, 600.0),
    "escala_dolor_eva": (0.0, 3.0),
    "PHQ9": (0.0, 9.0),
}
UNIDADES = {
    "presion_sistolica": "mmHg", "presion_diastolica": "mmHg", "HbA1c": "%", "glicemia": "mg/dL",
    "saturacion_o2": "%", "peak_flow": "L/min", "escala_dolor_eva": "puntos", "PHQ9": "puntos",
}
NOMBRE_MEDICION = {
    "presion_sistolica": "Presión sistólica", "presion_diastolica": "Presión diastólica",
    "HbA1c": "HbA1c", "glicemia": "Glicemia", "saturacion_o2": "Saturación O₂",
    "peak_flow": "Peak flow", "escala_dolor_eva": "Dolor EVA", "PHQ9": "PHQ-9",
}
MEJOR_ALTO = {"saturacion_o2", "peak_flow"}   # en estas, bajar es empeorar

PESO_DESVIACION = 4.0          # por cada "ancho de rango" fuera del rango normal
MAX_DESVIACION = 1.5
PESO_TENDENCIA = 15.0          # por cada ancho de rango por mes de empeoramiento
MAX_APORTE_TENDENCIA = 4.0
UMBRAL_TENDENCIA = 0.05        # pendientes menores se consideran estables
APORTE_TENDENCIA_MEJORA = -1.0
MIN_MEDICIONES_TENDENCIA = 3
VENTANA_TENDENCIA_DIAS = 180
PESO_PERSISTENCIA = 2.0        # × proporción fuera de rango en la ventana
VENTANA_PERSISTENCIA_DIAS = 90

# --- Patrones (combinación histórica de señales) ---------------------------------------------
PATRON_ESCALADA_VENTANA_DIAS = 120
PATRON_ESCALADA_APORTE = 2.0
PATRON_MEDICION_PREVIA_DIAS = 30
PATRON_MEDICION_VENTANA_DIAS = 180
PATRON_MEDICION_APORTE = 2.0

# --- Gestión del box (no entra al puntaje clínico) ---------------------------------------------
TASA_NO_SHOW_GLOBAL = 0.233     # del EDA
PESO_PRIOR_NO_SHOW = 2.0        # suavizado bayesiano hacia la tasa global
UMBRAL_RIESGO_NO_SHOW = 0.40
# Regla de demostración: examen reciente que la consulta necesita para aprovechar la hora
REQUISITO_EXAMEN = {
    "Endocrinología": ("HbA1c", "glicemia"),
    "Cardiología": ("presion_sistolica", "presion_diastolica"),
    "Broncopulmonar": ("saturacion_o2", "peak_flow"),
    "Salud Mental": ("PHQ9",),
}
VIGENCIA_EXAMEN_DIAS = 90
VENTANA_CONFIRMACION_DIAS = 30

# --- Canal de origen de la derivación (supuesto a confirmar con el HLF) --------------------
CANAL_ORIGEN = {
    "CESFAM/APS": "CUD (interconsulta desde APS)",
    "Otro hospital red": "CUD (interconsulta desde la red)",
    "Urgencia": "Thalamus (registro local HLF)",
    "Hospitalización": "Thalamus (registro local HLF)",
}


def tabla_reglas():
    """Filas legibles de las reglas vigentes, para mostrarlas al equipo clínico."""
    filas = [("Nivel", f"Puntaje de nivel ≥ {UMBRAL_ALTA:g}", "alta"),
             ("Nivel", f"{UMBRAL_MEDIA:g} ≤ puntaje de nivel < {UMBRAL_ALTA:g}", "media"),
             ("Nivel", f"Puntaje de nivel < {UMBRAL_MEDIA:g}", "baja"),
             ("Nivel", "Puntaje de nivel = base + señales clínicas + ajuste por riesgo basal", "decide el nivel"),
             ("Orden", "Puntaje de orden = puntaje de nivel + contexto (riesgo basal, edad, espera)",
              "ordena dentro del nivel"),
             ("Regla dura", f"Evento grave en los últimos {VENTANA_REGLA_DURA_DIAS} días", "alta + alerta"),
             ("Resguardo", "Bajar de nivel sin evidencia de mejora", "se mantiene la prioridad vigente")]
    filas += [("Base", f"Prioridad inicial {k}", f"{v:+g}") for k, v in BASE_PRIORIDAD.items()]
    filas += [("Evento", f"{NOMBRE_TIPO_EVENTO[t]} · {s}", f"{w:+g} (vida media {VIDA_MEDIA_DIAS} d)")
              for (t, s), w in PESO_EVENTO.items()]
    filas += [("Riesgo basal", f"{dx} · {txt}",
               f"orden {PUNTOS_RIESGO_BASAL[c]:+g} · señales ×{1 + AJUSTE_SENALES_RIESGO_BASAL[c]:g} "
               f"· plazo {PLAZO_REFERENCIA_DIAS[c]} d")
              for dx, (c, txt) in RIESGO_BASAL_DX.items()]
    filas += [("Edad", f"≥ {EDAD_UMBRAL_MAYOR} años", f"{EDAD_PUNTOS_MAYOR:+g}"),
              ("Edad", f"{EDAD_UMBRAL} a {EDAD_UMBRAL_MAYOR - 1} años", f"{EDAD_PUNTOS:+g}"),
              ("Espera", "Días de espera / plazo de referencia", f"hasta +{MAX_APORTE_ESPERA:g}"),
              ("Medición", "Último valor fuera de rango", f"{PESO_DESVIACION:g} × anchos de rango (máx. {MAX_DESVIACION:g})"),
              ("Medición", f"Tendencia de empeoramiento (≥ {MIN_MEDICIONES_TENDENCIA} mediciones)", f"hasta +{MAX_APORTE_TENDENCIA:g}"),
              ("Medición", "Tendencia de mejora con último valor normal", f"{APORTE_TENDENCIA_MEJORA:+g}"),
              ("Medición", f"Proporción fuera de rango en {VENTANA_PERSISTENCIA_DIAS} días", f"{PESO_PERSISTENCIA:g} × proporción"),
              ("Patrón", "Aumento de dosis + examen alterado", f"{PATRON_ESCALADA_APORTE:+g}"),
              ("Patrón", "Medición alterada antes de un evento moderado o grave", f"{PATRON_MEDICION_APORTE:+g}")]
    return filas
