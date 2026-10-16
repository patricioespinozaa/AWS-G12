"""Metadatos de la app y listado de solicitudes."""
from fastapi import APIRouter

from priorizacion import config
from priorizacion import reglas as R

from .. import estado as E

router = APIRouter()


@router.get("/api/meta")
def meta():
    return {
        "fecha_referencia": config.FECHA_REFERENCIA.isoformat(),
        "datos_al": config.FECHA_REFERENCIA.isoformat(),          # fecha de corte de los datos (F0006)
        "modo_fecha": E.registro.modo_fecha(),
        "fecha_min": E.repo.fecha_min.isoformat(),
        "especialidades": sorted({s.especialidad for s in E.repo.solicitudes.values()}),
        "version_reglas": R.VERSION_REGLAS,
        "umbrales": {"media": R.UMBRAL_MEDIA, "alta": R.UMBRAL_ALTA},
        "llm": {"activo": config.LLM_PROVEEDOR == "bedrock", "modelo": config.BEDROCK_MODEL_ID},
        "agenda": {"min": E.repo.agenda["fecha"].min().date().isoformat(),
                   "max": E.repo.agenda["fecha"].max().date().isoformat()},
        "tipos_medicion": [{"tipo": t, "nombre": R.NOMBRE_MEDICION[t], "unidad": R.UNIDADES[t],
                            "rango": R.RANGOS_NORMALES[t]} for t in R.RANGOS_NORMALES],
        "casos_referencia": [{"id_paciente": p, "id_solicitud": E.repo.solicitud_de_paciente(p).id_solicitud, "patron": n}
                             for p, n in E.CASOS_REFERENCIA.items() if any(
                                 s.id_paciente == p for s in E.repo.solicitudes.values())],
        "usuaria": config.USUARIA,
        "base_de_datos": "rds" if config.usa_rds() else "local",
    }


@router.get("/api/solicitudes")
def solicitudes():
    return [{"id_solicitud": s.id_solicitud, "id_paciente": s.id_paciente, "nombre": s.nombre,
             "especialidad": s.especialidad, "cie10": s.cie10, "diagnostico": s.diagnostico,
             "caso_referencia": E.CASOS_REFERENCIA.get(s.id_paciente)}
            for s in sorted(E.repo.solicitudes.values(), key=lambda s: s.id_paciente)]
