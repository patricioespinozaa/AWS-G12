"""Carga del dataset sintético HLF para los notebooks de EDA.

Uso:
    from carga import cargar, FECHA_REFERENCIA
    d = cargar()
    d["lista"].head()
"""
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "dataset_hlf_ambulatorio" / "dataset_hlf_ambulatorio"
FECHA_REFERENCIA = pd.Timestamp("2026-10-13")

ORDEN_PRIORIDAD = ["alta", "media", "baja"]
ORDEN_SEVERIDAD = ["leve", "moderada", "grave"]
RANGOS_NORMALES = {
    "presion_sistolica": (90, 139),
    "presion_diastolica": (60, 89),
    "HbA1c": (4.0, 6.4),
    "glicemia": (70, 140),
    "saturacion_o2": (95, 100),
    "peak_flow": (350, 600),
    "escala_dolor_eva": (0, 3),
    "PHQ9": (0, 9),
}


def _leer(nombre, fechas=()):
    df = pd.read_csv(DATA_DIR / nombre, encoding="utf-8")
    for col in fechas:
        df[col] = pd.to_datetime(df[col])
    return df


def cargar():
    """Devuelve un dict con las 6 tablas, con fechas parseadas y categorías ordenadas."""
    pacientes = _leer("pacientes.csv", ["fecha_defuncion"])
    lista = _leer("lista_espera.csv", ["fecha_ingreso_lista"])
    eventos = _leer("eventos_clinicos.csv", ["fecha_evento"])
    mediciones = _leer("mediciones.csv", ["fecha_medicion"])
    agenda = _leer("agenda_box.csv", ["fecha"])
    citas = _leer("citaciones.csv", ["fecha_cita"])

    lista["prioridad_inicial"] = pd.Categorical(lista["prioridad_inicial"], ORDEN_PRIORIDAD, ordered=True)
    eventos["severidad"] = pd.Categorical(eventos["severidad"], ORDEN_SEVERIDAD, ordered=True)
    lista["diagnostico_cie10"] = lista["diagnostico_cie10"].str.strip().str.upper()

    # Días de espera desde el ingreso a la lista, hasta hoy o hasta la defunción
    fin = lista.merge(pacientes[["id_paciente", "fecha_defuncion"]], on="id_paciente")["fecha_defuncion"].fillna(FECHA_REFERENCIA)
    lista["dias_espera"] = (fin.values - lista["fecha_ingreso_lista"]).dt.days

    return {
        "pacientes": pacientes,
        "lista": lista,
        "eventos": eventos,
        "mediciones": mediciones,
        "agenda": agenda,
        "citas": citas,
    }


def base_paciente(d):
    """Una fila por paciente: datos demográficos + solicitud en lista."""
    return d["pacientes"].merge(d["lista"], on="id_paciente", how="left")
