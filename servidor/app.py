"""API HTTP local del copiloto.

ADVERTENCIA: solo para uso local con datos sinteticos; sin autenticacion.
Se enlaza a 127.0.0.1 y el CORS se limita a los orígenes de Vite (dev/preview).

Solo compone funciones existentes del backend. No existen endpoints para aplicar
prioridades, citar, prescribir ni diagnosticar: la decisión del profesional se
registra en auditoría y no modifica ningún dato.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date
from functools import lru_cache
from typing import Any

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import auditoria
import copiloto
from servidor import RAIZ
from servidor.configuracion import ADVERTENCIA, ConfigServidor
from servidor.contratos import (EstadoServidor, HistorialAviso, ItemLista, RespuestaAnalisis,
                                RespuestaCalidad, RespuestaDecision, RespuestaLista,
                                RespuestaPaciente, SolicitudAnalisis, SolicitudDecision)
from servidor.inferencia import ClienteSimulado, instalar_cliente, origen_inferencia
from servidor.servicios import (ContextoDatos, a_nativo, estado_aviso, historial,
                                indice_evidencia, leer_auditoria, orden_lista)

log = logging.getLogger("servidor")

ORIGENES_VITE = ["http://127.0.0.1:5173", "http://localhost:5173",
                 "http://127.0.0.1:4173", "http://localhost:4173"]
PATRON_PID = r"^PAC-[A-Z]+-\d{5}$"
PATRON_ALERTA = re.compile(r"^ALR-(PAC-[A-Z]+-\d{5})-(\d{8})$")
TIPOS_AVISO = ("priorizacion", "gestion")
NOTA_DECISION = ("Decisión registrada en auditoría. La prioridad de la solicitud no se "
                 "modifica automáticamente.")
NOTA_CALIDAD = ("Hallazgos de calidad sobre registros visibles a la fecha de corte. "
                "DQ-06 no se evalúa antes del 2026-10-13 porque depende del estado a esa fecha.")


def _error(status: int, codigo: str, mensaje: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"codigo": codigo, "mensaje": mensaje})


def crear_app(contexto: ContextoDatos | None = None, config: ConfigServidor | None = None,
              cliente: Any = None) -> FastAPI:
    """``cliente`` permite inyectar un cliente falso (pruebas) en lugar del real."""
    config = config or ConfigServidor.desde_entorno()
    estado: dict[str, Any] = {"contexto": contexto}
    lock_backend = threading.Lock()   # copiloto._cliente y auditoria.LOG son globales

    if cliente is not None:
        def fabrica():
            return cliente
    elif config.inferencia_real:
        fabrica = lru_cache(maxsize=1)(lambda: __import__("config").get_client())
    else:
        simulado = ClienteSimulado()

        def fabrica():
            return simulado

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if estado["contexto"] is None:
            try:
                estado["contexto"] = ContextoDatos.cargar(RAIZ / "perfiles.json",
                                                          RAIZ / "agenda_box.csv")
            except Exception:
                log.critical("No se pudieron cargar perfiles.json/agenda_box.csv")
                raise
        yield

    app = FastAPI(title="Copiloto lista de espera HLF (local)", version="0.1.0",
                  description=ADVERTENCIA, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=ORIGENES_VITE,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
                       allow_credentials=False)

    @app.exception_handler(Exception)
    async def _no_previsto(_req: Request, exc: Exception):
        log.exception("Error no previsto: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": {
            "codigo": "error_interno", "mensaje": "Error interno del servidor."}})

    def ctx() -> ContextoDatos:
        return estado["contexto"]

    def validar_corte(c: ContextoDatos, corte: date) -> date:
        if not c.fecha_corte_min <= corte <= c.fecha_referencia:
            raise HTTPException(status_code=422, detail={
                "codigo": "fecha_corte_fuera_de_rango",
                "mensaje": f"La fecha de corte debe estar entre {c.fecha_corte_min} y "
                           f"{c.fecha_referencia}."})
        return corte

    def corte_query(fecha_corte: date = Query(..., description="Fecha de corte obligatoria"),
                    c: ContextoDatos = Depends(ctx)) -> date:
        return validar_corte(c, fecha_corte)

    def auditoria_actual() -> tuple[dict, int]:
        return leer_auditoria(config.auditoria_path)

    # ------------------------------------------------------------------
    @app.get("/api/estado", response_model=EstadoServidor)
    def obtener_estado(c: ContextoDatos = Depends(ctx)):
        return {
            "modo_inferencia": "real" if config.inferencia_real else "simulada",
            "requiere_confirmacion_envio": config.inferencia_real,
            "fecha_referencia": c.fecha_referencia, "fecha_corte_min": c.fecha_corte_min,
            "fecha_corte_max": c.fecha_referencia, "advertencia": ADVERTENCIA,
            "perfiles_validos": c.n_validos, "perfiles_en_cuarentena": len(c.cuarentena),
            "fuente_datos": "perfiles.json + agenda_box.csv",
        }

    @app.get("/api/lista", response_model=RespuestaLista)
    def obtener_lista(corte: date = Depends(corte_query), c: ContextoDatos = Depends(ctx)):
        evaluaciones = c.evaluaciones(corte)
        grupos, _ = auditoria_actual()
        items = sorted((r | {"estado_aviso": estado_aviso(grupos.get(r["alerta_id"]))}
                        for r in evaluaciones if r["tipo"] != "exclusion"), key=orden_lista)
        excluidos = sorted((r for r in evaluaciones if r["tipo"] == "exclusion"),
                           key=lambda r: r["id_paciente"])
        return {"fecha_corte": corte, "items": items, "excluidos": excluidos,
                "n_sin_solicitud_a_la_fecha": c.n_pacientes - len(evaluaciones)}

    @app.get("/api/avisos", response_model=list[ItemLista])
    def obtener_avisos(corte: date = Depends(corte_query), c: ContextoDatos = Depends(ctx)):
        grupos, _ = auditoria_actual()
        avisos = [r | {"estado_aviso": estado_aviso(grupos.get(r["alerta_id"]))}
                  for r in c.evaluaciones(corte) if r["tipo"] in TIPOS_AVISO]
        return sorted(avisos, key=orden_lista)

    @app.get("/api/pacientes/{pid}", response_model=RespuestaPaciente)
    def obtener_paciente(pid: str = Path(pattern=PATRON_PID),
                         corte: date = Depends(corte_query), c: ContextoDatos = Depends(ctx)):
        cron = c.cronologia(pid, corte)
        evaluacion = c.evaluacion(pid, corte)
        if cron is None or evaluacion is None:
            raise _error(404, "sin_solicitud_a_la_fecha",
                         "El paciente no tiene solicitud vigente a la fecha de corte.")
        grupos, invalidas = auditoria_actual()
        solicitud = cron["solicitud"] | {
            "estado_reconstruible": cron["solicitud"].get("estado") != "desconocido_a_la_fecha"}
        perfil = {k: cron["perfil"].get(k) for k in ("id_paciente", "edad", "sexo")}
        return {"fecha_corte": corte, "perfil": perfil, "solicitud": solicitud,
                "eventos": cron["eventos"], "evaluacion": evaluacion,
                "calidad": c.calidad_paciente(pid, corte, cron),
                "evidencia": indice_evidencia(cron),
                "historial": historial(evaluacion["alerta_id"], grupos, invalidas)}

    @app.get("/api/avisos/{alerta_id}/historial", response_model=HistorialAviso)
    def obtener_historial(alerta_id: str = Path(pattern=PATRON_ALERTA.pattern)):
        grupos, invalidas = auditoria_actual()
        return historial(alerta_id, grupos, invalidas)

    @app.post("/api/pacientes/{pid}/analisis", response_model=RespuestaAnalisis)
    def solicitar_analisis(cuerpo: SolicitudAnalisis, pid: str = Path(pattern=PATRON_PID),
                           c: ContextoDatos = Depends(ctx)):
        corte = validar_corte(c, cuerpo.fecha_corte)
        alerta = c.evaluacion(pid, corte)
        cron = c.cronologia(pid, corte)
        if alerta is None or cron is None:
            raise _error(404, "sin_solicitud_a_la_fecha",
                         "El paciente no tiene solicitud vigente a la fecha de corte.")
        if alerta["tipo"] not in TIPOS_AVISO:
            raise _error(409, "sin_aviso", "El motor de reglas no generó un aviso para este "
                                           "paciente a la fecha de corte.")
        if config.inferencia_real and not cuerpo.confirmar_envio_api_real:
            log.info("Análisis real sin confirmación: %s", alerta["alerta_id"])
            raise _error(409, "confirmacion_requerida",
                         "La inferencia real envía datos a una API externa: confirme el envío.")
        try:
            with lock_backend:
                auditoria.LOG = config.auditoria_path
                instalar_cliente(fabrica())
                analisis = copiloto.analizar_alerta(c.repo, alerta)
        except anthropic.APIError as e:
            log.error("Error de API en %s: %s", alerta["alerta_id"],
                      getattr(e, "status_code", type(e).__name__))
            raise _error(502, "error_api_inferencia", "La API de inferencia respondió con error.")
        except RuntimeError as e:
            log.error("Análisis no disponible para %s: %s", alerta["alerta_id"], type(e).__name__)
            raise _error(502, "analisis_no_disponible", "No se obtuvo un análisis válido.")
        except (KeyError, ValueError) as e:
            log.error("Alerta incompleta %s: %s", alerta["alerta_id"], type(e).__name__)
            raise _error(500, "alerta_incompleta", "La alerta del motor está incompleta.")
        analisis = a_nativo(analisis)
        return {"alerta_id": alerta["alerta_id"], "origen_inferencia": origen_inferencia(analisis),
                "analisis": analisis, "evidencia": indice_evidencia(cron)}

    @app.post("/api/avisos/{alerta_id}/decision", response_model=RespuestaDecision)
    def registrar_decision(cuerpo: SolicitudDecision,
                           alerta_id: str = Path(pattern=PATRON_ALERTA.pattern),
                           c: ContextoDatos = Depends(ctx)):
        pid, texto = PATRON_ALERTA.match(alerta_id).groups()
        try:
            corte = date(int(texto[:4]), int(texto[4:6]), int(texto[6:]))
        except ValueError:
            raise _error(404, "aviso_no_encontrado", "El aviso no existe.")
        validar_corte(c, corte)
        r = c.evaluacion(pid, corte)
        if r is None or r["tipo"] not in TIPOS_AVISO or r["alerta_id"] != alerta_id:
            raise _error(404, "aviso_no_encontrado",
                         "No existe un aviso de priorización o gestión con ese identificador.")
        try:
            with lock_backend:
                auditoria.LOG = config.auditoria_path
                auditoria.registrar_decision_medica(
                    alerta_id=alerta_id, medico_id=cuerpo.medico_id, decision=cuerpo.decision,
                    prioridad_final=cuerpo.prioridad_final, comentario=cuerpo.comentario)
        except OSError as e:
            log.error("No se pudo escribir la auditoría: %s", type(e).__name__)
            raise _error(503, "auditoria_no_disponible",
                         "No se pudo registrar la decisión en auditoría.")
        return {"registrada": True, "alerta_id": alerta_id, "nota": NOTA_DECISION}

    @app.get("/api/calidad", response_model=RespuestaCalidad)
    def obtener_calidad(corte: date = Depends(corte_query), c: ContextoDatos = Depends(ctx)):
        hallazgos = c.calidad_global(corte)
        conteo = Counter((h["codigo"], h["nivel"]) for h in hallazgos)
        return {"fecha_corte": corte, "hallazgos": hallazgos,
                "resumen": [{"codigo": k[0], "nivel": k[1], "n": n}
                            for k, n in sorted(conteo.items())],
                "cuarentena": [{"posicion": q["posicion"], "id_paciente": q.get("id_paciente"),
                                "n_errores": len(q.get("errores") or [])}
                               for q in c.cuarentena],
                "nota": NOTA_CALIDAD}

    return app
