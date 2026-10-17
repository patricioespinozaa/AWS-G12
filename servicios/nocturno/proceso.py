"""Una noche de consolidación (F0006).

1. Migra la base si hace falta (la tarea puede correr con una imagen más nueva que la base).
2. Revisa el buzón: cada entrega no procesada se valida (vista previa) y, si no tiene errores y
   HLF_AUTOCONFIRMAR=1, se suma a raw como una versión nueva, en orden. Una entrega con errores queda `fallida`
   en el historial de Cargas (con archivo y línea) y detiene las siguientes: los periodos dependen del anterior.
   Con HLF_AUTOCONFIRMAR=0 queda `lista` para que la Administradora la confirme en la vista Cargas.
3. Corre el pipeline de consolidación con origen `nocturno`: recalcula los pacientes afectados, suma las noches
   nuevas al histórico, estima la espera y (si está configurado) publica en Athena. Corre aunque no haya
   entregas nuevas: queda en la bitácora que la noche corrió y no había nada que sumar.

Es lo mismo que hace la vista Cargas, sin intervención: si el HLF puede dejar sus exportaciones en el buzón
(o un proceso las descarga de su sistema), la carga manual deja de ser necesaria.
"""
from __future__ import annotations

import json
import logging

from db import carga, esquema
from db.conexion import conectar
from priorizacion import config
from priorizacion.consolidacion import consolidar
from priorizacion.datos import Repositorio
from priorizacion.registro_postgres import RegistroPostgres

from .buzon import Descarga, ErrorBuzon

log = logging.getLogger("hlf.nocturno")
CARGADO_POR = "consolidacion_nocturna"


def _ya_procesada(conn, d: Descarga) -> dict | None:
    """La última carga de esta entrega con los mismos archivos (la base es el registro de lo procesado)."""
    fila = conn.execute("SELECT id_carga, estado, version FROM raw.carga_lote WHERE origen = %s "
                        "AND archivos = %s::jsonb ORDER BY id_carga DESC LIMIT 1",
                        (d.entrega.uri, json.dumps(d.huellas))).fetchone()
    return dict(zip(("id_carga", "estado", "version"), fila)) if fila else None


def _procesar(conn, d: Descarga, autoconfirmar: bool) -> dict:
    nombre = d.entrega.nombre
    if not d.huellas:
        return {"entrega": nombre, "estado": "sin_csv"}
    if previa := _ya_procesada(conn, d):
        return {"entrega": nombre, "id_carga": previa["id_carga"], "estado_carga": previa["estado"],
                "estado": "ya_procesada"}
    try:
        previa = carga.vista_previa(conn, d.carpeta, d.periodo, cargado_por=CARGADO_POR, uri_archivos=d.entrega.uri)
    except carga.ErrorCarga as e:                 # p. ej. los mismos archivos ya se subieron por la vista Cargas
        return {"entrega": nombre, "estado": "omitida", "motivo": str(e)}
    base = {"entrega": nombre, "id_carga": previa["id_carga"]}
    if previa["estado"] == "fallida":
        return {**base, "estado": "fallida", "errores": previa["errores"][:5]}
    if not autoconfirmar:
        return {**base, "estado": "lista"}
    res = carga.aplicar_incremental(conn, previa["id_carga"], d.carpeta)
    return {**base, "estado": "aplicada", "version": res["version"],
            "pacientes_afectados": res["pacientes_afectados"]}


def correr(buzon=None, url: str | None = None, autoconfirmar: bool | None = None, publicar=None) -> dict:
    """Corre una noche completa. Devuelve el resumen (también queda en la bitácora de corridas)."""
    autoconfirmar = config.AUTOCONFIRMAR if autoconfirmar is None else autoconfirmar
    entregas, afectados, ultima_carga = [], set(), None
    with conectar(url) as conn:
        esquema.migrar(conn)
        for entrega in (buzon.entregas() if buzon else []):
            try:
                d = buzon.descargar(entrega)
            except ErrorBuzon as e:
                entregas.append({"entrega": entrega.nombre, "estado": "fallida", "errores": [str(e)]})
                break
            try:
                r = _procesar(conn, d, autoconfirmar)
            finally:
                d.limpiar()
            log.info("Entrega %s: %s", entrega.nombre, r["estado"])
            if r["estado"] == "ya_procesada":
                continue                          # no se repite en la bitácora noche tras noche
            entregas.append({k: v for k, v in r.items() if k != "pacientes_afectados"})
            if r["estado"] == "aplicada":
                afectados |= set(r["pacientes_afectados"])
                ultima_carga = r["id_carga"]
            elif r["estado"] in ("fallida", "lista"):
                break                             # las siguientes dependen de esta
        hay_datos = carga.version_datos(conn) > 0
    if not hay_datos:                             # base vacía y nada en el buzón: no hay qué consolidar
        return {"sin_datos": True, "exportaciones": entregas,
                "con_errores": any(e["estado"] == "fallida" for e in entregas)}
    registro = RegistroPostgres(url)
    extra = {"buzon": str(buzon) if buzon else None, "exportaciones": entregas,
             "sin_exportaciones_nuevas": not entregas}
    resultado = consolidar(Repositorio.desde_postgres(url), registro, origen="nocturno", afectados=afectados,
                           id_carga=ultima_carga, publicar=publicar, extra=extra)
    resultado["con_errores"] = any(e["estado"] == "fallida" for e in entregas)
    resultado["kb"] = _sincronizar_kb(url, hubo_datos_nuevos=ultima_carga is not None, fecha_corte=resultado["fecha_corte"])
    return resultado


def _sincronizar_kb(url: str | None, hubo_datos_nuevos: bool, fecha_corte: str) -> dict | None:
    """F0009: la Knowledge Base del equipo clínico se regenera cuando entran datos nuevos (o si nunca se sincronizó o
    quedó en otra fecha de corte). Un fallo aquí no invalida la noche: queda en el resumen y en consulta.ingesta_kb."""
    if not config.KB_ID:
        return None
    try:
        from servicios.consulta_ia import registro as RC
        from servicios.preparacion_kb.proceso import preparar
        with conectar(url) as conn:
            vigente = RC.kb_vigente(conn, config.KB_ID)
        if not hubo_datos_nuevos and vigente and vigente["fecha_corte"].isoformat() == fecha_corte:
            return {"estado": "al_dia", "id_ingesta": vigente["id_ingesta"]}
        return preparar(url)
    except Exception as e:  # noqa: BLE001
        log.exception("No se pudo sincronizar la Knowledge Base")
        return {"estado": "fallida", "error": f"{type(e).__name__}: {str(e)[:300]}"}

