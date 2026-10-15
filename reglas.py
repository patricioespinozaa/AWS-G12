import numpy as np
import pandas as pd
from datos import FECHA_REFERENCIA

#  Todos los pesos son AJUSTABLES y deben validarse con clínicos
BASE = {"baja": 20, "media": 40, "alta": 60}
ORDEN = ["baja", "media", "alta", "critica"]
SLA_DIAS = {"alta": 30, "media": 90, "baja": 180}   # referencial; ajustar a normativa local
PESO_TIPO = {"hospitalizacion": 35, "visita_urgencia": 25, "examen_alterado": 10,
             "cambio_farmaco": 8, "control_aps": 0}
MULT_SEV = {"leve": 0.5, "moderada": 1.0, "grave": 1.5}
VIDA_MEDIA_DIAS = 90   # un evento pesa la mitad cada 90 días

# +1: un valor más alto es peor; -1: un valor más bajo es peor
SENTIDO = {"PHQ9": 1, "presion_sistolica": 1, "presion_diastolica": 1, "HbA1c": 1,
           "glicemia": 1, "escala_dolor_eva": 1, "peak_flow": -1, "saturacion_o2": -1}

# Umbrales de bandera roja (referenciales, a validar con cada especialidad)
CRITICO = {
    "presion_sistolica":  lambda v: v >= 180,
    "presion_diastolica": lambda v: v >= 120,
    "saturacion_o2":      lambda v: v < 90,
    "glicemia":           lambda v: v >= 300 or v < 54,
    "HbA1c":              lambda v: v >= 10,
    "PHQ9":               lambda v: v >= 20,
    "peak_flow":          lambda v: v < 200,
    "escala_dolor_eva":   lambda v: v >= 8,
}


def _decay(dias: int) -> float:
    return 0.5 ** (max(dias, 0) / VIDA_MEDIA_DIAS)


def a_prioridad(score: float) -> str:
    return "critica" if score >= 80 else "alta" if score >= 60 else "media" if score >= 40 else "baja"


def evaluar_paciente(repo, id_paciente: str, corte=None) -> dict | None:
    corte = pd.Timestamp(corte) if corte else FECHA_REFERENCIA
    ctx = repo.contexto(id_paciente, corte)
    if ctx is None:
        return None
    pac, sol = ctx["paciente"], ctx["solicitud"]
    base_out = {"alerta_id": f"ALR-{id_paciente}-{corte:%Y%m%d}", "id_paciente": id_paciente,
                "id_solicitud": sol.id_solicitud, "especialidad": sol.especialidad,
                "cie10": sol.diagnostico_cie10, "prioridad_inicial": sol.prioridad_inicial,
                "fecha_corte": corte.date().isoformat()}

    # --- Exclusiones duras ---
    if pac.fallecido and pd.notna(pac.fecha_defuncion) and pac.fecha_defuncion <= corte:
        return base_out | {"tipo": "exclusion", "motivo": "fallecido",
                           "fecha_defuncion": pac.fecha_defuncion.date().isoformat()}
    if corte >= FECHA_REFERENCIA and sol.estado == "atendido":
        return base_out | {"tipo": "exclusion", "motivo": "ya_atendido"}

    motivos, banderas, gestion, inconsistencias = [], [], [], []

    def add(pts, texto, ids):
        motivos.append({"puntos": round(pts, 1), "motivo": texto, "registro_ids": ids})

    add(BASE[sol.prioridad_inicial], f"Prioridad inicial {sol.prioridad_inicial}", [sol.id_solicitud])

    # --- Eventos clínicos ---
    for ev in ctx["eventos"].itertuples():
        dias = (corte - ev.fecha_evento).days
        p = PESO_TIPO.get(ev.tipo_evento, 0) * MULT_SEV.get(ev.severidad, 1.0)
        sub = str(ev.subtipo)
        if "UCI" in sub:
            p += 20
        if "estabiliz" in sub.lower():
            p -= 5
        relacionado = ev.especialidad_detalle == sol.especialidad
        if not relacionado:
            p *= 0.5
        p *= _decay(dias)
        if abs(p) >= 0.5:
            add(p, f"{ev.tipo_evento} ({sub}, {ev.severidad}) hace {dias} días"
                   + ("" if relacionado else " [especialidad distinta a la derivación]"), [ev.id_evento])
        if ev.tipo_evento in ("visita_urgencia", "hospitalizacion") and ev.severidad == "grave" and dias <= 30:
            banderas.append({"bandera": f"{ev.tipo_evento} grave hace {dias} días", "registro_ids": [ev.id_evento]})

    # --- Mediciones: fuera de rango, cambio brusco, tendencia, valores críticos ---
    for tipo, g in ctx["mediciones"].dropna(subset=["valor"]).groupby("tipo_medicion"):
        ult, u = g.tail(3), g.iloc[-1]
        sentido = SENTIDO.get(tipo, 1)
        fr = ult[ult.fuera_de_rango]
        if len(fr):
            add(3 * len(fr), f"{tipo}: {len(fr)} de las últimas {len(ult)} fuera de rango", fr.id_medicion.tolist())
        if CRITICO.get(tipo, lambda v: False)(u.valor):
            banderas.append({"bandera": f"{tipo} = {u.valor} {u.unidad} (umbral crítico)",
                             "registro_ids": [u.id_medicion]})
        if len(g) >= 3:
            previo = g.valor.iloc[:-1].median()
            if previo:
                cambio = sentido * (u.valor - previo) / abs(previo)
                if cambio > 0.25:
                    add(12, f"{tipo}: cambio brusco {u.valor} vs mediana previa {previo:g} ({cambio:+.0%})",
                        [u.id_medicion])
            x = (g.fecha_medicion - g.fecha_medicion.min()).dt.days.to_numpy()
            if x.max() > 0:
                pend30 = np.polyfit(x, g.valor.to_numpy(), 1)[0] * 30
                if sentido * pend30 / (abs(g.valor.mean()) or 1) > 0.03:
                    add(10, f"{tipo}: tendencia a empeorar ({pend30:+.1f} {u.unidad}/30 días)",
                        g.id_medicion.tolist())

    # --- Tiempo de espera ---
    dias_espera = (corte - sol.fecha_ingreso_lista).days
    exceso = dias_espera - SLA_DIAS[sol.prioridad_inicial]
    if exceso > 0:
        add(min(15, exceso / 15), f"{dias_espera} días en espera ({exceso} sobre el plazo referencial)",
            [sol.id_solicitud])

    # --- Gestión (no modifica el score clínico) ---
    citas = ctx["citas"]
    fallidas = citas[citas.estado_cita.isin(["no_asistio", "reprogramo", "cancelo"])]
    if len(fallidas) >= 2:
        gestion.append({"alerta": f"{len(fallidas)} citas fallidas: contactar al paciente y evaluar barreras de acceso",
                        "registro_ids": fallidas.id_cita.tolist()})
    asistio = citas[(citas.estado_cita == "asistio") & (citas.especialidad == sol.especialidad)]
    if len(asistio) and corte >= FECHA_REFERENCIA and sol.estado == "en_espera":
        inconsistencias.append({"descripcion": "Asistió a una cita de la especialidad, pero la solicitud sigue en_espera",
                                "registro_ids": asistio.id_cita.tolist() + [sol.id_solicitud]})

    score = round(sum(m["puntos"] for m in motivos), 1)
    prioridad = "critica" if banderas else a_prioridad(score)
    sube = ORDEN.index(prioridad) > ORDEN.index(sol.prioridad_inicial)

    return base_out | {
        "tipo": "priorizacion" if (sube or banderas) else ("gestion" if gestion else "sin_alerta"),
        "score": score, "prioridad_calculada": prioridad, "dias_en_espera": dias_espera,
        "motivos": sorted(motivos, key=lambda m: -m["puntos"]),
        "banderas_rojas": banderas, "alertas_gestion": gestion, "inconsistencias": inconsistencias,
    }


def evaluar_todos(repo, corte=None) -> list[dict]:
    res = [evaluar_paciente(repo, pid, corte) for pid in repo.t["lista"].id_paciente.unique()]
    return [r for r in res if r]