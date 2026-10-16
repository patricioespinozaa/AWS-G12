"""Canal del paciente (maqueta web): mensajes, exámenes externos y su validación por la Administradora."""
import base64
import binascii
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from priorizacion import nocturno
from priorizacion import reglas as R
from priorizacion.archivos import ErrorArchivo, guardar_evidencia
from priorizacion.disponibilidad import evaluar_disponibilidad
from priorizacion.motor import evaluar

from .. import estado as E
from ..seguridad import Persona, administradora
from ..serializacion import a_json

router = APIRouter()
MAX_ARCHIVO = 10 * 1024 * 1024


class MensajeIn(BaseModel):
    id_paciente: str
    fecha: str
    tipo: Literal["confirma_asistencia", "no_puede_asistir", "sintoma_alarma", "sintoma_sin_alarma", "sin_respuesta"]
    detalle: str = ""


class EvidenciaIn(BaseModel):
    id_paciente: str
    fecha_examen: str
    tipo_medicion: str
    valor: float
    lugar: str = ""
    fecha_recepcion: str
    archivo_nombre: str | None = None
    archivo_base64: str | None = Field(default=None, description="Contenido del PDF o imagen en base64")


class RevisionIn(BaseModel):
    """Revisa la Administradora (única usuaria; desde F0007, la sesión). No viene en el cuerpo."""
    estado: Literal["validada", "rechazada"]
    nota: str = ""
    corte: str | None = None


@router.get("/api/canal/{id_paciente}")
def canal_paciente(id_paciente: str, corte: str | None = None):
    c = E.fecha(corte)
    sol = E.paciente(id_paciente)
    msj, ev = E.registro.mensajes(), E.registro.evidencias()
    disp = evaluar_disponibilidad(sol, E.repo.historias[id_paciente], c, msj)
    return {"solicitud": {"id_solicitud": sol.id_solicitud, "nombre": sol.nombre, "especialidad": sol.especialidad,
                          "diagnostico": f"{sol.cie10} {sol.diagnostico}"},
            "disponibilidad": a_json(disp),
            "requisitos": [R.NOMBRE_MEDICION[t] for t in R.REQUISITO_EXAMEN.get(sol.especialidad, ())],
            "mensajes": a_json(msj[msj["id_paciente"] == id_paciente]) if len(msj) else [],
            "evidencias": a_json(ev[ev["id_paciente"] == id_paciente]) if len(ev) else []}


@router.post("/api/canal/mensajes")
def nuevo_mensaje(m: MensajeIn):
    E.paciente(m.id_paciente)
    with E.escritura:
        idm = E.registro.agregar_mensaje(m.id_paciente, E.fecha(m.fecha), m.tipo, m.detalle)
    return {"id_mensaje": idm, "respuesta": "Su información fue recibida y será revisada por el equipo. "
                                            "Esto no cambia por sí solo su fecha de atención."}


@router.post("/api/canal/evidencias")
def nueva_evidencia(e: EvidenciaIn):
    E.paciente(e.id_paciente)
    if e.tipo_medicion not in R.RANGOS_NORMALES:
        raise HTTPException(422, f"Tipo de examen desconocido: {e.tipo_medicion}")
    fecha_examen, fecha_recepcion = E.fecha(e.fecha_examen), E.fecha(e.fecha_recepcion)
    if fecha_examen > fecha_recepcion:
        raise HTTPException(422, "La fecha del examen no puede ser posterior a la de recepción.")
    archivo = None
    if e.archivo_base64 and e.archivo_nombre:
        try:
            contenido = base64.b64decode(e.archivo_base64.split(",")[-1], validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "El archivo no viene en base64 válido.")
        if len(contenido) > MAX_ARCHIVO:
            raise HTTPException(413, "El archivo supera 10 MB.")
        try:
            archivo = guardar_evidencia(e.id_paciente, e.archivo_nombre, contenido)
        except ErrorArchivo as err:
            raise HTTPException(422, str(err))
    with E.escritura:
        ide = E.registro.agregar_evidencia(e.id_paciente, fecha_examen, e.tipo_medicion, e.valor, e.lugar,
                                           archivo, fecha_recepcion)
    return {"id_evidencia": ide, "respuesta": "Recibimos su examen. Un profesional lo revisará antes de usarlo; "
                                              "esto no cambia por sí solo su fecha de atención."}


@router.get("/api/canal-pendientes")
def pendientes():
    ev, msj = E.registro.evidencias(), E.registro.mensajes()
    nombres = {s.id_paciente: s.nombre for s in E.repo.solicitudes.values()}
    ev = ev[ev["estado"] == "pendiente"] if len(ev) else ev
    msj = msj[(msj["estado"] == "pendiente")] if len(msj) else msj
    return {"evidencias": [{**x, "nombre": nombres.get(x["id_paciente"]),
                            "nombre_examen": R.NOMBRE_MEDICION.get(x["tipo_medicion"]),
                            "unidad": R.UNIDADES.get(x["tipo_medicion"])} for x in a_json(ev)],
            "alarmas": [{**x, "nombre": nombres.get(x["id_paciente"])} for x in a_json(msj)]}


def _antes_despues(id_paciente: str, corte: date, aplicar):
    sol = E.paciente(id_paciente)
    decs = E.decisiones(sol.id_solicitud)
    antes = evaluar(sol, E.repo.historias[id_paciente], corte, decs)
    E.exigir_sin_recalculo()
    with E.escritura:
        aplicar()
        nocturno.recalcular_solicitud(E.repo, E.registro, sol.id_solicitud)
    despues = evaluar(sol, E.repo.historias[id_paciente], corte, decs)
    resumen = lambda r: {"nivel_propuesto": r.nivel_propuesto, "puntaje_nivel": r.puntaje_nivel,  # noqa: E731
                         "alerta": r.alerta, "motivo_principal": r.motivo_principal}
    return {"id_solicitud": sol.id_solicitud, "antes": resumen(antes), "despues": resumen(despues)}


@router.post("/api/canal/evidencias/{id_evidencia}/revision")
def revisar_evidencia(id_evidencia: str, rev: RevisionIn, quien: Persona = Depends(administradora)):
    ev = E.registro.evidencias()
    fila = ev[ev["id_evidencia"] == id_evidencia]
    if fila.empty:
        raise HTTPException(404, f"No existe la evidencia {id_evidencia}")
    return _antes_despues(fila.iloc[0]["id_paciente"], E.fecha(rev.corte),
                          lambda: E.registro.revisar_evidencia(id_evidencia, rev.estado, quien.id_usuario, rev.nota))


@router.post("/api/canal/mensajes/{id_mensaje}/revision")
def revisar_mensaje(id_mensaje: str, rev: RevisionIn, quien: Persona = Depends(administradora)):
    msj = E.registro.mensajes()
    fila = msj[msj["id_mensaje"] == id_mensaje]
    if fila.empty:
        raise HTTPException(404, f"No existe el mensaje {id_mensaje}")
    return _antes_despues(fila.iloc[0]["id_paciente"], E.fecha(rev.corte),
                          lambda: E.registro.revisar_mensaje(id_mensaje, rev.estado, quien.id_usuario))
