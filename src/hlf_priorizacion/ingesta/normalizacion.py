"""Normalización de perfiles válidos (sección 4.4): CIE-10, ID de medición, especialidad del evento,
deduplicación y orden determinista."""

from __future__ import annotations

import hashlib
import itertools
import re
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from hlf_priorizacion.contrato.esquema import Paciente, PerfilValido, Solicitud, normalizar_cie10
from hlf_priorizacion.modelos import HallazgoDQ, RegistroCita, RegistroEvento, RegistroMedicion

__all__ = [
    "PerfilNormalizado",
    "ResultadoNormalizacion",
    "deduplicar_mediciones",
    "especialidad_desde_detalle",
    "id_medicion",
    "normalizar_cie10",
    "normalizar_perfil",
    "normalizar_valor",
]

_RE_ESPECIALIDAD = re.compile(r"\(([^()]+)\)\s*$")


class PerfilNormalizado(BaseModel):
    """Perfil listo para el repositorio: registros con ID, sin duplicados y en orden determinista."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    id_paciente: str
    paciente: Paciente
    solicitudes: list[Solicitud] = Field(min_length=1)
    eventos: list[RegistroEvento] = Field(default_factory=list)
    mediciones: list[RegistroMedicion] = Field(default_factory=list)
    citas: list[RegistroCita] = Field(default_factory=list)


class ResultadoNormalizacion(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    perfil: PerfilNormalizado
    hallazgos: list[HallazgoDQ] = Field(default_factory=list)


def normalizar_valor(valor: Decimal) -> str:
    """``Decimal`` sin ceros a la derecha y sin notación exponencial (``167.0`` -> ``167``)."""
    texto = format(valor.normalize(), "f")
    return "0" if texto in {"-0", "0"} else texto


def id_medicion(id_paciente: str, fecha: date, tipo: str, valor: Decimal) -> str:
    """``MED-`` + 16 hex de SHA-256 de ``id_paciente|fecha|tipo|valor normalizado``."""
    clave = f"{id_paciente}|{fecha.isoformat()}|{tipo}|{normalizar_valor(valor)}"
    return "MED-" + hashlib.sha256(clave.encode("utf-8")).hexdigest()[:16]


def especialidad_desde_detalle(detalle: str) -> str | None:
    """Extrae la especialidad de la plantilla ``"<subtipo> (<especialidad>)"``."""
    m = _RE_ESPECIALIDAD.search(detalle)
    if m is None:
        return None
    return m.group(1).strip() or None


def deduplicar_mediciones(
    mediciones: list[RegistroMedicion],
) -> tuple[list[RegistroMedicion], list[str]]:
    """Conserva una medición por ID (la primera en orden determinista). Devuelve los IDs duplicados."""
    unicas: dict[str, RegistroMedicion] = {}
    duplicados: list[str] = []
    for m in sorted(mediciones, key=_clave_medicion):
        if m.id_medicion in unicas:
            duplicados.append(m.id_medicion)
        else:
            unicas[m.id_medicion] = m
    return sorted(unicas.values(), key=_clave_medicion), sorted(set(duplicados))


def _clave_medicion(m: RegistroMedicion) -> tuple[date, str, str, bool]:
    return (m.fecha_medicion, m.tipo_medicion, m.id_medicion, m.fuera_de_rango_origen)


def normalizar_perfil(perfil: PerfilValido) -> ResultadoNormalizacion:
    hallazgos: list[HallazgoDQ] = []
    # Especialidad de respaldo para eventos cuyo `detalle` no la trae: la de la PRIMERA solicitud del perfil.
    # Con varias solicitudes (reglas-v0.2.0, R11) es una suposición: el evento queda con
    # `especialidad_inferida=True` y la calidad de datos lo informa (`especialidad_evento_inferida`).
    especialidad_principal = perfil.lista_espera[0].especialidad
    solicitudes = [
        s.model_copy(update={"diagnostico_cie10": normalizar_cie10(s.diagnostico_cie10)}) for s in perfil.lista_espera
    ]

    eventos = []
    for e in perfil.eventos_clinicos:
        especialidad = especialidad_desde_detalle(e.detalle)
        eventos.append(
            RegistroEvento(
                id_evento=e.id_evento,
                fecha_evento=e.fecha_evento,
                tipo_evento=e.tipo_evento,
                subtipo=e.subtipo,
                severidad=e.severidad,
                detalle=e.detalle,
                especialidad_evento=especialidad or especialidad_principal,
                especialidad_inferida=especialidad is None,
            )
        )
    eventos.sort(key=lambda x: (x.fecha_evento, x.id_evento))

    mediciones = [
        RegistroMedicion(
            id_medicion=id_medicion(perfil.id_paciente, m.fecha_medicion, m.tipo_medicion, m.valor),
            fecha_medicion=m.fecha_medicion,
            tipo_medicion=m.tipo_medicion,
            valor=m.valor,
            unidad=m.unidad,
            fuera_de_rango_origen=m.fuera_de_rango,
        )
        for m in perfil.mediciones
    ]
    mediciones, duplicados = deduplicar_mediciones(mediciones)
    if duplicados:
        hallazgos.append(
            HallazgoDQ(
                codigo="medicion_duplicada",
                nivel="info",
                ids_registro=duplicados,
                detalle=f"{len(duplicados)} medición(es) duplicada(s) por ID; se conserva una",
            )
        )

    citas_origen = [
        RegistroCita(
            id_cita=c.id_cita,
            id_box=c.id_box,
            fecha_cita=c.fecha_cita,
            especialidad=c.especialidad,
            estado_cita=c.estado_cita,
            minutos_atencion_real=c.minutos_atencion_real,
        )
        for c in perfil.citaciones
    ]
    fuera_de_orden = [b.id_cita for a, b in itertools.pairwise(citas_origen) if b.fecha_cita < a.fecha_cita]
    if fuera_de_orden:
        hallazgos.append(
            HallazgoDQ(
                codigo="citas_no_cronologicas",
                nivel="info",
                ids_registro=sorted(fuera_de_orden),
                detalle="citas no cronológicas en el origen",
            )
        )
    citas = sorted(citas_origen, key=lambda c: (c.fecha_cita, c.id_cita))

    return ResultadoNormalizacion(
        perfil=PerfilNormalizado(
            id_paciente=perfil.id_paciente,
            paciente=perfil.paciente,
            solicitudes=solicitudes,
            eventos=eventos,
            mediciones=mediciones,
            citas=citas,
        ),
        hallazgos=hallazgos,
    )
