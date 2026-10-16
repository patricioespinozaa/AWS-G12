"""Piezas compartidas por los stacks."""
from __future__ import annotations

from aws_cdk import aws_logs as logs


def retencion(dias: int) -> logs.RetentionDays:
    """Días de retención de los logs del entorno (F0013): 7 en dev, 30 en demo, 365 con datos reales."""
    return {7: logs.RetentionDays.ONE_WEEK, 30: logs.RetentionDays.ONE_MONTH, 90: logs.RetentionDays.THREE_MONTHS,
            365: logs.RetentionDays.ONE_YEAR}.get(dias, logs.RetentionDays.ONE_MONTH)
