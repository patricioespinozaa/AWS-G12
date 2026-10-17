"""Ficha de una solicitud: resultado, serie, datos clínicos, explicación y decisiones de la Administradora."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from priorizacion import nocturno
from priorizacion import reglas as R
from priorizacion.disponibilidad import evaluar_disponibilidad
from priorizacion.explicacion import explicacion_llm, explicacion_plantilla
from priorizacion.ficha import ficha_consolidada, resumen_clinico
from priorizacion.motor import evaluar, huella_datos

from .. import estado as E
from ..seguridad import Persona, administradora
from ..serializacion import a_json

router = APIRouter()
MAX_AJUSTE = 100.0                     # mismo límite que la base (decision_ajuste_acotado)


@router.get("/api/solicitudes/{id_solicitud}")
def ficha(id_solicitud: str, corte: str | None = None):
    c = E.fecha(corte)
    sol = E.solicitud(id_solicitud)
    hist = E.repo.historias[sol.id_paciente]
    decs = E.decisiones(id_solicitud)
    r = evaluar(sol, hist, c, decs)
    disp = evaluar_disponibilidad(sol, hist, c, E.registro.mensajes())
    secciones = ficha_consolidada(sol, hist, c, E.registro.evidencias(), E.registro.mensajes())
    clase, razon = R.RIESGO_BASAL_DX.get(sol.cie10, ("medio", "sin clasificar"))
    return {
        "corte": c.isoformat(),
        "solicitud": {**a_json(sol), "canal_origen": R.CANAL_ORIGEN.get(sol.origen_derivacion),
                      "riesgo_basal": clase, "riesgo_basal_razon": razon,
                      "caso_referencia": E.CASOS_REFERENCIA.get(sol.id_paciente)},
        "resultado": E.resultado_json(r),
        "disponibilidad": a_json(disp),
        "resumen": resumen_clinico(sol, hist, c, r),
        "explicacion": explicacion_plantilla(r),
        "huella_datos": huella_datos(sol, hist, c, decs),
        "ficha": {k: a_json(v) for k, v in secciones.items()},
        "decisiones": a_json(E.registro.decisiones(id_solicitud)),
        "propuestas": a_json(E.registro.propuestas(id_solicitud).drop(columns=["motivos_alerta"], errors="ignore")),
        "estimacion": _estimacion(id_solicitud, c),
    }


def _estimacion(id_solicitud: str, corte) -> dict | None:
    """La última estimación de espera calculada hasta el corte (F0006). Uso interno: no se informa al paciente."""
    est = E.registro.estimaciones(id_solicitud)
    est = est[est["fecha_calculo"] <= corte.isoformat()]
    return a_json(est.iloc[-1].to_dict()) if len(est) else None


@router.get("/api/solicitudes/{id_solicitud}/serie")
def serie(id_solicitud: str):
    sol = E.solicitud(id_solicitud)
    s = E.registro.serie(id_solicitud)
    hist = E.repo.historias[sol.id_paciente]
    cambios = s[s["nivel_propuesto"] != s["nivel_propuesto"].shift()].iloc[1:].copy()
    cambios["desde"] = s["nivel_propuesto"].shift().loc[cambios.index]
    return {
        "serie": a_json(s.drop(columns=["id_paciente", "especialidad"])),
        "cambios": a_json(cambios[["fecha", "desde", "nivel_propuesto", "alerta", "motivo_principal", "puntaje_nivel"]]),
        "eventos": [{"fecha": e.fecha.isoformat(), "tipo": R.NOMBRE_TIPO_EVENTO[e.tipo], "subtipo": e.subtipo,
                     "severidad": e.severidad, "id_evento": e.id_evento} for e in hist.eventos],
        "externas": [{"fecha": m.fecha.isoformat(), "tipo": R.NOMBRE_MEDICION[m.tipo], "valor": m.valor, "ref": m.ref}
                     for lst in hist.mediciones.values() for m in lst if m.origen == "externa"],
        "decisiones": a_json(E.registro.decisiones(id_solicitud)),
        "umbrales": {"media": R.UMBRAL_MEDIA, "alta": R.UMBRAL_ALTA},
    }


@router.get("/api/solicitudes/{id_solicitud}/clinico")
def clinico(id_solicitud: str, corte: str | None = None):
    c = E.fecha(corte)
    sol = E.solicitud(id_solicitud)
    hist = E.repo.historias[sol.id_paciente]
    mediciones = []
    for tipo, lst in hist.mediciones_hasta(c).items():
        if lst:
            mediciones.append({"tipo": tipo, "nombre": R.NOMBRE_MEDICION[tipo], "unidad": R.UNIDADES[tipo],
                               "rango": R.RANGOS_NORMALES[tipo],
                               "puntos": [{"fecha": m.fecha.isoformat(), "valor": m.valor, "fuera": m.fuera_de_rango,
                                           "origen": m.origen, "ref": m.ref} for m in lst]})
    return {
        "fecha_ingreso": sol.fecha_ingreso.isoformat(),
        "fecha_defuncion": sol.fecha_defuncion.isoformat() if sol.fecha_defuncion and sol.fecha_defuncion <= c else None,
        "mediciones": mediciones,
        "eventos": [{"fecha": e.fecha.isoformat(), "tipo": R.NOMBRE_TIPO_EVENTO[e.tipo], "subtipo": e.subtipo,
                     "severidad": e.severidad, "id_evento": e.id_evento} for e in hist.eventos_hasta(c)],
        "citas": [{"fecha": x.fecha.isoformat(), "estado": x.estado, "id_box": x.id_box, "id_cita": x.id_cita}
                  for x in hist.citas_hasta(c)],
    }


@router.post("/api/solicitudes/{id_solicitud}/explicacion-ia")
def explicacion_ia(id_solicitud: str, corte: str | None = None):
    c = E.fecha(corte)
    sol = E.solicitud(id_solicitud)
    r = evaluar(sol, E.repo.historias[sol.id_paciente], c, E.decisiones(id_solicitud))
    return a_json(explicacion_llm(r))


class DecisionIn(BaseModel):
    """La autora es la Administradora con sesión iniciada (F0007). Nunca viene en el cuerpo."""
    corte: str
    decision: Literal["acepta", "ajusta", "rechaza"]
    nivel_ajuste: Literal["alta", "media", "baja"] | None = None
    motivo: str = ""
    # Puntaje de orden que fija la Administradora (F0007). Sin él, se mantiene el ajuste que hubiera
    puntaje: float | None = Field(None, ge=0, le=200)


@router.post("/api/solicitudes/{id_solicitud}/decisiones")
def registrar_decision(id_solicitud: str, d: DecisionIn, quien: Persona = Depends(administradora)):
    c = E.fecha(d.corte)
    sol = E.solicitud(id_solicitud)
    if d.decision != "acepta" and not d.motivo.strip():
        raise HTTPException(422, "Indica el motivo para ajustar o rechazar la propuesta.")
    E.exigir_sin_recalculo()
    with E.escritura:
        hist = E.repo.historias[sol.id_paciente]
        decs = E.decisiones(id_solicitud)
        r = evaluar(sol, hist, c, decs)
        if r.excluido:
            raise HTTPException(409, f"La solicitud no está activa al {c.isoformat()}: {r.motivo_exclusion}")
        ajuste = _ajuste_puntaje(r, d.puntaje)
        if ajuste is not None and not d.motivo.strip():
            raise HTTPException(422, "Indica el motivo para cambiar el puntaje.")
        if d.decision == "ajusta" and not d.nivel_ajuste and ajuste is None:
            raise HTTPException(422, "Indica el nivel o el puntaje que se ajusta.")
        nivel_ajuste = d.nivel_ajuste or r.prioridad_vigente       # solo cambia el puntaje: el nivel se mantiene
        final = {"acepta": r.nivel_propuesto, "ajusta": nivel_ajuste, "rechaza": r.prioridad_vigente}[d.decision]
        motivo = d.motivo.strip() or "Acepta la propuesta"
        id_prop = E.registro.guardar_propuesta(r, huella_datos(sol, hist, c, decs), explicacion_plantilla(r),
                                               "plantilla", "validacion")
        E.registro.registrar_decision(id_prop, r, d.decision, final, motivo, quien.id_usuario, ajuste)
        nocturno.recalcular_solicitud(E.repo, E.registro, id_solicitud)
    puntaje = "" if ajuste is None else (
        f" Puntaje de orden {r.puntaje + ajuste:g} (motor {r.puntaje:g}, ajuste {ajuste:+g})." if ajuste
        else f" Puntaje de orden: vuelve al del motor ({r.puntaje:g}).")
    return {"ok": True, "prioridad_final": final, "ajuste_puntaje": ajuste,
            "mensaje": f"Decisión registrada: {d.decision} → prioridad {final} desde el {c.isoformat()}.{puntaje} "
                       "La serie del paciente y su cola se recalcularon."}


def _ajuste_puntaje(r, puntaje: float | None) -> float | None:
    """Ajuste que implica el puntaje fijado por la Administradora (None si no lo cambia). El puntaje del motor
    queda intacto: se guarda la diferencia, que rige hasta la siguiente decisión que la cambie."""
    if puntaje is None:
        return None
    ajuste = round(puntaje - r.puntaje, 2)
    if abs(ajuste - r.ajuste_puntaje) < 0.01:
        return None                                  # mismo puntaje vigente: no hay cambio
    if abs(ajuste) > MAX_AJUSTE:
        raise HTTPException(422, f"El ajuste no puede superar ±{MAX_AJUSTE:g} puntos sobre el puntaje del motor "
                                 f"({r.puntaje:g}).")
    return ajuste


@router.get("/api/propuestas/{id_propuesta}/factores")
def factores_propuesta(id_propuesta: int):
    return a_json(E.registro.factores(id_propuesta))
