"""Consolidación (F0006): bitácora de corridas, estado del recálculo en curso, reglas, fuentes y recálculo completo."""
from fastapi import APIRouter, HTTPException

from priorizacion import config
from priorizacion import reglas as R

from .. import estado as E
from ..serializacion import a_json

router = APIRouter()


@router.get("/api/nocturno")
def estado_nocturno():
    t = E.repo.tablas
    return {
        "version_reglas": R.VERSION_REGLAS,
        "fecha_corte": config.FECHA_REFERENCIA.isoformat(),
        "consolidacion": E.estado_consolidacion(),
        "corridas": a_json(E.registro.corridas().head(20)),
        "reglas": [{"grupo": g, "regla": r, "valor": v} for g, r, v in R.tabla_reglas()],
        "fuentes": [{"tabla": n, "filas": len(df)} for n, df in t.items()],
        "registro": {
            "serie_nocturna": len(E.serie()), "propuestas": len(E.registro.propuestas()),
            "decisiones": len(E.registro.decisiones()), "evidencias": len(E.registro.evidencias()),
            "mensajes": len(E.registro.mensajes())},
    }


@router.get("/api/nocturno/estado")
def estado_consolidacion():
    """Liviano, para consultar mientras corre un recálculo."""
    return E.estado_consolidacion()


@router.post("/api/nocturno/ejecutar", status_code=202)
def ejecutar_nocturno():
    """Rehace la historia completa en segundo plano (por ejemplo, después de cambiar las reglas)."""
    E.exigir_sin_recalculo()
    if not E.consolidar_en_segundo_plano("completo", desde_cero=True):
        raise HTTPException(409, "Ya hay un recálculo en curso.")
    return E.estado_consolidacion()
