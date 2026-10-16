"""Configuración de las reglas, versionada (F0014): catálogo, simulación, versiones y restauración.

La Administradora cambia los parámetros editables; cada cambio guardado es una versión nueva (solo inserción) con su
motivo, y recalcula la historia completa en segundo plano. La simulación calcula la bandeja de la fecha de corte con
los valores propuestos sin guardar nada.

Estas rutas no toman la dependencia `E.calculando`: simular y aplicar toman el candado de escritura de los parámetros
(`priorizacion/parametros.py`) y esperan a que terminen los cálculos en curso.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from priorizacion import parametros as P
from priorizacion import reglas as R
from priorizacion.bandeja import construir_bandeja

from .. import estado as E
from ..seguridad import Persona, administradora

router = APIRouter(prefix="/api/reglas", tags=["reglas"])
ORDEN = {"alta": 3, "media": 2, "baja": 1}


class ValoresIn(BaseModel):
    valores: dict[str, float | int | str] = Field(default_factory=dict)


class VersionIn(ValoresIn):
    motivo: str = ""


class RestaurarIn(BaseModel):
    motivo: str = ""


def _normalizar(valores: dict) -> dict:
    try:
        return P.normalizar(valores)
    except P.ErrorValidacion as e:
        raise HTTPException(422, {"mensaje": "Hay parámetros inválidos", "errores": {
            k: f"{P.POR_CLAVE[k].nombre if k in P.POR_CLAVE else k}: {m}" for k, m in e.errores.items()}})


def _cambios_con_nombre(cambios: dict) -> list[dict]:
    return [{"clave": k, "nombre": P.POR_CLAVE[k].nombre if k in P.POR_CLAVE else k,
             "grupo": P.POR_CLAVE[k].grupo if k in P.POR_CLAVE else "", **v} for k, v in cambios.items()]


@router.get("")
def reglas():
    with P.lectura():
        return {"version": R.VERSION_REGLAS, "numero": P.numero_vigente, "parametros": P.catalogo_json(),
                "solo_lectura": P.solo_lectura_json(), "fecha_corte": E.estado_consolidacion()["fecha_corte"],
                "recalculo": E.estado_consolidacion()}


@router.get("/versiones")
def versiones():
    df = E.registro.versiones_reglas()
    filas = [{"numero": 0, "version": P.version_texto(0), "motivo": "Valores de fábrica (priorizacion/reglas.py)",
              "creada_por": None, "creada_en": None, "restaura": None, "cambios": [], "vigente": P.numero_vigente == 0}]
    for f in df.to_dict("records"):
        filas.insert(0, {**{k: f[k] for k in ("numero", "version", "motivo", "creada_por", "creada_en", "restaura")},
                         "cambios": _cambios_con_nombre(f["cambios"]), "vigente": int(f["numero"]) == P.numero_vigente})
    return {"vigente": P.numero_vigente, "versiones": sorted(filas, key=lambda x: -x["numero"])}


@router.post("/simulacion")
def simulacion(d: ValoresIn):
    """Cuántos pacientes cambiarían de nivel con estos valores, y los de mayor cambio en el puntaje. No guarda nada."""
    E.exigir_sin_recalculo()
    propuestos = _normalizar(d.valores)
    cambios = P.diferencias(P.vigentes(), propuestos)
    if not cambios:
        raise HTTPException(422, "Los valores propuestos son iguales a los vigentes")
    corte = E.fecha(None)
    with P.lectura():
        actual, _ = E.bandeja(corte)
    with P.temporal(propuestos):
        simulada, _ = construir_bandeja(E.repo, E.registro, corte)
    a = actual.set_index("id_solicitud")
    s = simulada.set_index("id_solicitud").reindex(a.index)
    sube = (s["nivel_propuesto"].map(ORDEN) > a["nivel_propuesto"].map(ORDEN))
    baja = (s["nivel_propuesto"].map(ORDEN) < a["nivel_propuesto"].map(ORDEN))
    delta = (s["puntaje"] - a["puntaje"]).round(2)
    mayores = delta.abs().sort_values(ascending=False)
    mayores = mayores[mayores > 0].head(20).index
    detalle = [{"id_solicitud": i, "id_paciente": a.at[i, "id_paciente"], "nombre": a.at[i, "nombre"],
                "especialidad": a.at[i, "especialidad"],
                "nivel_actual": a.at[i, "nivel_propuesto"], "nivel_simulado": s.at[i, "nivel_propuesto"],
                "puntaje_actual": round(float(a.at[i, "puntaje"]), 2),
                "puntaje_simulado": round(float(s.at[i, "puntaje"]), 2), "diferencia": float(delta[i])}
               for i in mayores]
    niveles = {n: {"actual": int((a["nivel_propuesto"] == n).sum()), "simulado": int((s["nivel_propuesto"] == n).sum())}
               for n in R.NIVELES}
    return {"fecha_corte": corte.isoformat(), "total": len(a), "suben": int(sube.sum()), "bajan": int(baja.sum()),
            "cambian_puntaje": int((delta != 0).sum()), "niveles": niveles, "mayores_cambios": detalle,
            "cambios": _cambios_con_nombre(cambios)}


def _guardar(propuestos: dict, motivo: str, quien: Persona, restaura: int | None = None) -> dict:
    if len(motivo.strip()) < 5:
        raise HTTPException(422, "Escribe el motivo del cambio (al menos 5 caracteres)")
    E.exigir_sin_recalculo()
    with E.escritura:
        cambios = P.diferencias(P.vigentes(), propuestos)
        if not cambios:
            raise HTTPException(422, "Los valores son iguales a los de la versión vigente")
        numero = E.registro.guardar_version_reglas(propuestos, cambios, motivo, quien.id_usuario, restaura)
        P.aplicar(propuestos, numero)
    lanzado = E.consolidar_en_segundo_plano("reglas", desde_cero=True)
    return {"numero": numero, "version": P.version_texto(numero), "cambios": _cambios_con_nombre(cambios),
            "recalculo_lanzado": lanzado}


@router.post("/versiones")
def guardar_version(d: VersionIn, quien: Persona = Depends(administradora)):
    """Guarda los valores como una versión nueva y recalcula la historia completa con ella."""
    return _guardar(_normalizar(d.valores), d.motivo, quien)


@router.post("/versiones/{numero}/restaurar")
def restaurar(numero: int, d: RestaurarIn, quien: Persona = Depends(administradora)):
    """Vuelve a los valores de una versión anterior (0 = fábrica) creando una versión nueva."""
    if numero == 0:
        valores = P.fabrica()
    else:
        df = E.registro.versiones_reglas()
        fila = df[df["numero"] == numero]
        if fila.empty:
            raise HTTPException(404, f"No existe la versión {numero}")
        valores = fila.iloc[0]["valores"]
    return _guardar(_normalizar(valores), d.motivo, quien, restaura=numero or None)
