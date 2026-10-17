"""Indicadores: reevaluación, concordancia, foto frente a película, equidad e invisibles."""
import pandas as pd
from fastapi import APIRouter

from priorizacion import reglas as R
from priorizacion.kpis import concordancia, equidad, invisibles, tiempo_reevaluacion

from .. import estado as E
from ..serializacion import a_json

router = APIRouter()


@router.get("/api/kpis")
def kpis(corte: str | None = None):
    c = E.fecha(corte)

    def calcular():
        df, _ = E.bandeja(c)
        s = E.serie()
        s_corte = s[s["fecha"] <= c.isoformat()]
        reev = tiempo_reevaluacion(E.repo, s_corte, c)
        detalle = reev.pop("detalle")
        conc = concordancia(E.registro.decisiones())
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
            "invisibles": a_json(invisibles(E.repo, df, c)) if len(df) else [],
            "equidad": {k: a_json(v.reset_index().rename(columns={k: "grupo"})) for k, v in equidad(df).items()} if len(df) else {},
            "por_noche": a_json(por_noche),
        })
    return E.cacheado(("kpis", c), calcular)
