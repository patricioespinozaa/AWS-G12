"""Configuración de la demo local (H-4): lista fija de médicos ficticios. Sin datos reales."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Medico:
    id: str
    nombre: str


MEDICOS: tuple[Medico, ...] = (
    Medico("MED-DEMO-01", "Dra. Demo Uno"),
    Medico("MED-DEMO-02", "Dr. Demo Dos"),
    Medico("MED-DEMO-03", "Dra. Demo Tres"),
)
