from pathlib import Path
import pandas as pd

DATA_DIR = Path("data")
FECHA_REFERENCIA = pd.Timestamp("2026-10-13")

ARCHIVOS = {
    "pacientes":  ("pacientes.csv",        ["fecha_defuncion"]),
    "lista":      ("lista_espera.csv",     ["fecha_ingreso_lista"]),
    "eventos":    ("eventos_clinicos.csv", ["fecha_evento"]),
    "mediciones": ("mediciones.csv",       ["fecha_medicion"]),
    "citaciones": ("citaciones.csv",       ["fecha_cita"]),
    "agenda":     ("agenda_box.csv",       ["fecha"]),
}


def _bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().eq("true")


def wilson(k: int, n: int, z: float = 1.96):
    """Intervalo de confianza 95 % para una proporción (sirve con n pequeños)."""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(100 * max(0, c - h), 1), round(100 * min(1, c + h), 1)]


def _prop(k, n):
    return {"k": k, "pct": round(100 * k / n, 1) if n else None, "ic95": wilson(k, n)}


class Repositorio:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.t = {k: pd.read_csv(data_dir / f, parse_dates=fechas)
                  for k, (f, fechas) in ARCHIVOS.items()}

        p = self.t["pacientes"]
        p["fallecido"] = _bool(p["fallecido"])

        m = self.t["mediciones"]
        m["fuera_de_rango"] = _bool(m["fuera_de_rango"])
        m["valor"] = pd.to_numeric(m["valor"], errors="coerce")
        m["id_medicion"] = "MED-" + (m.index + 1).astype(str).str.zfill(6)  # ID trazable

        e = self.t["eventos"]
        # "triage ESI 2 (Cardiología)" -> "Cardiología"
        e["especialidad_detalle"] = e["detalle"].str.extract(r"\(([^)]+)\)\s*$")[0]

        self.base = self.t["lista"].merge(p, on="id_paciente", how="left")

    # ---------- Vista del paciente a una fecha de corte ----------
    def contexto(self, id_paciente: str, corte: pd.Timestamp):
        l = self.t["lista"]
        sol = l[(l.id_paciente == id_paciente) & (l.fecha_ingreso_lista <= corte)]
        pac = self.t["pacientes"][self.t["pacientes"].id_paciente == id_paciente]
        if sol.empty or pac.empty:
            return None

        def filtrar(tabla, col):
            df = self.t[tabla]
            return df[(df.id_paciente == id_paciente) & (df[col] <= corte)].sort_values(col)

        return {
            "paciente": pac.iloc[0], "solicitud": sol.iloc[0],
            "eventos": filtrar("eventos", "fecha_evento"),
            "mediciones": filtrar("mediciones", "fecha_medicion"),
            "citas": filtrar("citaciones", "fecha_cita"),
        }

    def linea_tiempo(self, id_paciente: str, corte: pd.Timestamp) -> dict:
        ctx = self.contexto(id_paciente, corte)
        if ctx is None:
            return {"error": "Paciente sin solicitud vigente a la fecha de corte"}
        pac, sol = ctx["paciente"], ctx["solicitud"]
        ev = [{"fecha": r.fecha_evento.date().isoformat(), "registro_id": r.id_evento,
               "fuente": "evento", "tipo": r.tipo_evento, "subtipo": r.subtipo,
               "severidad": r.severidad, "especialidad_asociada": r.especialidad_detalle}
              for r in ctx["eventos"].itertuples()]
        ev += [{"fecha": r.fecha_medicion.date().isoformat(), "registro_id": r.id_medicion,
                "fuente": "medicion", "tipo": r.tipo_medicion, "valor": r.valor,
                "unidad": r.unidad, "fuera_de_rango": bool(r.fuera_de_rango)}
               for r in ctx["mediciones"].itertuples()]
        ev += [{"fecha": r.fecha_cita.date().isoformat(), "registro_id": r.id_cita,
                "fuente": "cita", "especialidad": r.especialidad, "estado": r.estado_cita,
                "id_box": r.id_box}
               for r in ctx["citas"].itertuples()]
        ev.sort(key=lambda x: x["fecha"])
        return {
            "fecha_corte": corte.date().isoformat(),
            "perfil": {"id_paciente": id_paciente, "edad": int(pac.edad), "sexo": pac.sexo,
                       "comuna": pac.comuna, "prevision": pac.prevision},
            "solicitud": {"registro_id": sol.id_solicitud, "especialidad": sol.especialidad,
                          "sub_especialidad": sol.sub_especialidad,
                          "cie10": sol.diagnostico_cie10, "diagnostico": sol.diagnostico_texto,
                          "prioridad_inicial": sol.prioridad_inicial,
                          "fecha_ingreso": sol.fecha_ingreso_lista.date().isoformat(),
                          "dias_en_espera": (corte - sol.fecha_ingreso_lista).days,
                          "origen": sol.origen_derivacion,
                          # El estado solo es válido a la fecha de referencia (evita fuga de datos)
                          "estado": sol.estado if corte >= FECHA_REFERENCIA else "desconocido_a_la_fecha"},
            "n_eventos": len(ev), "eventos": ev,
        }

    # ---------- Capa poblacional ----------
    def cohorte(self, diagnostico_cie10, edad_min, edad_max, corte, ventana_dias=90,
                origen_derivacion=None, excluir_id=None, n_minimo=10) -> dict:
        td = pd.Timedelta(days=ventana_dias)
        b = self.base
        # Solo pacientes con seguimiento completo dentro de la ventana, antes del corte
        c = b[(b.diagnostico_cie10 == diagnostico_cie10)
              & b.edad.between(edad_min, edad_max)
              & (b.fecha_ingreso_lista + td <= corte)]
        if origen_derivacion:
            c = c[c.origen_derivacion == origen_derivacion]
        if excluir_id:
            c = c[c.id_paciente != excluir_id]
        n = len(c)
        out = {"criterio": {"cie10": diagnostico_cie10, "edad": [edad_min, edad_max],
                            "ventana_dias": ventana_dias, "origen": origen_derivacion},
               "n": n}
        if n == 0:
            return out | {"advertencia": "Sin pacientes comparables."}

        ev = self.t["eventos"].merge(c[["id_paciente", "fecha_ingreso_lista"]], on="id_paciente")
        ev = ev[(ev.fecha_evento >= ev.fecha_ingreso_lista)
                & (ev.fecha_evento <= ev.fecha_ingreso_lista + td)]
        urg = set(ev[ev.tipo_evento == "visita_urgencia"].id_paciente)
        hosp = set(ev[ev.tipo_evento == "hospitalizacion"].id_paciente)
        uci = set(ev[ev.subtipo.str.contains("UCI", na=False)].id_paciente)
        muertes = set(c[c.fallecido & (c.fecha_defuncion <= c.fecha_ingreso_lista + td)].id_paciente)

        out |= {
            "urgencia_en_espera": _prop(len(urg), n),
            "hospitalizacion_en_espera": _prop(len(hosp), n),
            "uci_en_espera": _prop(len(uci), n),
            "fallecimiento_en_espera": _prop(len(muertes), n),
            "cualquier_desenlace_grave": _prop(len(urg | hosp | muertes), n),
            "nota": "Asociación descriptiva en datos sintéticos locales; no es probabilidad individual.",
        }
        if n < n_minimo:
            out["advertencia"] = f"Muestra pequeña (n<{n_minimo}). Intervalos amplios; no concluir."
        return out

    # ---------- Recurso box ----------
    def capacidad_box(self, especialidad, desde, hasta) -> dict:
        a = self.t["agenda"]
        a = a[(a.especialidad == especialidad) & a.fecha.between(desde, hasta)].copy()
        if a.empty:
            return {"especialidad": especialidad, "advertencia": "Sin agenda en el periodo"}
        a["libres"] = a.capacidad_cupos - a.cupos_usados
        l = self.base
        esperando = int(((l.especialidad == especialidad) & (l.estado == "en_espera")).sum())
        top = a.groupby("fecha").libres.sum().nlargest(5)
        return {
            "especialidad": especialidad,
            "periodo": [str(desde.date()), str(hasta.date())],
            "bloques": len(a), "cupos_totales": int(a.capacidad_cupos.sum()),
            "cupos_libres": int(a.libres.sum()),
            "pct_ocupacion": round(100 * a.cupos_usados.sum() / a.capacidad_cupos.sum(), 1),
            "sobretiempo_promedio_min": round(a.minutos_sobretiempo.mean(), 1),
            "pacientes_en_espera_especialidad": esperando,
            "dias_con_mas_cupos_libres": {str(k.date()): int(v) for k, v in top.items()},
        }