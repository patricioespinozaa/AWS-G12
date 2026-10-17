"""Agenda de cupos y panel de uso de box."""
import pandas as pd
from fastapi import APIRouter

from priorizacion.disponibilidad import proponer_agenda

from .. import estado as E
from ..serializacion import a_json

router = APIRouter()


@router.get("/api/agenda")
def agenda(fecha: str, especialidad: str):
    f = E.fecha(fecha)
    df, _ = E.bandeja(f)
    if df.empty:
        return {"fecha": f.isoformat(), "cupos_libres": 0, "bloques": [], "asignados": [], "reemplazos": [], "acciones": []}
    res = proponer_agenda(df, E.repo.agenda, f, especialidad)
    return {"fecha": f.isoformat(), "especialidad": especialidad, **{k: a_json(v) for k, v in res.items()}}


@router.get("/api/box")
def panel_box(corte: str | None = None):
    c = E.fecha(corte)

    def calcular():
        ag = E.repo.agenda[E.repo.agenda["fecha"] <= pd.Timestamp(c)].copy()
        ci = E.repo.tablas["citas"][E.repo.tablas["citas"]["fecha_cita"] <= pd.Timestamp(c)].copy()
        if ag.empty:
            return {"hay_agenda": False}
        por_esp = ag.groupby("especialidad").agg(
            box=("id_box", "nunique"), capacidad=("capacidad_cupos", "sum"), usados=("cupos_usados", "sum"),
            sobretiempo_medio=("minutos_sobretiempo", "mean"),
            sobretiempo_p90=("minutos_sobretiempo", lambda s: s.quantile(0.9))).reset_index()
        por_esp["ocupacion"] = por_esp["usados"] / por_esp["capacidad"]
        por_esp["pct_capacidad"] = por_esp["capacidad"] / por_esp["capacidad"].sum()
        df, _ = E.bandeja(c)
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
    return E.cacheado(("box", c), calcular)
