"""API REST del MVP (FastAPI). Expone el motor de priorización a la app React (web/).

Ejecutar desde la raíz del repositorio:
    uvicorn api.main:app --reload --port 8000

En AWS: contenedor en App Runner/ECS o Lambda + API Gateway. La consolidación nocturna corre aparte
(EventBridge → Lambda/Glue); aquí también se puede disparar a mano para la demo.
"""
from __future__ import annotations

import base64
import threading
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from priorizacion import config, nocturno
from priorizacion import reglas as R
from priorizacion.bandeja import construir_bandeja
from priorizacion.datos import Repositorio
from priorizacion.disponibilidad import evaluar_disponibilidad, proponer_agenda
from priorizacion.explicacion import explicacion_llm, explicacion_plantilla
from priorizacion.ficha import ficha_consolidada, resumen_clinico
from priorizacion.kpis import concordancia, equidad, invisibles, tiempo_reevaluacion
from priorizacion.motor import Decision, Resultado, evaluar, huella_datos
from priorizacion.registro import Registro

CASOS_REFERENCIA = {
    "PAC-HLF-00002": "Deterioro agudo",
    "PAC-HLF-00001": "Deterioro progresivo",
    "PAC-HLF-00028": "Mejora",
    "PAC-HLF-00020": "Inasistencia",
    "PAC-HLF-00032": "Estable / atendido",
    "PAC-HLF-00009": "Fallecido en espera",
}

app = FastAPI(title="Priorización dinámica HLF", version=R.VERSION_REGLAS)
repo = Repositorio.desde_csv()
registro = Registro()
repo.aplicar_registro(registro.evidencias(), registro.mensajes())
_escritura = threading.Lock()
_cache: dict[tuple, object] = {}

if not registro.hay_serie():          # primera vez: consolidación nocturna sobre toda la historia
    nocturno.ejecutar(repo, registro)


# -- utilidades ---------------------------------------------------------------------------------
def a_json(x):
    """Convierte dataclasses, fechas, DataFrames y tipos numpy en estructuras JSON."""
    if is_dataclass(x):
        return {k: a_json(v) for k, v in asdict(x).items()}
    if isinstance(x, dict):
        return {str(k): a_json(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [a_json(v) for v in x]
    if isinstance(x, pd.DataFrame):
        return a_json(x.replace({np.nan: None}).to_dict(orient="records"))
    if isinstance(x, pd.Series):
        return a_json(x.to_dict())
    if isinstance(x, (date, pd.Timestamp)):
        return x.isoformat()[:10]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return None if np.isnan(x) else round(float(x), 4)
    if isinstance(x, float):
        return None if np.isnan(x) else round(x, 4)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def _fecha(valor: str | None) -> date:
    if not valor:
        return config.FECHA_REFERENCIA
    try:
        f = date.fromisoformat(valor)
    except ValueError:
        raise HTTPException(400, f"Fecha inválida: {valor}")
    return min(max(f, repo.fecha_min), config.FECHA_REFERENCIA)


def _solicitud(id_solicitud: str):
    if id_solicitud not in repo.solicitudes:
        raise HTTPException(404, f"No existe la solicitud {id_solicitud}")
    return repo.solicitudes[id_solicitud]


def _decisiones(id_solicitud: str) -> list[Decision]:
    return [Decision(date.fromisoformat(d.fecha_corte), d.prioridad_final)
            for d in registro.decisiones(id_solicitud).itertuples(index=False)]


def _cacheado(clave: tuple, calcular):
    clave = clave + (registro.version(),)
    if clave not in _cache:
        if len(_cache) > 40:
            _cache.clear()
        _cache[clave] = calcular()
    return _cache[clave]


def _bandeja(corte: date) -> tuple[pd.DataFrame, dict[str, Resultado]]:
    return _cacheado(("bandeja", corte), lambda: construir_bandeja(repo, registro, corte))


def _serie() -> pd.DataFrame:
    return _cacheado(("serie",), registro.serie_resumen)


def _resultado_json(r: Resultado) -> dict:
    d = a_json(r)
    d["motivo_principal"] = r.motivo_principal
    return d


# -- metadatos ----------------------------------------------------------------------------------
@app.get("/api/meta")
def meta():
    return {
        "fecha_referencia": config.FECHA_REFERENCIA.isoformat(),
        "fecha_min": repo.fecha_min.isoformat(),
        "especialidades": sorted({s.especialidad for s in repo.solicitudes.values()}),
        "version_reglas": R.VERSION_REGLAS,
        "umbrales": {"media": R.UMBRAL_MEDIA, "alta": R.UMBRAL_ALTA},
        "llm": {"activo": config.LLM_PROVEEDOR == "bedrock", "modelo": config.BEDROCK_MODEL_ID},
        "agenda": {"min": repo.agenda["fecha"].min().date().isoformat(), "max": repo.agenda["fecha"].max().date().isoformat()},
        "tipos_medicion": [{"tipo": t, "nombre": R.NOMBRE_MEDICION[t], "unidad": R.UNIDADES[t],
                            "rango": R.RANGOS_NORMALES[t]} for t in R.RANGOS_NORMALES],
        "casos_referencia": [{"id_paciente": p, "id_solicitud": repo.solicitud_de_paciente(p).id_solicitud, "patron": n}
                             for p, n in CASOS_REFERENCIA.items()],
    }


@app.get("/api/solicitudes")
def solicitudes():
    return [{"id_solicitud": s.id_solicitud, "id_paciente": s.id_paciente, "nombre": s.nombre,
             "especialidad": s.especialidad, "cie10": s.cie10, "diagnostico": s.diagnostico,
             "caso_referencia": CASOS_REFERENCIA.get(s.id_paciente)}
            for s in sorted(repo.solicitudes.values(), key=lambda s: s.id_paciente)]


# -- bandeja ------------------------------------------------------------------------------------
@app.get("/api/bandeja")
def bandeja(corte: str | None = None):
    c = _fecha(corte)
    df, _ = _bandeja(c)
    if len(df):
        df = df.assign(caso_referencia=df["id_paciente"].map(CASOS_REFERENCIA))
    return {"corte": c.isoformat(), "filas": a_json(df)}


# -- ficha del paciente ---------------------------------------------------------------------------
@app.get("/api/solicitudes/{id_solicitud}")
def ficha(id_solicitud: str, corte: str | None = None):
    c = _fecha(corte)
    sol = _solicitud(id_solicitud)
    hist = repo.historias[sol.id_paciente]
    decs = _decisiones(id_solicitud)
    r = evaluar(sol, hist, c, decs)
    disp = evaluar_disponibilidad(sol, hist, c, registro.mensajes())
    secciones = ficha_consolidada(sol, hist, c, registro.evidencias(), registro.mensajes())
    clase, razon = R.RIESGO_BASAL_DX.get(sol.cie10, ("medio", "sin clasificar"))
    return {
        "corte": c.isoformat(),
        "solicitud": {**a_json(sol), "canal_origen": R.CANAL_ORIGEN.get(sol.origen_derivacion),
                      "riesgo_basal": clase, "riesgo_basal_razon": razon,
                      "caso_referencia": CASOS_REFERENCIA.get(sol.id_paciente)},
        "resultado": _resultado_json(r),
        "disponibilidad": a_json(disp),
        "resumen": resumen_clinico(sol, hist, c, r),
        "explicacion": explicacion_plantilla(r),
        "huella_datos": huella_datos(sol, hist, c, decs),
        "ficha": {k: a_json(v) for k, v in secciones.items()},
        "decisiones": a_json(registro.decisiones(id_solicitud)),
        "propuestas": a_json(registro.propuestas(id_solicitud).drop(columns=["motivos_alerta"], errors="ignore")),
    }


@app.get("/api/solicitudes/{id_solicitud}/serie")
def serie(id_solicitud: str):
    sol = _solicitud(id_solicitud)
    s = registro.serie(id_solicitud)
    hist = repo.historias[sol.id_paciente]
    cambios = s[s["nivel_propuesto"] != s["nivel_propuesto"].shift()].iloc[1:].copy()
    cambios["desde"] = s["nivel_propuesto"].shift().loc[cambios.index]
    return {
        "serie": a_json(s.drop(columns=["id_paciente", "especialidad"])),
        "cambios": a_json(cambios[["fecha", "desde", "nivel_propuesto", "alerta", "motivo_principal", "puntaje_nivel"]]),
        "eventos": [{"fecha": e.fecha.isoformat(), "tipo": R.NOMBRE_TIPO_EVENTO[e.tipo], "subtipo": e.subtipo,
                     "severidad": e.severidad, "id_evento": e.id_evento} for e in hist.eventos],
        "externas": [{"fecha": m.fecha.isoformat(), "tipo": R.NOMBRE_MEDICION[m.tipo], "valor": m.valor, "ref": m.ref}
                     for lst in hist.mediciones.values() for m in lst if m.origen == "externa"],
        "decisiones": a_json(registro.decisiones(id_solicitud)),
        "umbrales": {"media": R.UMBRAL_MEDIA, "alta": R.UMBRAL_ALTA},
    }


@app.get("/api/solicitudes/{id_solicitud}/clinico")
def clinico(id_solicitud: str, corte: str | None = None):
    c = _fecha(corte)
    sol = _solicitud(id_solicitud)
    hist = repo.historias[sol.id_paciente]
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


@app.post("/api/solicitudes/{id_solicitud}/explicacion-ia")
def explicacion_ia(id_solicitud: str, corte: str | None = None):
    c = _fecha(corte)
    sol = _solicitud(id_solicitud)
    r = evaluar(sol, repo.historias[sol.id_paciente], c, _decisiones(id_solicitud))
    return a_json(explicacion_llm(r))


class DecisionIn(BaseModel):
    corte: str
    decision: Literal["acepta", "ajusta", "rechaza"]
    nivel_ajuste: Literal["alta", "media", "baja"] | None = None
    motivo: str = ""
    usuario: str = "equipo_clinico"


@app.post("/api/solicitudes/{id_solicitud}/decisiones")
def registrar_decision(id_solicitud: str, d: DecisionIn):
    c = _fecha(d.corte)
    sol = _solicitud(id_solicitud)
    if d.decision != "acepta" and not d.motivo.strip():
        raise HTTPException(422, "Indica el motivo para ajustar o rechazar la propuesta.")
    if d.decision == "ajusta" and not d.nivel_ajuste:
        raise HTTPException(422, "Indica el nivel al que se ajusta.")
    with _escritura:
        hist = repo.historias[sol.id_paciente]
        decs = _decisiones(id_solicitud)
        r = evaluar(sol, hist, c, decs)
        if r.excluido:
            raise HTTPException(409, f"La solicitud no está activa al {c.isoformat()}: {r.motivo_exclusion}")
        final = {"acepta": r.nivel_propuesto, "ajusta": d.nivel_ajuste, "rechaza": r.prioridad_vigente}[d.decision]
        id_prop = registro.guardar_propuesta(r, huella_datos(sol, hist, c, decs), explicacion_plantilla(r),
                                             "plantilla", "validacion")
        registro.registrar_decision(id_prop, r, d.decision, final, d.motivo.strip(), d.usuario.strip() or "equipo_clinico")
        nocturno.recalcular_solicitud(repo, registro, id_solicitud)
    return {"ok": True, "prioridad_final": final,
            "mensaje": f"Decisión registrada: {d.decision} → prioridad {final} desde el {c.isoformat()}. "
                       "La serie del paciente y su cola se recalcularon."}


@app.get("/api/propuestas/{id_propuesta}/factores")
def factores_propuesta(id_propuesta: int):
    return a_json(registro.factores(id_propuesta))


# -- agenda y box --------------------------------------------------------------------------------
@app.get("/api/agenda")
def agenda(fecha: str, especialidad: str):
    f = _fecha(fecha)
    df, _ = _bandeja(f)
    if df.empty:
        return {"fecha": f.isoformat(), "cupos_libres": 0, "bloques": [], "asignados": [], "reemplazos": [], "acciones": []}
    res = proponer_agenda(df, repo.agenda, f, especialidad)
    return {"fecha": f.isoformat(), "especialidad": especialidad, **{k: a_json(v) for k, v in res.items()}}


@app.get("/api/box")
def panel_box(corte: str | None = None):
    c = _fecha(corte)

    def calcular():
        ag = repo.agenda[repo.agenda["fecha"] <= pd.Timestamp(c)].copy()
        ci = repo.tablas["citas"][repo.tablas["citas"]["fecha_cita"] <= pd.Timestamp(c)].copy()
        if ag.empty:
            return {"hay_agenda": False}
        por_esp = ag.groupby("especialidad").agg(
            box=("id_box", "nunique"), capacidad=("capacidad_cupos", "sum"), usados=("cupos_usados", "sum"),
            sobretiempo_medio=("minutos_sobretiempo", "mean"),
            sobretiempo_p90=("minutos_sobretiempo", lambda s: s.quantile(0.9))).reset_index()
        por_esp["ocupacion"] = por_esp["usados"] / por_esp["capacidad"]
        por_esp["pct_capacidad"] = por_esp["capacidad"] / por_esp["capacidad"].sum()
        df, _ = _bandeja(c)
        demanda = df["especialidad"].value_counts(normalize=True) if len(df) else pd.Series(dtype=float)
        por_esp["pct_demanda"] = por_esp["especialidad"].map(demanda).fillna(0)
        por_esp["demanda_sobre_capacidad"] = por_esp["pct_demanda"] / por_esp["pct_capacidad"]
        por_esp["alertas_en_cola"] = por_esp["especialidad"].map(df.groupby("especialidad")["alerta"].sum()
                                                                if len(df) else {}).fillna(0)
        ag["semana"] = ag["fecha"].dt.to_period("W").dt.start_time.dt.date.astype(str)
        sem = ag.groupby(["semana", "especialidad"])[["cupos_usados", "capacidad_cupos"]].sum()
        sem = (sem["cupos_usados"] / sem["capacidad_cupos"]).unstack().reset_index()
        citas = ci.groupby("especialidad")["estado_cita"].value_counts().unstack(fill_value=0).reset_index()
        for col in ["asistio", "no_asistio", "reprogramo", "cancelo"]:
            if col not in citas:
                citas[col] = 0
        citas["tasa_no_show"] = citas["no_asistio"] / citas[["asistio", "no_asistio", "reprogramo", "cancelo"]].sum(axis=1)
        return {
            "hay_agenda": True,
            "desde": ag["fecha"].min().date().isoformat(), "hasta": ag["fecha"].max().date().isoformat(),
            "ocupacion_global": float(ag["cupos_usados"].sum() / ag["capacidad_cupos"].sum()),
            "por_especialidad": a_json(por_esp.sort_values("demanda_sobre_capacidad", ascending=False)),
            "semanal": a_json(sem), "citas": a_json(citas),
            "no_show_global": float((ci["estado_cita"] == "no_asistio").mean()) if len(ci) else None,
            "duracion_real_mediana": float(ci["minutos_atencion_real"].median()) if ci["minutos_atencion_real"].notna().any() else None,
            "cupo_teorico_mediana": float((300 / ag["capacidad_cupos"]).median()),
        }
    return _cacheado(("box", c), calcular)


# -- canal del paciente (maqueta) -----------------------------------------------------------------
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
    estado: Literal["validada", "rechazada"]
    revisado_por: str = "tens"
    nota: str = ""
    corte: str | None = None


def _paciente(id_paciente: str):
    try:
        return repo.solicitud_de_paciente(id_paciente)
    except StopIteration:
        raise HTTPException(404, f"No existe el paciente {id_paciente}")


@app.get("/api/canal/{id_paciente}")
def canal_paciente(id_paciente: str, corte: str | None = None):
    c = _fecha(corte)
    sol = _paciente(id_paciente)
    msj, ev = registro.mensajes(), registro.evidencias()
    disp = evaluar_disponibilidad(sol, repo.historias[id_paciente], c, msj)
    return {"solicitud": {"id_solicitud": sol.id_solicitud, "nombre": sol.nombre, "especialidad": sol.especialidad,
                          "diagnostico": f"{sol.cie10} {sol.diagnostico}"},
            "disponibilidad": a_json(disp),
            "requisitos": [R.NOMBRE_MEDICION[t] for t in R.REQUISITO_EXAMEN.get(sol.especialidad, ())],
            "mensajes": a_json(msj[msj["id_paciente"] == id_paciente]) if len(msj) else [],
            "evidencias": a_json(ev[ev["id_paciente"] == id_paciente]) if len(ev) else []}


@app.post("/api/canal/mensajes")
def nuevo_mensaje(m: MensajeIn):
    _paciente(m.id_paciente)
    with _escritura:
        idm = registro.agregar_mensaje(m.id_paciente, _fecha(m.fecha), m.tipo, m.detalle)
    return {"id_mensaje": idm, "respuesta": "Su información fue recibida y será revisada por el equipo. "
                                            "Esto no cambia por sí solo su fecha de atención."}


@app.post("/api/canal/evidencias")
def nueva_evidencia(e: EvidenciaIn):
    _paciente(e.id_paciente)
    if e.tipo_medicion not in R.RANGOS_NORMALES:
        raise HTTPException(422, f"Tipo de examen desconocido: {e.tipo_medicion}")
    archivo = None
    if e.archivo_base64 and e.archivo_nombre:
        config.EVIDENCIA_DIR.mkdir(parents=True, exist_ok=True)
        archivo = f"{e.id_paciente}_{Path(e.archivo_nombre).name}"
        (config.EVIDENCIA_DIR / archivo).write_bytes(base64.b64decode(e.archivo_base64.split(",")[-1]))
    with _escritura:
        ide = registro.agregar_evidencia(e.id_paciente, _fecha(e.fecha_examen), e.tipo_medicion, e.valor, e.lugar,
                                         archivo, _fecha(e.fecha_recepcion))
    return {"id_evidencia": ide, "respuesta": "Recibimos su examen. Un profesional lo revisará antes de usarlo; "
                                              "esto no cambia por sí solo su fecha de atención."}


@app.get("/api/canal-pendientes")
def pendientes():
    ev, msj = registro.evidencias(), registro.mensajes()
    nombres = {s.id_paciente: s.nombre for s in repo.solicitudes.values()}
    ev = ev[ev["estado"] == "pendiente"] if len(ev) else ev
    msj = msj[(msj["estado"] == "pendiente")] if len(msj) else msj
    return {"evidencias": [{**x, "nombre": nombres.get(x["id_paciente"]),
                            "nombre_examen": R.NOMBRE_MEDICION.get(x["tipo_medicion"]),
                            "unidad": R.UNIDADES.get(x["tipo_medicion"])} for x in a_json(ev)],
            "alarmas": [{**x, "nombre": nombres.get(x["id_paciente"])} for x in a_json(msj)]}


def _antes_despues(id_paciente: str, corte: date, aplicar):
    sol = _paciente(id_paciente)
    decs = _decisiones(sol.id_solicitud)
    antes = evaluar(sol, repo.historias[id_paciente], corte, decs)
    with _escritura:
        aplicar()
        nocturno.recalcular_solicitud(repo, registro, sol.id_solicitud)
    despues = evaluar(sol, repo.historias[id_paciente], corte, decs)
    resumen = lambda r: {"nivel_propuesto": r.nivel_propuesto, "puntaje_nivel": r.puntaje_nivel,  # noqa: E731
                         "alerta": r.alerta, "motivo_principal": r.motivo_principal}
    return {"id_solicitud": sol.id_solicitud, "antes": resumen(antes), "despues": resumen(despues)}


@app.post("/api/canal/evidencias/{id_evidencia}/revision")
def revisar_evidencia(id_evidencia: str, rev: RevisionIn):
    ev = registro.evidencias()
    fila = ev[ev["id_evidencia"] == id_evidencia]
    if fila.empty:
        raise HTTPException(404, f"No existe la evidencia {id_evidencia}")
    return _antes_despues(fila.iloc[0]["id_paciente"], _fecha(rev.corte),
                          lambda: registro.revisar_evidencia(id_evidencia, rev.estado, rev.revisado_por, rev.nota))


@app.post("/api/canal/mensajes/{id_mensaje}/revision")
def revisar_mensaje(id_mensaje: str, rev: RevisionIn):
    msj = registro.mensajes()
    fila = msj[msj["id_mensaje"] == id_mensaje]
    if fila.empty:
        raise HTTPException(404, f"No existe el mensaje {id_mensaje}")
    return _antes_despues(fila.iloc[0]["id_paciente"], _fecha(rev.corte),
                          lambda: registro.revisar_mensaje(id_mensaje, rev.estado, rev.revisado_por))


# -- KPIs ---------------------------------------------------------------------------------------
@app.get("/api/kpis")
def kpis(corte: str | None = None):
    c = _fecha(corte)

    def calcular():
        df, _ = _bandeja(c)
        s = _serie()
        s_corte = s[s["fecha"] <= c.isoformat()]
        reev = tiempo_reevaluacion(repo, s_corte, c)
        detalle = reev.pop("detalle")
        conc = concordancia(registro.decisiones())
        por_noche = s_corte.assign(
            alta_propuesta=s_corte["nivel_propuesto"].eq("alta"), alta_inicial=s_corte["prioridad_inicial"].eq("alta"),
            suben=s_corte["cambio"].eq("sube")).groupby("fecha").agg(
            en_lista=("id_solicitud", "size"), alertas=("alerta", "sum"), alta_propuesta=("alta_propuesta", "sum"),
            alta_inicial=("alta_inicial", "sum"), suben=("suben", "sum")).reset_index()
        matriz = pd.crosstab(df["prioridad_inicial"], df["nivel_propuesto"]).reindex(
            index=list(R.NIVELES), columns=list(R.NIVELES), fill_value=0) if len(df) else pd.DataFrame()
        return a_json({
            "corte": c.isoformat(),
            "reevaluacion": {**a_json(reev),
                             "por_severidad": a_json(detalle.groupby("severidad").size()) if len(detalle) else {}},
            "cobertura": {"activas": len(df), "con_propuesta": len(df),
                          "pct": 1.0 if len(df) else None},
            "concordancia": {k: a_json(v) for k, v in conc.items() if k != "por_decision"}
                            | ({"por_decision": a_json(conc["por_decision"].to_dict())} if "por_decision" in conc else {}),
            "foto_vs_pelicula": {"niveles": list(R.NIVELES),
                                 "matriz": [[int(matriz.loc[i, j]) for j in R.NIVELES] for i in R.NIVELES] if len(matriz) else []},
            "cambios": a_json(df["cambio"].value_counts().to_dict()) if len(df) else {},
            "invisibles": a_json(invisibles(repo, df, c)) if len(df) else [],
            "equidad": {k: a_json(v.reset_index().rename(columns={k: "grupo"})) for k, v in equidad(df).items()} if len(df) else {},
            "por_noche": a_json(por_noche),
        })
    return _cacheado(("kpis", c), calcular)


# -- consolidación nocturna -----------------------------------------------------------------------
@app.get("/api/nocturno")
def estado_nocturno():
    t = repo.tablas
    return {
        "version_reglas": R.VERSION_REGLAS,
        "corridas": a_json(registro.corridas().head(20)),
        "reglas": [{"grupo": g, "regla": r, "valor": v} for g, r, v in R.tabla_reglas()],
        "fuentes": [{"tabla": n, "filas": len(df)} for n, df in t.items()],
        "registro": {
            "serie_nocturna": len(_serie()), "propuestas": len(registro.propuestas()),
            "decisiones": len(registro.decisiones()), "evidencias": len(registro.evidencias()),
            "mensajes": len(registro.mensajes())},
    }


@app.post("/api/nocturno/ejecutar")
def ejecutar_nocturno():
    with _escritura:
        return nocturno.ejecutar(repo, registro)


def _precalentar():
    """Calcula en segundo plano la bandeja y los KPIs del día de referencia para que la demo abra rápido."""
    try:
        kpis(config.FECHA_REFERENCIA.isoformat())
        panel_box(config.FECHA_REFERENCIA.isoformat())
    except Exception:  # noqa: BLE001 — el precalentado es opcional
        pass


threading.Thread(target=_precalentar, daemon=True).start()


# -- app React compilada (npm run build en web/) ----------------------------------------------------
DIST = config.RAIZ / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{ruta:path}", include_in_schema=False)
    def spa(ruta: str):
        archivo = DIST / ruta
        if ruta and archivo.is_file():
            return FileResponse(archivo)
        return FileResponse(DIST / "index.html")
