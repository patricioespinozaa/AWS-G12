"""Contexto a fecha de corte (R2, sección 5.2) y línea de tiempo citada.

El filtro ``fecha <= fecha_corte`` está dentro de las funciones: no existe forma de pedir datos sin corte.
El contexto no tiene ``comuna``, ``prevision``, ``nivel_socioeconomico`` ni nombre.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import date
from typing import Final

from hlf_priorizacion.contrato.esquema import Solicitud
from hlf_priorizacion.ingesta.normalizacion import PerfilNormalizado, normalizar_valor
from hlf_priorizacion.modelos import ContextoPaciente, RegistroCita, RegistroCitado, SolicitudContexto

FECHA_EXTRACCION_DATASET: Final = date(2026, 10, 13)


class ErrorFechaCorte(ValueError):
    """``fecha_corte`` fuera del rango permitido (R2.2)."""


class SolicitudNoEncontrada(KeyError):
    pass


def anios_completos(desde: date, hasta: date) -> int:
    """Años completos entre dos fechas (``desde <= hasta``)."""
    anios = hasta.year - desde.year
    if (hasta.month, hasta.day) < (desde.month, desde.day):
        anios -= 1
    return max(0, anios)


def edad_a_la_fecha(edad_extraccion: int, fecha_corte: date, fecha_extraccion: date) -> int:
    """R2.3: ``edad_corte = edad - años completos entre fecha_corte y fecha_extraccion``."""
    return max(0, edad_extraccion - anios_completos(fecha_corte, fecha_extraccion))


def _solicitud_contexto(s: Solicitud, fecha_corte: date, fecha_extraccion: date) -> SolicitudContexto:
    return SolicitudContexto(
        id_solicitud=s.id_solicitud,
        especialidad=s.especialidad,
        sub_especialidad=s.sub_especialidad,
        diagnostico_cie10=s.diagnostico_cie10,
        diagnostico_texto=s.diagnostico_texto,
        prioridad_inicial=s.prioridad_inicial,
        fecha_ingreso_lista=s.fecha_ingreso_lista,
        origen_derivacion=s.origen_derivacion,
        estado_extraccion=s.estado,
        estado_a_la_fecha=s.estado if fecha_corte == fecha_extraccion else "desconocido_a_la_fecha",
    )


def huella_contexto(ctx: ContextoPaciente) -> str:
    """SHA-256 del contexto canónico (sin el propio campo ``huella``)."""
    texto = ctx.model_copy(update={"huella": ""}).model_dump_json()
    return "sha256:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()


def cita_egreso_inferido(citas: Iterable[RegistroCita], especialidad: str) -> RegistroCita | None:
    """R3.3: última cita ``asistio`` de la especialidad (las citas ya vienen filtradas al corte).

    La usan el contexto (egreso inferido de la solicitud evaluada) y el motor (vigencia de las otras
    solicitudes del paciente, R11.1), para que ambos apliquen exactamente la misma regla.
    """
    asistidas = [c for c in citas if c.estado_cita == "asistio" and c.especialidad == especialidad]
    return max(asistidas, key=lambda c: (c.fecha_cita, c.id_cita)) if asistidas else None


def validar_fecha_corte(fecha_corte: date, fecha_extraccion: date, fecha_ingreso: date | None = None) -> None:
    if fecha_corte > fecha_extraccion:
        raise ErrorFechaCorte("fecha_corte no puede ser posterior a fecha_extraccion")
    if fecha_ingreso is not None and fecha_corte < fecha_ingreso:
        raise ErrorFechaCorte("fecha_corte no puede ser anterior a fecha_ingreso_lista")


def contexto_a_fecha(
    perfil: PerfilNormalizado,
    id_solicitud: str,
    fecha_corte: date,
    fecha_extraccion: date = FECHA_EXTRACCION_DATASET,
) -> ContextoPaciente:
    """Contexto de una solicitud con solo lo que se sabía a ``fecha_corte`` (R2, R3.3)."""
    solicitud = next((s for s in perfil.solicitudes if s.id_solicitud == id_solicitud), None)
    if solicitud is None:
        raise SolicitudNoEncontrada(id_solicitud)
    validar_fecha_corte(fecha_corte, fecha_extraccion, solicitud.fecha_ingreso_lista)

    eventos = [e for e in perfil.eventos if e.fecha_evento <= fecha_corte]
    mediciones = [m for m in perfil.mediciones if m.fecha_medicion <= fecha_corte]
    citas = [c for c in perfil.citas if c.fecha_cita <= fecha_corte]

    defuncion = perfil.paciente.fecha_defuncion
    fallecido = defuncion is not None and defuncion <= fecha_corte

    # R3.3: egreso inferido solo si en la extracción figura atendido y hay una cita "asistio" de su
    # especialidad hasta el corte. Asistir no implica egreso para pacientes que siguen en espera.
    fecha_egreso: date | None = None
    id_cita_egreso: str | None = None
    if fecha_corte < fecha_extraccion and solicitud.estado == "atendido":
        ultima = cita_egreso_inferido(citas, solicitud.especialidad)
        if ultima is not None:
            fecha_egreso, id_cita_egreso = ultima.fecha_cita, ultima.id_cita

    # Sin fuga de información futura (R2, R11.1): solo las otras solicitudes que ya estaban en la lista al corte.
    otras = [
        _solicitud_contexto(s, fecha_corte, fecha_extraccion)
        for s in perfil.solicitudes
        if s.id_solicitud != id_solicitud and s.fecha_ingreso_lista <= fecha_corte
    ]

    ctx = ContextoPaciente(
        id_paciente=perfil.id_paciente,
        id_solicitud=id_solicitud,
        fecha_corte=fecha_corte,
        fecha_extraccion=fecha_extraccion,
        edad=edad_a_la_fecha(perfil.paciente.edad, fecha_corte, fecha_extraccion),
        sexo=perfil.paciente.sexo,
        solicitud=_solicitud_contexto(solicitud, fecha_corte, fecha_extraccion),
        fallecido_a_la_fecha=fallecido,
        fecha_defuncion=defuncion if fallecido else None,
        fecha_egreso_inferida=fecha_egreso,
        id_cita_egreso_inferido=id_cita_egreso,
        eventos=eventos,
        mediciones=mediciones,
        citas=citas,
        otras_solicitudes=otras,
    )
    return ctx.model_copy(update={"huella": huella_contexto(ctx)})


def linea_tiempo(perfil: PerfilNormalizado, fecha_corte: date) -> list[RegistroCitado]:
    """Registros del paciente hasta el corte, ordenados por fecha, cada uno con su ID."""
    registros: list[RegistroCitado] = []
    registros.extend(
        RegistroCitado(
            fecha=s.fecha_ingreso_lista,
            tipo_registro="solicitud",
            id_registro=s.id_solicitud,
            descripcion=(
                f"ingreso a la lista de {s.especialidad} ({s.diagnostico_cie10}, prioridad {s.prioridad_inicial})"
            ),
        )
        for s in perfil.solicitudes
        if s.fecha_ingreso_lista <= fecha_corte
    )
    registros.extend(
        RegistroCitado(
            fecha=e.fecha_evento,
            tipo_registro="evento",
            id_registro=e.id_evento,
            descripcion=f"{e.tipo_evento}: {e.subtipo} ({e.severidad}, {e.especialidad_evento})",
        )
        for e in perfil.eventos
        if e.fecha_evento <= fecha_corte
    )
    registros.extend(
        RegistroCitado(
            fecha=m.fecha_medicion,
            tipo_registro="medicion",
            id_registro=m.id_medicion,
            descripcion=f"{m.tipo_medicion} = {normalizar_valor(m.valor)} {m.unidad}",
        )
        for m in perfil.mediciones
        if m.fecha_medicion <= fecha_corte
    )
    registros.extend(
        RegistroCitado(
            fecha=c.fecha_cita,
            tipo_registro="cita",
            id_registro=c.id_cita,
            descripcion=f"cita de {c.especialidad} en {c.id_box}: {c.estado_cita}",
        )
        for c in perfil.citas
        if c.fecha_cita <= fecha_corte
    )
    return sorted(registros, key=lambda r: (r.fecha, r.tipo_registro, r.id_registro))


class Repositorio:
    """Acceso en memoria a los perfiles normalizados de una extracción."""

    def __init__(self, perfiles: Iterable[PerfilNormalizado], fecha_extraccion: date = FECHA_EXTRACCION_DATASET):
        self.fecha_extraccion = fecha_extraccion
        self._perfiles: dict[str, PerfilNormalizado] = {}
        self._paciente_de_solicitud: dict[str, str] = {}
        for p in perfiles:
            self._perfiles[p.id_paciente] = p
            for s in p.solicitudes:
                self._paciente_de_solicitud[s.id_solicitud] = p.id_paciente

    @property
    def perfiles(self) -> list[PerfilNormalizado]:
        return [self._perfiles[k] for k in sorted(self._perfiles)]

    def perfil_de_solicitud(self, id_solicitud: str) -> PerfilNormalizado:
        try:
            return self._perfiles[self._paciente_de_solicitud[id_solicitud]]
        except KeyError as e:
            raise SolicitudNoEncontrada(id_solicitud) from e

    def contexto_a_fecha(self, id_solicitud: str, fecha_corte: date) -> ContextoPaciente:
        return contexto_a_fecha(
            self.perfil_de_solicitud(id_solicitud), id_solicitud, fecha_corte, self.fecha_extraccion
        )

    def linea_tiempo(self, id_paciente: str, fecha_corte: date) -> list[RegistroCitado]:
        validar_fecha_corte(fecha_corte, self.fecha_extraccion)
        return linea_tiempo(self._perfiles[id_paciente], fecha_corte)
