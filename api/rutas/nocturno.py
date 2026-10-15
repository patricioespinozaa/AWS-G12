"""Consolidación nocturna: estado, reglas, fuentes y ejecución manual."""
from fastapi import APIRouter

from priorizacion import nocturno
from priorizacion import reglas as R

from .. import estado as E
from ..serializacion import a_json

router = APIRouter()


@router.get("/api/nocturno")
def estado_nocturno():
    t = E.repo.tablas
    return {
        "version_reglas": R.VERSION_REGLAS,
        "corridas": a_json(E.registro.corridas().head(20)),
        "reglas": [{"grupo": g, "regla": r, "valor": v} for g, r, v in R.tabla_reglas()],
        "fuentes": [{"tabla": n, "filas": len(df)} for n, df in t.items()],
        "registro": {
            "serie_nocturna": len(E.serie()), "propuestas": len(E.registro.propuestas()),
            "decisiones": len(E.registro.decisiones()), "evidencias": len(E.registro.evidencias()),
            "mensajes": len(E.registro.mensajes())},
    }


@router.post("/api/nocturno/ejecutar")
def ejecutar_nocturno():
    with E.escritura, E.registro.candado("hlf_serie_completa"):
        return nocturno.ejecutar(E.repo, E.registro)
