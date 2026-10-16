"""Lectura de las salidas de U1 y U2 para la bandeja (B1: solo lectura) y contexto reconstruido.

- Cortes disponibles: carpetas ``salidas/propuestas/fecha_corte=*/version_reglas=<v>/propuestas.parquet``.
- ``DatosCorte``: propuestas (con especialidad), análisis, fallidos, hallazgos DQ, cohortes y resumen del lote.
- La ``Evaluacion`` no guarda el contexto: se reconstruye desde el dataset y se exige la misma
  ``huella_contexto`` (igual que U2 en ``copiloto/paquete.py``). Si no coincide, no hay línea de tiempo.

Nada de aquí ejecuta el lote ni el copiloto, ni importa el cliente de Bedrock.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Final, Literal

import pyarrow as pa
import pyarrow.parquet as pq

from hlf_priorizacion.contrato.validacion import validar_perfil
from hlf_priorizacion.copiloto.modelos import AnalisisFallido, FraseRevisionEquidad, RegistroAnalisis
from hlf_priorizacion.copiloto.persistencia import leer_analisis, leer_cohortes, leer_fallidos, leer_hallazgos_dq
from hlf_priorizacion.copiloto.validacion import frases_revision_equidad
from hlf_priorizacion.ingesta.carga import cargar_perfiles
from hlf_priorizacion.ingesta.normalizacion import PerfilNormalizado, normalizar_perfil
from hlf_priorizacion.logs import obtener_logger
from hlf_priorizacion.modelos import (
    ORDEN_NIVEL,
    ContextoPaciente,
    Evaluacion,
    HallazgoDQ,
    RegistroCitado,
    ResultadoCohorte,
)
from hlf_priorizacion.motor.parametros import VERSION_POR_DEFECTO
from hlf_priorizacion.persistencia.salidas import ErrorPersistencia, leer_propuestas, ruta_propuestas
from hlf_priorizacion.repositorio.contexto import (
    FECHA_EXTRACCION_DATASET,
    ErrorFechaCorte,
    Repositorio,
    SolicitudNoEncontrada,
    huella_contexto,
)

VERSION_REGLAS: Final = VERSION_POR_DEFECTO
VARIABLE_SALIDAS: Final = "HLF_SALIDAS"
VARIABLE_DATOS: Final = "HLF_DATOS"

ROTULO_COPILOTO: Final = "Sugerencia del copiloto — no es una decisión"
ADVERTENCIA_EQUIDAD: Final = (
    "El análisis menciona inasistencias junto a una bajada de prioridad. "
    "La inasistencia no baja la prioridad clínica: revise antes de decidir"
)
ANALISIS_PENDIENTE: Final = "Análisis IA pendiente"
AVISO_DEMO: Final = "Demo local con datos sintéticos. El sistema propone; el médico decide."

_RE_CORTE: Final = re.compile(r"^fecha_corte=(\d{4}-\d{2}-\d{2})$")

EstadoAnalisis = Literal["si", "no", "fallido"]


# --------------------------------------------------------------------------- rutas y comandos (B1.2, B1.3)


def rutas(raiz_repo: Path) -> tuple[Path, Path]:
    """``(salidas, datos)``: variables ``HLF_SALIDAS`` / ``HLF_DATOS`` o las carpetas del repositorio."""
    salidas = Path(os.environ.get(VARIABLE_SALIDAS) or raiz_repo / "salidas")
    datos = Path(os.environ.get(VARIABLE_DATOS) or raiz_repo / "data" / "dataset_hlf_ambulatorio")
    return salidas, datos


def comando_lote(corte: date) -> str:
    return f"uv run hlf-lote --fecha-corte {corte.isoformat()}"


def comando_copiloto(corte: date) -> str:
    return f"uv run hlf-copiloto --fecha-corte {corte.isoformat()}"


def cortes_disponibles(raiz: Path, version_reglas: str = VERSION_REGLAS) -> list[date]:
    """Cortes con propuestas de ``version_reglas``, en orden ascendente."""
    base = raiz / "propuestas"
    if not base.is_dir():
        return []
    cortes: list[date] = []
    for carpeta in base.iterdir():
        m = _RE_CORTE.match(carpeta.name)
        if m is None:
            continue
        try:
            corte = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if ruta_propuestas(raiz, corte, version_reglas).is_file():
            cortes.append(corte)
    return sorted(cortes)


# --------------------------------------------------------------------------- datos de un corte


class CorteSinPropuestas(LookupError):
    """El corte no tiene propuestas del lote (B1.2). Lleva el comando exacto para generarlas."""

    def __init__(self, corte: date) -> None:
        super().__init__(f"sin propuestas para {corte.isoformat()}")
        self.corte = corte
        self.comando = comando_lote(corte)


@dataclass(frozen=True)
class DatosCorte:
    corte: date
    version_reglas: str
    propuestas: dict[str, Evaluacion]
    especialidades: dict[str, str]
    analisis: dict[str, RegistroAnalisis] = field(default_factory=dict)
    fallidos: dict[str, AnalisisFallido] = field(default_factory=dict)
    hallazgos_dq: dict[str, list[HallazgoDQ]] = field(default_factory=dict)
    cohortes: dict[str, ResultadoCohorte] = field(default_factory=dict)
    resumen: dict[str, Any] | None = None

    def estado_analisis(self, id_solicitud: str) -> EstadoAnalisis:
        if id_solicitud in self.analisis:
            return "si"
        return "fallido" if id_solicitud in self.fallidos else "no"

    def marcas_equidad(self, id_solicitud: str) -> list[FraseRevisionEquidad]:
        registro = self.analisis.get(id_solicitud)
        return marcas_equidad(registro) if registro is not None else []


def marcas_equidad(registro: RegistroAnalisis) -> list[FraseRevisionEquidad]:
    """Frases que exigen la advertencia de equidad (B3.5).

    Los análisis guardados antes de la marca del sistema (prompt < v1.2.0) no traen ``revision_equidad`` y no se
    reescriben (solo agregar). Para ellos se aplica al leer la misma regla determinista de U2
    (``frases_revision_equidad``, C6.5 regla 2), sin llamar al modelo.
    """
    return list(registro.revision_equidad) or frases_revision_equidad(registro.analisis)


def _especialidades(raiz: Path, corte: date, version_reglas: str) -> dict[str, str]:
    ruta = ruta_propuestas(raiz, corte, version_reglas)
    try:
        tabla = pq.read_table(ruta, columns=["id_solicitud", "especialidad"])
    except (OSError, pa.ArrowException) as e:
        raise ErrorPersistencia(f"no se pudo leer {ruta}: {type(e).__name__}") from e
    return {str(f["id_solicitud"]): str(f["especialidad"]) for f in tabla.to_pylist()}


def elegir_analisis(registros: Iterable[RegistroAnalisis]) -> dict[str, RegistroAnalisis]:
    """Un análisis por solicitud: el de la versión de prompt más reciente (empate por ``id_analisis``)."""
    salida: dict[str, RegistroAnalisis] = {}
    for r in registros:
        previo = salida.get(r.id_solicitud)
        if previo is None or (r.version_prompt, r.id_analisis) > (previo.version_prompt, previo.id_analisis):
            salida[r.id_solicitud] = r
    return salida


def leer_resumen(raiz: Path, corte: date, version_reglas: str) -> dict[str, Any] | None:
    ruta = raiz / "resumen" / f"fecha_corte={corte.isoformat()}" / f"version_reglas={version_reglas}" / "resumen.json"
    if not ruta.is_file():
        return None
    try:
        datos: dict[str, Any] = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ErrorPersistencia(f"no se pudo leer {ruta}: {type(e).__name__}") from e
    return datos


def cargar_corte(raiz: Path, corte: date, version_reglas: str = VERSION_REGLAS) -> DatosCorte:
    """Todo lo que la bandeja muestra de un corte. ``CorteSinPropuestas`` si el lote no corrió."""
    if not ruta_propuestas(raiz, corte, version_reglas).is_file():
        raise CorteSinPropuestas(corte)
    propuestas = {ev.id_solicitud: ev for ev in leer_propuestas(raiz, corte, version_reglas)}
    analisis = elegir_analisis(leer_analisis(raiz, corte, version_reglas))
    fallidos: dict[str, AnalisisFallido] = {}
    for f in leer_fallidos(raiz, corte, version_reglas):
        if f.id_solicitud not in analisis:
            fallidos[f.id_solicitud] = f  # el último del archivo
    return DatosCorte(
        corte=corte,
        version_reglas=version_reglas,
        propuestas=propuestas,
        especialidades=_especialidades(raiz, corte, version_reglas),
        analisis=analisis,
        fallidos=fallidos,
        hallazgos_dq=leer_hallazgos_dq(raiz, corte),
        cohortes=leer_cohortes(raiz, corte, version_reglas),
        resumen=leer_resumen(raiz, corte, version_reglas),
    )


# --------------------------------------------------------------------------- contexto y línea de tiempo


def cargar_repositorio(datos: Path, fecha_extraccion: date = FECHA_EXTRACCION_DATASET) -> Repositorio:
    """Perfiles normalizados igual que el lote (contrato -> normalización). Un perfil inválido se omite."""
    normalizados: list[PerfilNormalizado] = []
    for raw in cargar_perfiles(datos):
        try:
            v = validar_perfil(raw)
            if v.ok and v.perfil is not None:
                normalizados.append(normalizar_perfil(v.perfil).perfil)
        except Exception as e:
            obtener_logger().warning("perfil no reconstruible", extra={"campos": {"tipo_error": type(e).__name__}})
    return Repositorio(normalizados, fecha_extraccion)


EstadoContexto = Literal["ok", "huella_distinta", "contexto_no_disponible"]


@dataclass(frozen=True)
class ResultadoContexto:
    estado: EstadoContexto
    contexto: ContextoPaciente | None = None
    linea_tiempo: list[RegistroCitado] = field(default_factory=list)


def reconstruir_contexto(repo: Repositorio, ev: Evaluacion) -> ResultadoContexto:
    """Contexto y línea de tiempo a la fecha de corte, solo si la huella coincide con la de la evaluación."""
    try:
        ctx = repo.contexto_a_fecha(ev.id_solicitud, ev.fecha_corte)
    except (SolicitudNoEncontrada, ErrorFechaCorte):
        return ResultadoContexto("contexto_no_disponible")
    if huella_contexto(ctx) != ev.huella_contexto:
        return ResultadoContexto("huella_distinta")
    return ResultadoContexto("ok", ctx, repo.linea_tiempo(ctx.id_paciente, ev.fecha_corte))


# --------------------------------------------------------------------------- cobertura (B6)


def cobertura(datos: DatosCorte, decididas: Iterable[str]) -> dict[str, Any]:
    """Métricas del panel de cobertura. ``decididas``: solicitudes con decisión vigente en el corte."""
    props = list(datos.propuestas.values())
    resumen = datos.resumen or {}
    solicitudes: Mapping[str, Any] = resumen.get("solicitudes", {})
    cambios = Counter[str]()
    for ev in props:
        if ev.nivel_propuesto is not None and ev.nivel_propuesto != ev.prioridad_inicial:
            cambios["sube" if ORDEN_NIVEL[ev.nivel_propuesto] > ORDEN_NIVEL[ev.prioridad_inicial] else "baja"] += 1
    decidibles = {ev.id_solicitud for ev in props if ev.nivel_propuesto is not None}
    tomadas = decidibles & set(decididas)
    return {
        "evaluadas": len(props),
        "cobertura_pct": resumen.get("cobertura", {}).get("porcentaje"),
        "cobertura_completa": resumen.get("cobertura", {}).get("completa"),
        "por_tipo_resultado": dict(sorted(Counter(ev.tipo_resultado for ev in props).items())),
        "exclusiones": dict(sorted(Counter(ev.codigo_exclusion for ev in props if ev.codigo_exclusion).items())),
        "cambios_de_nivel": dict(sorted(cambios.items())),
        "alertas_gestion": dict(sorted(Counter(a.codigo for ev in props for a in ev.alertas_gestion).items())),
        "cuarentena_perfiles": resumen.get("perfiles", {}).get("cuarentena"),
        "cuarentena_solicitudes": solicitudes.get("en_cuarentena"),
        "analisis_guardados": len(datos.analisis),
        "analisis_fallidos": len(datos.fallidos),
        "analisis_equidad": sum(1 for i in datos.analisis if datos.marcas_equidad(i)),
        "decisiones_tomadas": len(tomadas),
        "decisiones_pendientes": len(decidibles - tomadas),
    }
