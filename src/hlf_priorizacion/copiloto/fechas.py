"""Validación estricta de fechas y modos de ``hlf-copiloto`` (C2.1–C2.3). Funciones puras."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Final

MAX_DIAS_RANGO: Final = 31
_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ErrorFecha(ValueError):
    """Fecha o combinación de fechas inválida: el copiloto no arranca ni llama a Bedrock."""


def parsear_fecha(texto: str) -> date:
    """ISO estricto ``AAAA-MM-DD`` (sin horas, sin zonas, sin otros separadores)."""
    if not _RE_FECHA.match(texto):
        raise ErrorFecha(f"formato esperado AAAA-MM-DD: {texto!r}")
    try:
        return date.fromisoformat(texto)
    except ValueError as e:
        raise ErrorFecha(f"fecha inexistente: {texto}") from e


def cortes_a_procesar(
    fecha_corte: date | None,
    desde: date | None,
    hasta: date | None,
    fecha_extraccion: date,
) -> list[date]:
    """Lista de cortes en orden. Exige un solo modo y aplica C2.3 (salvo la existencia de salidas)."""
    modo_corte = fecha_corte is not None
    modo_rango = desde is not None or hasta is not None
    if modo_corte and modo_rango:
        raise ErrorFecha("no se puede combinar --fecha-corte con --desde/--hasta")
    if fecha_corte is not None:
        if fecha_corte > fecha_extraccion:
            raise ErrorFecha(
                f"--fecha-corte {fecha_corte} es posterior a la fecha de extracción {fecha_extraccion}"
            )
        return [fecha_corte]
    if not modo_rango:
        raise ErrorFecha("indique --fecha-corte o el par --desde/--hasta")
    if desde is None or hasta is None:
        raise ErrorFecha("--desde y --hasta se usan juntos")
    if desde >= hasta:
        raise ErrorFecha(f"--desde {desde} debe ser estrictamente anterior a --hasta {hasta}")
    if hasta > fecha_extraccion:
        raise ErrorFecha(f"--hasta {hasta} es posterior a la fecha de extracción {fecha_extraccion}")
    dias = (hasta - desde).days + 1
    if dias > MAX_DIAS_RANGO:
        raise ErrorFecha(f"el rango tiene {dias} días; el máximo es {MAX_DIAS_RANGO}")
    return [desde + timedelta(days=i) for i in range(dias)]
