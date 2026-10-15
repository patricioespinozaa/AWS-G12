"""Composición de funciones existentes del backend (solo lectura de datos).

No agrega reglas, puntajes ni lógica clínica: evalúa con ``reglas``, arma la
cronología con ``datos.Repositorio``, filtra calidad con ``copiloto`` y lee la
auditoría escrita por ``auditoria``.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

import copiloto
import reglas
from calidad import auditar
from datos import FECHA_REFERENCIA, Repositorio
from ingesta_json import cargar_perfiles, tablas_desde_perfiles
from servidor.inferencia import origen_inferencia

log = logging.getLogger("servidor")

ORIGEN_POR_FUENTE = {
    "solicitud": "perfiles.json › lista_espera",
    "evento": "perfiles.json › eventos_clinicos",
    "medicion": "perfiles.json › mediciones",
    "cita": "perfiles.json › citaciones",
}
RANGO = {"critica": 3, "alta": 2, "media": 1, "baja": 0}
MAX_CORTES_EN_CACHE = 8


def a_nativo(obj: Any) -> Any:
    """Convierte numpy/Timestamp/NaN a tipos JSON nativos antes de validar contratos."""
    if isinstance(obj, dict):
        return {str(k): a_nativo(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [a_nativo(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return None if pd.isna(obj) else obj.date().isoformat()
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if obj is pd.NaT or obj is pd.NA:
        return None
    return obj


class _CachePorCorte:
    def __init__(self, calcular: Callable[[date], Any]):
        self._calcular = calcular
        self._datos: OrderedDict[date, Any] = OrderedDict()
        self._lock = threading.Lock()

    def obtener(self, corte: date) -> Any:
        with self._lock:
            if corte in self._datos:
                return self._datos[corte]
            valor = self._calcular(corte)
            self._datos[corte] = valor
            while len(self._datos) > MAX_CORTES_EN_CACHE:
                self._datos.popitem(last=False)      # descarta el más antiguo
            return valor


class ContextoDatos:
    """Única carga de datos: perfiles.json + agenda_box.csv (sin CSV de pacientes)."""

    def __init__(self, repo: Repositorio, cuarentena: list[dict], n_validos: int):
        self.repo = repo
        self.cuarentena = cuarentena
        self.n_validos = n_validos
        self.dq = auditar(repo)
        self.fecha_referencia: date = FECHA_REFERENCIA.date()
        self.fecha_corte_min: date = repo.t["lista"].fecha_ingreso_lista.min().date()
        self._evaluaciones = _CachePorCorte(self._evaluar_todos)
        self._calidad = _CachePorCorte(self._calidad_global)

    @classmethod
    def cargar(cls, ruta_perfiles: Path, ruta_agenda: Path) -> "ContextoDatos":
        perfiles, cuarentena = cargar_perfiles(ruta_perfiles)
        repo = Repositorio(tablas=tablas_desde_perfiles(perfiles, ruta_agenda))
        return cls(repo, cuarentena, len(perfiles))

    # ---------- Motor de reglas ----------
    def _evaluar_todos(self, corte: date) -> list[dict]:
        return a_nativo(reglas.evaluar_todos(self.repo, corte.isoformat()))

    def evaluaciones(self, corte: date) -> list[dict]:
        return self._evaluaciones.obtener(corte)

    def evaluacion(self, pid: str, corte: date) -> dict | None:
        r = reglas.evaluar_paciente(self.repo, pid, corte.isoformat())
        return None if r is None else a_nativo(r)

    @property
    def n_pacientes(self) -> int:
        return int(self.repo.t["lista"].id_paciente.nunique())

    # ---------- Cronología y calidad ----------
    def cronologia(self, pid: str, corte: date) -> dict | None:
        cron = self.repo.linea_tiempo(pid, corte.isoformat())
        return None if "error" in cron else a_nativo(cron)

    def calidad_paciente(self, pid: str, corte: date, cron: dict) -> list[dict]:
        return a_nativo(copiloto._calidad_por_paciente(
            self.dq, pid, copiloto._ids_citables(cron), pd.Timestamp(corte)))

    def _calidad_global(self, corte: date) -> list[dict]:
        if self.dq.empty:
            return []
        salida: list[dict] = []
        for pid in sorted(self.dq["id_paciente"].dropna().unique()):
            cron = self.cronologia(pid, corte)
            if cron is not None:
                salida += self.calidad_paciente(pid, corte, cron)
        return salida

    def calidad_global(self, corte: date) -> list[dict]:
        return self._calidad.obtener(corte)


def indice_evidencia(cron: dict) -> dict[str, dict]:
    """registro_id -> {registro_id, fuente, fecha, origen} a partir de linea_tiempo."""
    sol = cron["solicitud"]
    indice = {sol["registro_id"]: {"registro_id": sol["registro_id"], "fuente": "solicitud",
                                   "fecha": sol.get("fecha_ingreso"),
                                   "origen": ORIGEN_POR_FUENTE["solicitud"]}}
    for e in cron.get("eventos") or []:
        indice[e["registro_id"]] = {"registro_id": e["registro_id"], "fuente": e["fuente"],
                                    "fecha": e.get("fecha"),
                                    "origen": ORIGEN_POR_FUENTE.get(e["fuente"], "perfiles.json")}
    return indice


def orden_lista(item: dict) -> tuple:
    """Orden del propio motor: prioridad calculada, score, días en espera, id."""
    return (-RANGO.get(item.get("prioridad_calculada") or "", -1), -(item.get("score") or 0),
            -(item.get("dias_en_espera") or 0), item["id_paciente"])


# ---------- Auditoría (solo lectura) ----------
def leer_auditoria(ruta: Path) -> tuple[dict[str, dict], int]:
    """Agrupa analisis_ia y decision_medica por alerta_id. Omite líneas inválidas."""
    grupos: dict[str, dict] = {}
    invalidas = 0
    if not ruta.exists():
        return grupos, 0
    with ruta.open(encoding="utf-8") as f:
        for linea in f:
            if not linea.strip():
                continue
            try:
                reg = json.loads(linea)
            except json.JSONDecodeError:
                invalidas += 1
                continue
            if not isinstance(reg, dict) or reg.get("tipo") not in ("analisis_ia", "decision_medica"):
                continue
            g = grupos.setdefault(str(reg.get("alerta_id")), {"analisis": [], "decisiones": []})
            g["analisis" if reg["tipo"] == "analisis_ia" else "decisiones"].append(reg)
    if invalidas:
        log.warning("auditoría: %d líneas inválidas omitidas", invalidas)
    return grupos, invalidas


def estado_aviso(hist: dict | None) -> str:
    if hist and hist["decisiones"]:
        return "decidido"
    if hist and hist["analisis"]:
        return "analizado"
    return "pendiente"


def historial(alerta_id: str, grupos: dict[str, dict], invalidas: int) -> dict:
    g = grupos.get(alerta_id) or {"analisis": [], "decisiones": []}
    analisis = [{"timestamp": r.get("timestamp"),
                 "origen_inferencia": origen_inferencia(r.get("analisis")),
                 "prioridad_sugerida": (r.get("analisis") or {}).get("prioridad_sugerida"),
                 "resumen": (r.get("analisis") or {}).get("resumen")}
                for r in g["analisis"]]
    decisiones = [{k: r.get(k) for k in ("timestamp", "medico_id", "decision",
                                         "prioridad_final", "comentario")}
                  for r in g["decisiones"]]
    ultimo = g["analisis"][-1].get("analisis") if g["analisis"] else None
    return {"alerta_id": alerta_id, "estado_aviso": estado_aviso(g), "analisis": analisis,
            "decisiones": decisiones, "ultimo_analisis": ultimo,
            "origen_ultimo_analisis": origen_inferencia(ultimo) if ultimo else None,
            "lineas_invalidas": invalidas}
