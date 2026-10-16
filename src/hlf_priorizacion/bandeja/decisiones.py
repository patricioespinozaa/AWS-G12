"""Decisiones médicas (B5): validación, guardado solo agregando y estado vigente.

``salidas/decisiones/decisiones.jsonl`` es el único archivo que escribe la bandeja (B1.4), más su evento
``decision_medica`` en la auditoría. Nunca se edita ni se borra una línea: una decisión nueva sobre la
misma solicitud queda como la vigente y las anteriores como historial. Los logs y la auditoría llevan
IDs, decisión y prioridad final; nunca el texto del motivo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import ValidationError

from hlf_priorizacion.auditoria.registro import RegistroAuditoria, nuevo_ulid
from hlf_priorizacion.bandeja.filas import EstadoDecision
from hlf_priorizacion.logs import obtener_logger
from hlf_priorizacion.modelos import NIVELES, Decision, Evaluacion, Nivel
from hlf_priorizacion.persistencia.salidas import ErrorPersistencia, agregar_jsonl

ARCHIVO_DECISIONES: Final = "decisiones.jsonl"
MAX_MOTIVO: Final = 1000

Opcion = Literal["aceptar", "ajustar", "rechazar"]
OPCIONES: Final[tuple[Opcion, ...]] = ("aceptar", "ajustar", "rechazar")
_DECISION_DE_OPCION: Final[dict[Opcion, Literal["aceptada", "ajustada", "rechazada"]]] = {
    "aceptar": "aceptada",
    "ajustar": "ajustada",
    "rechazar": "rechazada",
}
Clave = tuple[str, date, str]


class ErrorDecision(ValueError):
    """El formulario no forma una ``Decision`` válida. ``mensajes`` se muestran sin guardar."""

    def __init__(self, mensajes: list[str]) -> None:
        super().__init__("; ".join(mensajes))
        self.mensajes = mensajes


def ruta_decisiones(raiz: Path) -> Path:
    return raiz / "decisiones" / ARCHIVO_DECISIONES


def ruta_auditoria(raiz: Path) -> Path:
    return raiz / "auditoria" / "eventos.jsonl"


def _ahora() -> datetime:
    return datetime.now(UTC)


def _mensajes(e: ValidationError) -> list[str]:
    return [str(err["msg"]).removeprefix("Value error, ") for err in e.errors(include_input=False)]


def crear_decision(
    *,
    evaluacion: Evaluacion,
    opcion: str,
    usuario: str,
    prioridad_final: str | None = None,
    motivo: str | None = None,
    id_analisis: str | None = None,
    reloj: Callable[[], datetime] = _ahora,
    generar_id: Callable[[], str] = nuevo_ulid,
) -> Decision:
    """Arma la ``Decision`` del formulario. La validación de negocio la hace el modelo (B5.2)."""
    if evaluacion.nivel_propuesto is None:
        raise ErrorDecision(["una exclusión no tiene prioridad propuesta que decidir"])
    if opcion not in _DECISION_DE_OPCION:
        raise ErrorDecision(["elija aceptar, ajustar o rechazar"])
    texto = (motivo or "").strip()
    if len(texto) > MAX_MOTIVO:
        raise ErrorDecision([f"el motivo admite hasta {MAX_MOTIVO} caracteres"])
    decision = _DECISION_DE_OPCION[opcion]
    final: str | None
    if decision == "aceptada":
        final = evaluacion.nivel_propuesto
    elif decision == "ajustada":
        final = prioridad_final
    else:
        final = None
    try:
        return Decision.model_validate(
            {
                "id_decision": generar_id(),
                "id_solicitud": evaluacion.id_solicitud,
                "fecha_corte": evaluacion.fecha_corte,
                "version_reglas": evaluacion.version_reglas,
                "id_analisis": id_analisis,
                "decision": decision,
                "prioridad_propuesta": evaluacion.nivel_propuesto,
                "prioridad_final": final,
                "motivo": texto or None,
                "usuario": usuario,
                "timestamp": reloj().astimezone(UTC),
            }
        )
    except ValidationError as e:
        raise ErrorDecision(_mensajes(e)) from e


class DecisionSinAuditoria(ErrorPersistencia):
    """La decisión quedó guardada, pero su evento ``decision_medica`` no se pudo escribir."""

    def __init__(self, id_decision: str, tipo_error: str) -> None:
        super().__init__(f"decisión {id_decision} guardada sin evento de auditoría: {tipo_error}")
        self.id_decision = id_decision
        self.tipo_error = tipo_error


def guardar_decision(raiz: Path, decision: Decision, id_ejecucion: str = "bandeja") -> None:
    """Agrega la decisión a ``decisiones.jsonl`` y un evento ``decision_medica`` a la auditoría (B5.4, B5.5)."""
    agregadas = agregar_jsonl(
        ruta_decisiones(raiz), [decision.model_dump(mode="json")], lambda r: str(r["id_decision"])
    )
    if agregadas != 1:
        raise ErrorPersistencia("id_decision repetido: la decisión no se guardó")
    auditoria = RegistroAuditoria(ruta_auditoria(raiz), id_ejecucion, actor=f"medico:{decision.usuario}")
    try:
        auditoria.registrar(
            "decision_medica",
            id_decision=decision.id_decision,
            id_solicitud=decision.id_solicitud,
            fecha_corte=decision.fecha_corte.isoformat(),
            version_reglas=decision.version_reglas,
            id_analisis=decision.id_analisis,
            decision=decision.decision,
            prioridad_final=decision.prioridad_final,
        )
    except OSError as e:
        # La decisión ya quedó en decisiones.jsonl: no es un fallo de guardado y no hay que reintentarla.
        raise DecisionSinAuditoria(decision.id_decision, type(e).__name__) from e
    obtener_logger().info(
        "decisión médica guardada",
        extra={
            "campos": {
                "id_solicitud": decision.id_solicitud,
                "fecha_corte": decision.fecha_corte.isoformat(),
                "version_reglas": decision.version_reglas,
                "codigo": decision.decision,
            }
        },
    )


def leer_decisiones(raiz: Path) -> list[Decision]:
    """Todas las decisiones, en el orden del archivo."""
    ruta = ruta_decisiones(raiz)
    if not ruta.exists():
        return []
    try:
        with ruta.open(encoding="utf-8") as f:
            return [Decision.model_validate_json(linea) for linea in f if linea.strip()]
    except (OSError, ValueError) as e:
        raise ErrorPersistencia(f"no se pudo leer {ruta}: {type(e).__name__}") from e


def _orden(d: Decision) -> tuple[datetime, str]:
    return d.timestamp, d.id_decision


def clave(d: Decision) -> Clave:
    return d.id_solicitud, d.fecha_corte, d.version_reglas


def vigentes(decisiones: Iterable[Decision]) -> dict[Clave, Decision]:
    """La vigente por ``(id_solicitud, fecha_corte, version_reglas)``: mayor ``timestamp``, empate por ID."""
    salida: dict[Clave, Decision] = {}
    for d in decisiones:
        previa = salida.get(clave(d))
        if previa is None or _orden(d) > _orden(previa):
            salida[clave(d)] = d
    return salida


def historial(decisiones: Iterable[Decision], id_solicitud: str, corte: date, version_reglas: str) -> list[Decision]:
    """Decisiones de una solicitud y corte, de la más reciente a la más antigua (la primera es la vigente)."""
    return sorted(
        (d for d in decisiones if clave(d) == (id_solicitud, corte, version_reglas)), key=_orden, reverse=True
    )


def estado_decision(d: Decision | None) -> EstadoDecision:
    return "pendiente" if d is None else d.decision


def estados_del_corte(decisiones: Iterable[Decision], corte: date, version_reglas: str) -> dict[str, EstadoDecision]:
    return {
        k[0]: estado_decision(d) for k, d in vigentes(decisiones).items() if k[1] == corte and k[2] == version_reglas
    }


def niveles_ajuste(propuesto: Nivel) -> list[Nivel]:
    """Opciones de prioridad final al ajustar: todas menos la propuesta."""
    return [n for n in NIVELES if n != propuesto]
