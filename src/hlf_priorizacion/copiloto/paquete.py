"""Armado y render del ``PaqueteBarrido`` (C3). Funciones puras.

U1 no guarda el contexto de cada solicitud, solo ``Evaluacion.huella_contexto``. U2 reconstruye el
contexto desde el dataset y exige que la huella sea idéntica; si no, los datos cambiaron desde el lote y
la solicitud falla con ``huella_distinta`` sin llamar al modelo.

El render es JSON canónico dentro de ``<datos_clinicos>``. Todo ``<`` se escapa como ``\\u003c`` para que
ningún dato pueda cerrar el bloque ni abrir etiquetas (C3.3).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any, Final

from hlf_priorizacion.copiloto.modelos import PaqueteBarrido
from hlf_priorizacion.modelos import ContextoPaciente, Evaluacion, HallazgoDQ, ResultadoCohorte
from hlf_priorizacion.repositorio.contexto import huella_contexto

MARCA_DESCARTAR: Final = "error de registro, no usar como evidencia"
_CAMPOS_EVALUACION_OMITIDOS: Final = {"huella_contexto", "estado_revision"}


class ErrorHuella(ValueError):
    """El contexto reconstruido no coincide con el que evaluó el lote (``huella_distinta``)."""


def armar_paquete(
    contexto: ContextoPaciente,
    evaluacion: Evaluacion,
    *,
    evaluacion_anterior: Evaluacion | None = None,
    hallazgos_dq: Iterable[HallazgoDQ] = (),
    cohorte: ResultadoCohorte | None = None,
) -> PaqueteBarrido:
    if contexto.id_solicitud != evaluacion.id_solicitud or contexto.fecha_corte != evaluacion.fecha_corte:
        raise ErrorHuella("el contexto no corresponde a la evaluación")
    if huella_contexto(contexto) != evaluacion.huella_contexto:
        raise ErrorHuella("la huella del contexto reconstruido no coincide con la de la evaluación")
    return PaqueteBarrido(
        id_solicitud=evaluacion.id_solicitud,
        fecha_corte=evaluacion.fecha_corte,
        version_reglas=evaluacion.version_reglas,
        contexto=contexto,
        evaluacion=evaluacion,
        evaluacion_anterior=evaluacion_anterior,
        hallazgos_dq=sorted(hallazgos_dq, key=lambda h: (h.codigo, h.ids_registro, h.nivel)),
        cohorte=cohorte,
    )


def _marcar(registros: list[dict[str, Any]], clave_id: str, descartados: set[str]) -> list[dict[str, Any]]:
    return [{**r, "calidad_dato": MARCA_DESCARTAR} if r[clave_id] in descartados else r for r in registros]


def _evaluacion(ev: Evaluacion | None) -> dict[str, Any] | None:
    if ev is None:
        return None
    return {k: v for k, v in ev.model_dump(mode="json").items() if k not in _CAMPOS_EVALUACION_OMITIDOS}


def datos_paquete(p: PaqueteBarrido) -> dict[str, Any]:
    """Estructura que ve el modelo. Solo campos de ``ContextoPaciente`` (sin comuna, previsión, NSE ni nombre)."""
    ctx = p.contexto.model_dump(mode="json")
    descartados = {i for h in p.hallazgos_dq if h.nivel == "descartar" for i in h.ids_registro}
    return {
        "fecha_corte": p.fecha_corte.isoformat(),
        "paciente": {
            "id_paciente": ctx["id_paciente"],
            "edad_a_la_fecha": ctx["edad"],
            "sexo": ctx["sexo"],
            "fallecido_a_la_fecha": ctx["fallecido_a_la_fecha"],
            "fecha_defuncion": ctx["fecha_defuncion"],
        },
        "solicitud": ctx["solicitud"],
        "fecha_egreso_inferida": ctx["fecha_egreso_inferida"],
        "id_cita_egreso_inferido": ctx["id_cita_egreso_inferido"],
        "otras_solicitudes": ctx["otras_solicitudes"],
        "eventos": _marcar(ctx["eventos"], "id_evento", descartados),
        "mediciones": _marcar(ctx["mediciones"], "id_medicion", descartados),
        "citas": _marcar(ctx["citas"], "id_cita", descartados),
        "evaluacion_motor": _evaluacion(p.evaluacion),
        "evaluacion_anterior": _evaluacion(p.evaluacion_anterior),
        "hallazgos_calidad_datos": [h.model_dump(mode="json") for h in p.hallazgos_dq],
        "riesgo_poblacional_cohorte": p.cohorte.model_dump(mode="json") if p.cohorte is not None else None,
    }


def render_datos(p: PaqueteBarrido) -> str:
    texto = json.dumps(datos_paquete(p), ensure_ascii=False, indent=1, sort_keys=False)
    return texto.replace("<", "\\u003c")


def huella_texto(texto: str) -> str:
    return "sha256:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()
