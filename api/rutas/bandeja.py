"""Bandeja de revisión: las solicitudes activas con su propuesta, por especialidad."""
from fastapi import APIRouter

from .. import estado as E
from ..serializacion import a_json

router = APIRouter()


@router.get("/api/bandeja")
def bandeja(corte: str | None = None):
    c = E.fecha(corte)
    df, _ = E.bandeja(c)
    if len(df):
        df = df.assign(caso_referencia=df["id_paciente"].map(E.CASOS_REFERENCIA))
    return {"corte": c.isoformat(), "filas": a_json(df)}
