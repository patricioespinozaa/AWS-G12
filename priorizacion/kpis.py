"""KPIs del desafío (docs/kpis.md) calculados sobre la serie nocturna y la bandeja."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import reglas as R
from .datos import Repositorio


def tiempo_reevaluacion(repo: Repositorio, serie: pd.DataFrame, corte: date) -> dict:
    """Para cada evento relevante (moderado o grave) ocurrido con el paciente en lista: cuántas noches
    pasan hasta la primera corrida que lo incorpora, y si los graves encendieron la alerta esa noche."""
    evaluadas = set(zip(serie["id_solicitud"], serie["fecha"]))
    alerta = set(zip(serie.loc[serie["alerta"] == 1, "id_solicitud"], serie.loc[serie["alerta"] == 1, "fecha"]))
    filas = []
    for sol in repo.solicitudes.values():
        for e in repo.historias[sol.id_paciente].eventos_hasta(corte):
            if e.severidad == "leve" or e.fecha < sol.fecha_ingreso or (sol.fecha_egreso and e.fecha >= sol.fecha_egreso):
                continue
            noches = next((d for d in range(0, 8) if (sol.id_solicitud, (e.fecha + timedelta(days=d)).isoformat())
                           in evaluadas), None)
            filas.append({"id_solicitud": sol.id_solicitud, "id_evento": e.id_evento, "fecha": e.fecha,
                          "severidad": e.severidad, "noches_hasta_reevaluacion": noches,
                          "alerta_misma_noche": (sol.id_solicitud, e.fecha.isoformat()) in alerta})
    df = pd.DataFrame(filas)
    if df.empty:
        return {"eventos": 0, "pct_menos_72h": None, "mediana_horas": None, "pct_alerta_graves": None, "detalle": df}
    dentro = df["noches_hasta_reevaluacion"].notna() & (df["noches_hasta_reevaluacion"] < 3)
    graves = df[df["severidad"] == "grave"]
    return {
        "eventos": len(df),
        "pct_menos_72h": dentro.mean(),
        # La corrida de la noche del evento lo incorpora: < 24 h si la fuente carga el dato ese mismo día
        "mediana_horas": 24 * (df["noches_hasta_reevaluacion"].median() + 1) if dentro.any() else None,
        "pct_alerta_graves": graves["alerta_misma_noche"].mean() if len(graves) else None,
        "detalle": df,
    }


def concordancia(decisiones: pd.DataFrame) -> dict:
    if len(decisiones) == 0:
        return {"n": 0}
    from sklearn.metrics import cohen_kappa_score
    a = decisiones["prioridad_propuesta"].map(R.ORDEN_NIVEL)
    b = decisiones["prioridad_final"].map(R.ORDEN_NIVEL)
    kappa = cohen_kappa_score(a, b, weights="quadratic", labels=[1, 2, 3]) if len(decisiones) >= 2 else None
    return {"n": len(decisiones), "kappa": kappa,
            "pct_acepta": (decisiones["decision"] == "acepta").mean(),
            "por_decision": decisiones["decision"].value_counts()}


def equidad(bandeja: pd.DataFrame) -> dict[str, pd.DataFrame]:
    b = bandeja.copy()
    b["grupo_edad"] = pd.cut(b["edad"], [0, 40, 60, 75, 120], labels=["<40", "40–59", "60–74", "75+"], right=False)
    b["sube"] = b["cambio"] == "sube"
    b["baja"] = b["cambio"] == "baja"
    out = {}
    for var in ["grupo_edad", "sexo", "comuna", "prevision", "nivel_socioeconomico"]:
        g = b.groupby(var, observed=True).agg(pacientes=("id_solicitud", "size"), sube=("sube", "mean"),
                                              baja=("baja", "mean"))
        out[var] = g
    return out


def invisibles(repo: Repositorio, bandeja: pd.DataFrame, corte: date, ventana_dias: int = 365) -> pd.DataFrame:
    """Pacientes en lista con prioridad inicial baja o media y un evento grave reciente: los que la lista
    congelada no ve. Muestra qué propone el sistema para ellos."""
    filas = []
    for r in bandeja.itertuples(index=False):
        if r.prioridad_inicial == "alta":
            continue
        graves = [e for e in repo.historias[r.id_paciente].eventos_hasta(corte)
                  if e.severidad == "grave" and (corte - e.fecha).days <= ventana_dias]
        if graves:
            filas.append({"id_solicitud": r.id_solicitud, "id_paciente": r.id_paciente, "nombre": r.nombre,
                          "especialidad": r.especialidad, "prioridad_inicial": r.prioridad_inicial,
                          "nivel_propuesto": r.nivel_propuesto, "ultimo_evento_grave": graves[-1].fecha.isoformat(),
                          "posicion_estatica": r.posicion_estatica, "posicion_dinamica": r.posicion_dinamica,
                          "total_cola": r.total_cola})
    return pd.DataFrame(filas)
