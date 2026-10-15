import pandas as pd
from sklearn.metrics import roc_auc_score
from reglas import evaluar_todos, BASE


def backtest(repo, cortes, horizonte_dias: int = 60) -> dict:
    """¿El score dinámico a la fecha T anticipa urgencias, hospitalizaciones o muertes en T+horizonte
    mejor que la prioridad estática?"""
    ev, pac = repo.t["eventos"], repo.t["pacientes"].set_index("id_paciente")
    filas = []
    for corte in pd.to_datetime(cortes):
        fin = corte + pd.Timedelta(days=horizonte_dias)
        futuros = ev[(ev.fecha_evento > corte) & (ev.fecha_evento <= fin)
                     & ev.tipo_evento.isin(["visita_urgencia", "hospitalizacion"])]
        con_evento = set(futuros.id_paciente)
        for r in evaluar_todos(repo, corte):
            if r["tipo"] == "exclusion":
                continue
            p = pac.loc[r["id_paciente"]]
            murio = bool(p.fallecido and pd.notna(p.fecha_defuncion) and corte < p.fecha_defuncion <= fin)
            filas.append({"corte": corte, "id_paciente": r["id_paciente"],
                          "score": r["score"], "estatico": BASE[r["prioridad_inicial"]],
                          "desenlace": int(r["id_paciente"] in con_evento or murio)})
    df = pd.DataFrame(filas)
    if df.desenlace.nunique() < 2:
        return {"n": len(df), "advertencia": "Sin variabilidad de desenlace para calcular el AUC"}
    k = max(1, int(0.1 * len(df)))
    return {
        "n_observaciones": len(df), "tasa_desenlace": round(df.desenlace.mean(), 3),
        "auc_dinamico": round(roc_auc_score(df.desenlace, df.score), 3),
        "auc_estatico": round(roc_auc_score(df.desenlace, df.estatico), 3),
        "captura_top10_dinamico": round(df.nlargest(k, "score").desenlace.sum() / df.desenlace.sum(), 3),
        "captura_top10_estatico": round(
            df.sample(frac=1, random_state=0).nlargest(k, "estatico").desenlace.sum() / df.desenlace.sum(), 3),
    }