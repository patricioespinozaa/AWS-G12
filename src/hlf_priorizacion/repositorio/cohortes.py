"""Cohortes en memoria (R9, sección 5.3) con IC95 de Wilson.

Desenlace: al menos un evento grave (urgencia u hospitalización grave) en los 90 días posteriores al
ingreso, calculado solo con registros hasta el corte. Solo entran solicitudes con seguimiento completo
(``fecha_ingreso_lista <= fecha_corte - 90``). El propio paciente queda fuera.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Final

from hlf_priorizacion.contrato.catalogos import es_evento_grave
from hlf_priorizacion.contrato.esquema import Solicitud
from hlf_priorizacion.ingesta.normalizacion import PerfilNormalizado
from hlf_priorizacion.modelos import ResultadoCohorte
from hlf_priorizacion.repositorio.contexto import FECHA_EXTRACCION_DATASET, edad_a_la_fecha

Z_95: Final = 1.959963984540054
DIAS_SEGUIMIENTO: Final = 90
N_MINIMO: Final = 10


def wilson(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Intervalo de Wilson para ``k`` éxitos en ``n`` ensayos (``n > 0``)."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError("se requiere n > 0 y 0 <= k <= n")
    p = k / n
    z2 = z * z
    centro = (p + z2 / (2 * n)) / (1 + z2 / n)
    margen = (z / (1 + z2 / n)) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    # El intervalo de Wilson siempre contiene a p; min/max solo corrigen el redondeo de punto flotante.
    return max(0.0, min(p, centro - margen)), min(1.0, max(p, centro + margen))


def banda_edad(edad: int, ancho: int) -> str:
    inicio = (edad // ancho) * ancho
    return f"{inicio}-{inicio + ancho - 1}"


def clave_cohorte(solicitud: Solicitud, edad: int, nivel_relajacion: int) -> str:
    """Nivel 0: CIE-10 + banda 10 años + origen; 1: sin origen; 2: banda de 20 años sin origen."""
    if nivel_relajacion == 0:
        return f"{solicitud.diagnostico_cie10}|{banda_edad(edad, 10)}|{solicitud.origen_derivacion}"
    if nivel_relajacion == 1:
        return f"{solicitud.diagnostico_cie10}|{banda_edad(edad, 10)}"
    return f"{solicitud.diagnostico_cie10}|{banda_edad(edad, 20)}"


def _tuvo_desenlace(perfil: PerfilNormalizado, solicitud: Solicitud, fecha_corte: date) -> bool:
    limite = min(solicitud.fecha_ingreso_lista + timedelta(days=DIAS_SEGUIMIENTO), fecha_corte)
    return any(
        es_evento_grave(e.tipo_evento, e.severidad) and solicitud.fecha_ingreso_lista <= e.fecha_evento <= limite
        for e in perfil.eventos
    )


def cohorte(
    perfiles: Sequence[PerfilNormalizado],
    id_solicitud: str,
    fecha_corte: date,
    fecha_extraccion: date = FECHA_EXTRACCION_DATASET,
) -> ResultadoCohorte:
    propio = next(p for p in perfiles if any(s.id_solicitud == id_solicitud for s in p.solicitudes))
    solicitud = next(s for s in propio.solicitudes if s.id_solicitud == id_solicitud)
    edad = edad_a_la_fecha(propio.paciente.edad, fecha_corte, fecha_extraccion)
    tope_ingreso = fecha_corte - timedelta(days=DIAS_SEGUIMIENTO)

    candidatos = [
        (p, s, edad_a_la_fecha(p.paciente.edad, fecha_corte, fecha_extraccion))
        for p in perfiles
        if p.id_paciente != propio.id_paciente
        for s in p.solicitudes
        if s.fecha_ingreso_lista <= tope_ingreso
    ]

    nivel = 0
    clave = clave_cohorte(solicitud, edad, 0)
    miembros: list[tuple[PerfilNormalizado, Solicitud]] = []
    for nivel in range(3):
        clave = clave_cohorte(solicitud, edad, nivel)
        miembros = [(p, s) for p, s, e in candidatos if clave_cohorte(s, e, nivel) == clave]
        if len(miembros) >= N_MINIMO:
            break

    n = len(miembros)
    k = sum(_tuvo_desenlace(p, s, fecha_corte) for p, s in miembros)
    if n == 0:
        p_hat, inf, sup = None, None, None
    else:
        p_hat = k / n
        inf, sup = wilson(k, n)
    return ResultadoCohorte(
        clave=clave,
        nivel_relajacion=nivel,
        n=n,
        k=k,
        p=p_hat,
        ic95_inf=inf,
        ic95_sup=sup,
        advertencia_muestra_pequena=n < N_MINIMO,
        advertencia_sesgo_acceso=True,
    )
