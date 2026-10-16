"""Configuración común de pytest y perfiles de Hypothesis.

Perfiles:
- ``ci`` (por defecto): ``derandomize=True`` (semilla fija y reproducible), ``print_blob=True``
  para imprimir el blob de reproducción en cada fallo. El shrinking queda activado.
- ``dev``: aleatorio, más ejemplos, para explorar en local.

Se elige con la variable de entorno ``HYPOTHESIS_PROFILE`` o con ``--hypothesis-profile``.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, Phase, settings

settings.register_profile(
    "ci",
    derandomize=True,
    print_blob=True,
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.target, Phase.shrink],
)
settings.register_profile(
    "dev",
    derandomize=False,
    print_blob=True,
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


def pytest_report_header(config: pytest.Config) -> list[str]:
    perfil = settings.get_current_profile_name()
    actual = settings()
    return [
        f"hypothesis: perfil={perfil} derandomize={actual.derandomize} print_blob={actual.print_blob} "
        f"(con derandomize la semilla es fija; al fallar se imprime el blob @reproduce_failure)"
    ]
