"""Propuesta de lectura de un examen (F0012) y su validación contra el texto del documento.

El modelo propone cada campo con una CITA copiada del documento. El validador no confía en el modelo:
- la cita debe aparecer literal en el texto extraído (sin distinguir mayúsculas, tildes ni espacios);
- el valor debe estar dentro de su cita; la fecha de la cita debe ser la propuesta; el tipo debe nombrarse en la cita;
- la unidad debe aparecer en la cita. Si no es la del motor, se convierte solo con una tabla explícita; si no hay
  conversión, el valor queda vacío para que la persona lo revise.
Lo que no pasa queda vacío, nunca inventado.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from priorizacion import reglas as R

VERSION_PROMPT = "ocr-v1"
CAMPOS = ("tipo_medicion", "valor", "unidad", "fecha_examen", "lugar")
SINONIMOS = {
    "HbA1c": ["hba1c", "hemoglobina glicosilada", "hemoglobina glicada", "a1c"],
    "glicemia": ["glicemia", "glucosa", "glucemia"],
    "presion_sistolica": ["presion arterial", "presion sistolica", "sistolica", "p.a.", "pa "],
    "presion_diastolica": ["presion arterial", "presion diastolica", "diastolica", "p.a.", "pa "],
    "saturacion_o2": ["saturacion", "sato2", "sat o2", "spo2", "oximetria"],
    "peak_flow": ["peak flow", "flujo espiratorio maximo", "pef", "fem"],
    "escala_dolor_eva": ["eva", "escala visual analoga", "dolor"],
    "PHQ9": ["phq-9", "phq9", "phq 9", "cuestionario de salud del paciente"],
}
UNIDADES_TEXTO = {"%": ["%"], "mg/dL": ["mg/dl"], "mmHg": ["mmhg"], "L/min": ["l/min", "lt/min", "litros/min"],
                  "puntos": ["puntos", "pts", "/27", "/10"], "mmol/L": ["mmol/l"], "mmol/mol": ["mmol/mol"]}
# Conversiones explícitas a la unidad del motor (priorizacion/reglas.UNIDADES). Nada más se convierte.
CONVERSIONES = {
    ("glicemia", "mmol/L"): (lambda v: round(v * 18.016, 1), "glicemia en mmol/L convertida a mg/dL (×18,016)"),
    ("HbA1c", "mmol/mol"): (lambda v: round(0.0915 * v + 2.15, 1), "HbA1c IFCC (mmol/mol) convertida a % NGSP"),
}
MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), start=1)}


def normalizar(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", (texto or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin_tildes).strip()


def _numero(texto: str) -> float | None:
    try:
        return float(str(texto).strip().replace(",", "."))
    except ValueError:
        return None


def _numeros_en(texto: str) -> list[float]:
    """Números sueltos: no el 1 de «HbA1c» ni el 9 de «PHQ-9» cuando va pegado a letras."""
    return [float(x.replace(",", ".")) for x in re.findall(r"(?<![\w.,])\d+(?:[.,]\d+)?", texto or "")]


def _nombra(cita: str, tipo: str) -> bool:
    """El tipo se nombra en la cita como palabra (que «eva» no calce dentro de «evaluación»)."""
    t = normalizar(cita)
    return any(re.search(r"(?<![a-z0-9])" + re.escape(s.strip()) + r"(?![a-z0-9])", t) for s in SINONIMOS[tipo])


def _fechas_en(texto: str) -> set[date]:
    t, fechas = normalizar(texto), set()
    for d, m, a in re.findall(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", t):
        try:
            fechas.add(date(int(a), int(m), int(d)))
        except ValueError:
            pass
    for a, m, d in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", t):
        try:
            fechas.add(date(int(a), int(m), int(d)))
        except ValueError:
            pass
    for d, mes, a in re.findall(r"\b(\d{1,2}) de (" + "|".join(MESES) + r") (?:de |del )?(\d{4})\b", t):
        fechas.add(date(int(a), MESES[mes], int(d)))
    return fechas


@dataclass
class Campo:
    campo: str
    valor: str | None
    cita: str | None
    confianza: float | None = None
    nota: str | None = None


@dataclass
class Lectura:
    campos: dict[str, Campo] = field(default_factory=dict)

    def valor(self, campo: str) -> str | None:
        return self.campos[campo].valor if campo in self.campos else None


def validar(propuesta: dict, texto_documento: str) -> Lectura:
    """Aplica las reglas de arriba a la propuesta del modelo ({campo: valor}, citas {campo: cita}, confianza)."""
    doc = normalizar(texto_documento)
    citas = propuesta.get("citas") or {}
    confianza = propuesta.get("confianza")
    confianza = max(0.0, min(1.0, float(confianza))) if isinstance(confianza, (int, float)) else None
    lectura = Lectura()

    def vacio(campo, nota):
        lectura.campos[campo] = Campo(campo, None, None, None, nota)

    def cita_valida(campo) -> str | None:
        cita = (citas.get(campo) or "").strip()
        return cita if cita and normalizar(cita) in doc else None

    for campo in CAMPOS:
        valor = propuesta.get(campo)
        valor = str(valor).strip() if valor not in (None, "") else ""
        if not valor:
            vacio(campo, "no se encontró en el documento")
            continue
        cita = cita_valida(campo)
        if cita is None:
            vacio(campo, "la cita no aparece literal en el documento")
            continue
        lectura.campos[campo] = Campo(campo, valor, cita, confianza)

    tipo = lectura.valor("tipo_medicion")
    if tipo and (tipo not in SINONIMOS or not _nombra(lectura.campos["tipo_medicion"].cita, tipo)):
        vacio("tipo_medicion", "el tipo no se nombra en su cita o no es uno de los 8 admitidos")
        tipo = None
    if (v := lectura.valor("valor")) is not None:
        numero = _numero(v)
        if numero is None or not any(abs(numero - n) < 1e-9 for n in _numeros_en(lectura.campos["valor"].cita)):
            vacio("valor", "el valor no está en su cita")
        else:
            lectura.campos["valor"].valor = f"{numero:g}"          # «8,4» → «8.4»
    if (f := lectura.valor("fecha_examen")) is not None:
        try:
            propuesta_fecha = date.fromisoformat(f)
        except ValueError:
            propuesta_fecha = None
        if propuesta_fecha is None or propuesta_fecha not in _fechas_en(lectura.campos["fecha_examen"].cita):
            vacio("fecha_examen", "la fecha de la cita no coincide")
    if (u := lectura.valor("unidad")) is not None:
        conocida = next((k for k, variantes in UNIDADES_TEXTO.items() if normalizar(u) in variantes or normalizar(u) == normalizar(k)), None)
        if conocida is None or not any(x in normalizar(lectura.campos["unidad"].cita) for x in UNIDADES_TEXTO[conocida]):
            vacio("unidad", "unidad no reconocida o fuera de su cita")
            if lectura.valor("valor") is not None:      # no suponer la unidad del motor: el número podría ser otra escala
                vacio("valor", f"unidad «{u}» no reconocida: revisar a mano")
        else:
            lectura.campos["unidad"].valor = conocida
    # Unidad del motor: convertir solo con la tabla; si no se puede, el valor queda para revisión
    if tipo and lectura.valor("valor") is not None:
        esperada = R.UNIDADES.get(tipo)
        unidad = lectura.valor("unidad") or esperada
        if unidad != esperada:
            conversion = CONVERSIONES.get((tipo, unidad))
            if conversion:
                fn, nota = conversion
                original = lectura.campos["valor"]
                lectura.campos["valor"] = Campo("valor", str(fn(_numero(original.valor))), original.cita,
                                                original.confianza, nota)
                lectura.campos["unidad"].valor = esperada
                lectura.campos["unidad"].nota = nota
            else:
                vacio("valor", f"unidad {unidad} sin conversión explícita a {esperada}: revisar a mano")
    return lectura


SISTEMA = """Lees el texto de un examen médico (extraído con OCR) y propones sus datos para que una persona los confirme.

Reglas:
- Usa solo el texto entregado. Si un dato no está, deja el campo vacío. Nunca adivines ni completes.
- Para cada dato que propongas, copia en `citas` el fragmento EXACTO del texto donde aparece (palabra por palabra).
- tipo_medicion debe ser uno de: {tipos}. Si el examen no es de esos tipos, déjalo vacío.
- valor: el número tal como aparece. unidad: la unidad tal como aparece. fecha_examen: AAAA-MM-DD (la fecha de toma de la muestra o del examen). lugar: el laboratorio o centro.
- Si hay varios resultados, elige el que corresponde a un tipo admitido; si hay más de uno admitido, el primero.
- confianza: de 0 a 1, qué tan seguro estás de la lectura completa."""

HERRAMIENTA = {
    "name": "lectura_examen",
    "description": "Datos del examen con la cita literal de cada uno.",
    "schema": {"type": "object", "properties": {
        "tipo_medicion": {"type": "string", "enum": [""] + list(SINONIMOS)},
        "valor": {"type": "string"}, "unidad": {"type": "string"},
        "fecha_examen": {"type": "string", "description": "AAAA-MM-DD o vacío"},
        "lugar": {"type": "string"},
        "citas": {"type": "object", "properties": {c: {"type": "string"} for c in CAMPOS}},
        "confianza": {"type": "number"},
    }, "required": ["tipo_medicion", "valor", "fecha_examen", "citas"]},
}


def proponer(texto_documento: str, modelo: str | None = None) -> tuple[dict, dict]:
    """Llama a Claude (Bedrock) con respuesta estructurada. Devuelve (propuesta, medida)."""
    from servicios.comun import bedrock
    sistema = SISTEMA.format(tipos=", ".join(SINONIMOS))
    return bedrock.converse_herramienta(sistema, texto_documento[:20000], HERRAMIENTA, max_tokens=800, modelo=modelo)
