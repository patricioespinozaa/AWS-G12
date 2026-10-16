"""Propiedad de persistencia: escribir la misma propuesta dos veces deja un solo registro."""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from hypothesis import given, settings

from estrategias import perfil_y_corte
from estrategias.tuberia import evaluar_crudo
from hlf_priorizacion.persistencia.salidas import escribir_propuestas, leer_propuestas


@settings(max_examples=25)
@given(perfil_y_corte())
def test_escribir_dos_veces_deja_un_solo_registro(caso: tuple[dict[str, Any], date]) -> None:
    raw, corte = caso
    ctx, _, ev = evaluar_crudo(raw, corte)
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        escribir_propuestas(raiz, [(ev, ctx.solicitud.especialidad)])
        segunda = escribir_propuestas(raiz, [(ev, ctx.solicitud.especialidad)])
        assert segunda[0].nuevas == 0
        assert leer_propuestas(raiz, ev.fecha_corte, ev.version_reglas) == [ev]
