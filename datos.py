from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
_dd = Path(os.getenv("DATA_DIR", "."))
DATA_DIR = (_dd if _dd.is_absolute() else BASE_DIR / _dd).resolve()
FECHA_REFERENCIA = pd.Timestamp("2026-10-13")

# Nombre interno -> (CSV, columnas de fecha)
ARCHIVOS = {
    "pacientes":  ("pacientes.csv",        ["fecha_defuncion"]),
    "lista":      ("lista_espera.csv",     ["fecha_ingreso_lista"]),
    "eventos":    ("eventos_clinicos.csv", ["fecha_evento"]),
    "mediciones": ("mediciones.csv",       ["fecha_medicion"]),
    "citaciones": ("citaciones.csv",       ["fecha_cita"]),
    "agenda":     ("agenda_box.csv",       ["fecha"]),
}
# Nombres aceptados al recibir tablas de la ingesta
ALIAS = {
    "pacientes":  ("pacientes", "paciente"),
    "lista":      ("lista", "lista_espera", "solicitudes"),
    "eventos":    ("eventos", "eventos_clinicos"),
    "mediciones": ("mediciones",),
    "citaciones": ("citaciones", "citas"),
    "agenda":     ("agenda", "agenda_box", "box"),
}
ESTADOS_CITA_ASISTIDA = {"asistio", "asistió", "asistida", "atendida", "realizada", "fulfilled"}
_PATRON_GRUPO = re.compile(r"^[A-Z]\d{2}")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin({"true", "1", "si", "sí"})


def _ts(corte: Any) -> pd.Timestamp:
    if corte is None:
        raise ValueError("fecha de corte obligatoria")
    t = pd.Timestamp(corte)
    if pd.isna(t):
        raise ValueError("fecha de corte inválida")
    return t.normalize()


def _py(v: Any) -> Any:
    """Convierte a tipos JSON nativos (sin numpy, NaN ni NaT)."""
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.date().isoformat()
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT or v is pd.NA:
        return None
    return v


def id_medicion(pid: str, fecha: Any, tipo: str, valor: Any) -> str:
    """MED- + hash de (paciente, fecha, tipo, valor). Estable entre JSON y CSV (§4)."""
    v = "" if pd.isna(valor) else f"{float(valor):.4f}"
    clave = f"{pid}|{pd.Timestamp(fecha).date().isoformat()}|{tipo}|{v}"
    return "MED-" + hashlib.sha256(clave.encode("utf-8")).hexdigest()[:10].upper()


def wilson(k: int, n: int, z: float = 1.96):
    """Intervalo de confianza 95 % para una proporción (robusto con n pequeños)."""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(100 * max(0, c - h), 1), round(100 * min(1, c + h), 1)]


def _prop(k: int, n: int) -> dict:
    return {"k": k, "pct": round(100 * k / n, 1) if n else None, "ic95": wilson(k, n)}


# ---------------------------------------------------------------------------
# Repositorio
# ---------------------------------------------------------------------------
class Repositorio:
    def __init__(self, tablas: dict[str, pd.DataFrame] | None = None,
                 data_dir: Path | str | None = None):
        if tablas is None:
            d = Path(data_dir) if data_dir else DATA_DIR
            tablas = {k: pd.read_csv(d / f) for k, (f, _) in ARCHIVOS.items()}
        self.t = self._normalizar(tablas)

        p = self.t["pacientes"]
        if "fallecido" in p:
            p["fallecido"] = _bool(p["fallecido"])
        else:
            p["fallecido"] = p["fecha_defuncion"].notna()

        m = self.t["mediciones"]
        if "fuera_de_rango" in m:
            m["fuera_de_rango"] = _bool(m["fuera_de_rango"])
        m["valor"] = pd.to_numeric(m["valor"], errors="coerce")
        if "id_medicion" not in m or m["id_medicion"].isna().any():
            m["id_medicion"] = [id_medicion(r.id_paciente, r.fecha_medicion, r.tipo_medicion, r.valor)
                                for r in m.itertuples()]

        e = self.t["eventos"]
        detalle = e["detalle"] if "detalle" in e else pd.Series("", index=e.index)
        # "triage ESI 2 (Cardiología)" -> "Cardiología"
        e["especialidad_detalle"] = detalle.astype(str).str.extract(r"\(([^)]+)\)\s*$")[0]

        self.base = self.t["lista"].merge(p, on="id_paciente", how="left",
                                          suffixes=("", "_pac"))
        self.base["fallecido"] = self.base["fallecido"].fillna(False).astype(bool)

    @staticmethod
    def _normalizar(tablas: dict) -> dict[str, pd.DataFrame]:
        out, faltan = {}, []
        for nombre, alias in ALIAS.items():
            clave = next((a for a in alias if a in tablas), None)
            if clave is None:
                faltan.append(nombre)
                continue
            df = tablas[clave].copy()
            for col in ARCHIVOS[nombre][1]:
                if col in df:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
            out[nombre] = df
        if faltan:
            raise KeyError(f"Faltan tablas {faltan}. Recibidas: {sorted(tablas)}")
        return out

    # ---------- Vista del paciente a una fecha de corte ----------
    def contexto(self, id_paciente: str, corte: Any):
        corte = _ts(corte)
        l = self.t["lista"]
        sol = l[(l.id_paciente == id_paciente) & (l.fecha_ingreso_lista <= corte)]
        pac = self.t["pacientes"][self.t["pacientes"].id_paciente == id_paciente]
        if sol.empty or pac.empty:
            return None

        def filtrar(tabla: str, col: str) -> pd.DataFrame:
            df = self.t[tabla]
            return df[(df.id_paciente == id_paciente) & (df[col] <= corte)].sort_values(col)

        return {
            "paciente": pac.iloc[0], "solicitud": sol.iloc[0],
            "eventos": filtrar("eventos", "fecha_evento"),
            "mediciones": filtrar("mediciones", "fecha_medicion"),
            "citas": filtrar("citaciones", "fecha_cita"),
        }

    def linea_tiempo(self, pid: str, corte: Any) -> dict:
        corte = _ts(corte)
        ctx = self.contexto(pid, corte)
        if ctx is None:
            return {"error": "Paciente sin solicitud vigente a la fecha de corte"}
        pac, sol = ctx["paciente"], ctx["solicitud"]

        ev = [{"fecha": _py(r["fecha_evento"]), "registro_id": r["id_evento"], "fuente": "evento",
               "tipo": _py(r.get("tipo_evento")), "subtipo": _py(r.get("subtipo")),
               "severidad": _py(r.get("severidad")), "detalle": _py(r.get("detalle")),
               "especialidad_asociada": _py(r.get("especialidad_detalle"))}
              for r in ctx["eventos"].to_dict("records")]
        ev += [{"fecha": _py(r["fecha_medicion"]), "registro_id": r["id_medicion"],
                "fuente": "medicion", "tipo": _py(r.get("tipo_medicion")),
                "valor": _py(r.get("valor")), "unidad": _py(r.get("unidad")),
                "fuera_de_rango": bool(r.get("fuera_de_rango", False))}
               for r in ctx["mediciones"].to_dict("records")]
        ev += [{"fecha": _py(r["fecha_cita"]), "registro_id": r["id_cita"], "fuente": "cita",
                "especialidad": _py(r.get("especialidad")), "estado": _py(r.get("estado_cita")),
                "id_box": _py(r.get("id_box"))}
               for r in ctx["citas"].to_dict("records")]
        ev.sort(key=lambda x: x["fecha"] or "")

        return {
            "fecha_corte": corte.date().isoformat(),
            "perfil": {"id_paciente": pid, "edad": int(pac["edad"]), "sexo": _py(pac.get("sexo")),
                       "comuna": _py(pac.get("comuna")), "prevision": _py(pac.get("prevision"))},
            "solicitud": {
                "registro_id": sol["id_solicitud"],
                "especialidad": _py(sol.get("especialidad")),
                "sub_especialidad": _py(sol.get("sub_especialidad")),
                "cie10": _py(sol.get("diagnostico_cie10")),
                "diagnostico": _py(sol.get("diagnostico_texto")),
                "prioridad_inicial": _py(sol.get("prioridad_inicial")),
                "fecha_ingreso": _py(sol["fecha_ingreso_lista"]),
                "dias_en_espera": int((corte - sol["fecha_ingreso_lista"]).days),
                "origen": _py(sol.get("origen_derivacion")),
                # El estado es una fotografía a la fecha de referencia (evita fuga de datos)
                "estado": _py(sol.get("estado")) if corte >= FECHA_REFERENCIA
                          else "desconocido_a_la_fecha",
            },
            "n_eventos": len(ev), "eventos": ev,
        }

    # ---------- Capa poblacional ----------
    def cohorte(self, diagnostico_cie10: str, edad_min: int, edad_max: int, corte: Any,
                ventana_dias: int = 90, origen_derivacion: str | None = None,
                excluir_id: str | None = None, n_minimo: int = 10) -> dict:
        corte = _ts(corte)
        grupo = str(diagnostico_cie10).strip().upper()[:3]
        if not _PATRON_GRUPO.match(grupo):
            return {"error": f"grupo CIE-10 inválido: {diagnostico_cie10!r}"}
        td = pd.Timedelta(days=int(ventana_dias))
        b = self.base
        # Solo seguimiento completo dentro de la ventana, antes del corte
        c = b[b.diagnostico_cie10.astype(str).str.upper().str.startswith(grupo)
              & b.edad.between(edad_min, edad_max)
              & (b.fecha_ingreso_lista + td <= corte)]
        if origen_derivacion:
            c = c[c.origen_derivacion == origen_derivacion]
        if excluir_id:
            c = c[c.id_paciente != excluir_id]
        n = int(c.id_paciente.nunique())
        out = {"criterio": {"cie10_grupo": grupo, "edad": [int(edad_min), int(edad_max)],
                            "ventana_dias": int(ventana_dias), "origen": origen_derivacion,
                            "fecha_corte": corte.date().isoformat()},
               "n": n}
        if n == 0:
            return out | {"advertencia": "Sin pacientes comparables."}

        ev = self.t["eventos"].merge(c[["id_paciente", "fecha_ingreso_lista"]], on="id_paciente")
        ev = ev[(ev.fecha_evento >= ev.fecha_ingreso_lista)
                & (ev.fecha_evento <= ev.fecha_ingreso_lista + td)]
        urg = set(ev[ev.tipo_evento == "visita_urgencia"].id_paciente)
        hosp = set(ev[ev.tipo_evento == "hospitalizacion"].id_paciente)
        uci = set(ev[ev.subtipo.astype(str).str.contains("UCI", na=False)].id_paciente)
        muertes = set(c[c.fallecido
                        & (c.fecha_defuncion >= c.fecha_ingreso_lista)
                        & (c.fecha_defuncion <= c.fecha_ingreso_lista + td)].id_paciente)

        out |= {
            "urgencia_en_espera": _prop(len(urg), n),
            "hospitalizacion_en_espera": _prop(len(hosp), n),
            "uci_en_espera": _prop(len(uci), n),
            "fallecimiento_en_espera": _prop(len(muertes), n),
            "cualquier_desenlace_grave": _prop(len(urg | hosp | muertes), n),
            "nota": "Asociación descriptiva en datos sintéticos locales; no es probabilidad "
                    "individual. Refleja solo a pacientes que lograron registrar atenciones.",
        }
        if n < n_minimo:
            out["advertencia"] = f"Muestra pequeña (n<{n_minimo}). Intervalos amplios; no concluir."
        return out

    def estadisticas_cohorte(self, grupo_cie10: str, edad_min: int, edad_max: int,
                             ventana_dias: int = 180, corte: Any = None,
                             excluir_pid: str | None = None) -> dict:
        """Contrato de la herramienta obtener_cohorte (corte y exclusión obligatorios)."""
        if excluir_pid is None:
            raise ValueError("excluir_pid obligatorio: el paciente no puede estar en su cohorte")
        return self.cohorte(grupo_cie10, edad_min, edad_max, _ts(corte),
                            ventana_dias=ventana_dias, excluir_id=excluir_pid)

    # ---------- Recurso box ----------
    def capacidad_box(self, especialidad: str, ventana_dias: int = 30, corte: Any = None) -> dict:
        """Contrato de la herramienta: ventana hacia atrás desde el corte."""
        corte = _ts(corte)
        return self.capacidad_box_periodo(especialidad,
                                          corte - pd.Timedelta(days=int(ventana_dias)), corte)

    def capacidad_box_periodo(self, especialidad: str, desde: Any, hasta: Any) -> dict:
        desde, hasta = _ts(desde), _ts(hasta)
        a = self.t["agenda"]
        a = a[(a.especialidad == especialidad) & a.fecha.between(desde, hasta)].copy()
        if a.empty:
            return {"especialidad": especialidad, "advertencia": "Sin agenda en el periodo"}
        a["libres"] = a.capacidad_cupos - a.cupos_usados
        total = int(a.capacidad_cupos.sum())
        top = a.groupby("fecha").libres.sum().nlargest(5)
        return {
            "especialidad": especialidad,
            "periodo": [desde.date().isoformat(), hasta.date().isoformat()],
            "bloques": int(len(a)), "cupos_totales": total,
            "cupos_libres": int(a.libres.sum()),
            "pct_ocupacion": round(100 * a.cupos_usados.sum() / total, 1) if total else None,
            "sobretiempo_promedio_min": _py(round(a.minutos_sobretiempo.mean(), 1))
                                        if "minutos_sobretiempo" in a else None,
            "pacientes_en_espera_especialidad": self._en_espera_a_la_fecha(especialidad, hasta),
            "dias_con_mas_cupos_libres": {k.date().isoformat(): int(v) for k, v in top.items()},
        }

    def _en_espera_a_la_fecha(self, especialidad: str, corte: pd.Timestamp) -> int:
        """Estimación sin usar 'estado' (fotografía al 13-10): ingresados, vivos y no atendidos."""
        l = self.base
        vig = l[(l.especialidad == especialidad) & (l.fecha_ingreso_lista <= corte)
                & ~(l.fallecido & (l.fecha_defuncion <= corte))]
        c = self.t["citaciones"]
        atendidos = set(c[(c.especialidad == especialidad) & (c.fecha_cita <= corte)
                          & c.estado_cita.astype(str).str.strip().str.lower()
                             .isin(ESTADOS_CITA_ASISTIDA)].id_paciente)
        return int((~vig.id_paciente.isin(atendidos)).sum())