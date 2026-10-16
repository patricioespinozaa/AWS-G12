"""Reglas de calidad de datos (sección 7 de docs/contexto-tecnico.md). Valores referenciales.

Los límites de plausibilidad (7.1) están separados de los rangos normales. Los rangos normales de
esta tabla son los del diccionario de datos (con ellos se calcula ``fuera_de_rango`` en el origen) y
se usan aquí solo para verificar ese booleano y la variabilidad del mismo día; el motor usa los suyos
desde ``reglas-vX.Y.Z.yaml``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

LIMITES_PLAUSIBILIDAD: Final[dict[str, tuple[Decimal, Decimal]]] = {
    "presion_sistolica": (Decimal(50), Decimal(300)),
    "presion_diastolica": (Decimal(20), Decimal(200)),
    "glicemia": (Decimal(10), Decimal(1500)),
    "HbA1c": (Decimal(3), Decimal(20)),
    "saturacion_o2": (Decimal(50), Decimal(100)),
    "peak_flow": (Decimal(50), Decimal(900)),
    "escala_dolor_eva": (Decimal(0), Decimal(10)),
    "PHQ9": (Decimal(0), Decimal(27)),
}

RANGOS_NORMALES_ORIGEN: Final[dict[str, tuple[Decimal, Decimal]]] = {
    "presion_sistolica": (Decimal(90), Decimal(139)),
    "presion_diastolica": (Decimal(60), Decimal(89)),
    "glicemia": (Decimal(70), Decimal(140)),
    "HbA1c": (Decimal("4.0"), Decimal("6.4")),
    "saturacion_o2": (Decimal(95), Decimal(100)),
    "peak_flow": (Decimal(350), Decimal(600)),
    "escala_dolor_eva": (Decimal(0), Decimal(3)),
    "PHQ9": (Decimal(0), Decimal(9)),
}

# Mismo tipo, mismo día: diferencia > 30 % del ancho del rango normal => ``verificar``.
FRACCION_REPETIDA_MISMO_DIA: Final = Decimal("0.3")

# Códigos de hallazgo.
DQ_FUERA_PLAUSIBILIDAD: Final = "fuera_de_plausibilidad"
DQ_REPETIDA_IMPLAUSIBLE: Final = "medicion_repetida_implausible"
DQ_PREVIO_INGRESO: Final = "registro_previo_ingreso"
DQ_POSTERIOR_DEFUNCION: Final = "registro_posterior_defuncion"
DQ_ASISTIO_EN_ESPERA: Final = "asistio_en_espera"
DQ_FUERA_RANGO_INCONSISTENTE: Final = "fuera_de_rango_inconsistente"
DQ_ESPECIALIDAD_INFERIDA: Final = "especialidad_evento_inferida"


def es_plausible(tipo: str, valor: Decimal) -> bool:
    inf, sup = LIMITES_PLAUSIBILIDAD[tipo]
    return inf <= valor <= sup


def fuera_de_rango_origen_esperado(tipo: str, valor: Decimal) -> bool:
    inf, sup = RANGOS_NORMALES_ORIGEN[tipo]
    return not inf <= valor <= sup
