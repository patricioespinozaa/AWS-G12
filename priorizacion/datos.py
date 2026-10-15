"""Ingesta y normalización: de los CSV del HLF a objetos de dominio por paciente.

En AWS este paso corresponde al job nocturno que lee S3 (raw) y escribe la ficha consolidada.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from . import config
from .reglas import RANGOS_NORMALES, UNIDADES


@dataclass(frozen=True, slots=True)
class Evento:
    id_evento: str
    fecha: date
    tipo: str
    subtipo: str
    severidad: str
    detalle: str


@dataclass(frozen=True, slots=True)
class Medicion:
    fecha: date
    tipo: str
    valor: float
    unidad: str
    fuera_de_rango: bool
    ref: str              # referencia trazable: medicion:PAC/fecha/tipo o externa:EXT-0001
    origen: str = "hospital"   # hospital | externa


@dataclass(frozen=True, slots=True)
class Cita:
    id_cita: str
    fecha: date
    id_box: str
    especialidad: str
    estado: str
    minutos: float | None


@dataclass(frozen=True, slots=True)
class Alarma:
    fecha: date
    ref: str
    detalle: str


@dataclass(slots=True)
class Solicitud:
    id_solicitud: str
    id_paciente: str
    nombre: str
    edad: int
    sexo: str
    comuna: str
    prevision: str
    nivel_socioeconomico: str
    especialidad: str
    sub_especialidad: str
    cie10: str
    diagnostico: str
    prioridad_inicial: str
    fecha_ingreso: date
    origen_derivacion: str
    estado: str
    fallecido: bool
    fecha_defuncion: date | None
    fecha_egreso: date | None      # desde cuándo sale de la lista activa
    motivo_egreso: str | None


@dataclass(slots=True)
class Historia:
    """Todo lo registrado de un paciente, ordenado por fecha, para filtrar rápido a una fecha de corte."""
    eventos: list[Evento] = field(default_factory=list)
    mediciones: dict[str, list[Medicion]] = field(default_factory=dict)
    citas: list[Cita] = field(default_factory=list)
    alarmas: list[Alarma] = field(default_factory=list)
    _fechas_eventos: list[date] = field(default_factory=list)
    _fechas_mediciones: dict[str, list[date]] = field(default_factory=dict)
    _fechas_citas: list[date] = field(default_factory=list)

    def ordenar(self):
        self.eventos.sort(key=lambda e: (e.fecha, e.id_evento))
        self._fechas_eventos = [e.fecha for e in self.eventos]
        for tipo, lista in self.mediciones.items():
            lista.sort(key=lambda m: (m.fecha, m.ref))
            self._fechas_mediciones[tipo] = [m.fecha for m in lista]
        self.citas.sort(key=lambda c: (c.fecha, c.id_cita))
        self._fechas_citas = [c.fecha for c in self.citas]
        self.alarmas.sort(key=lambda a: a.fecha)

    def eventos_hasta(self, corte: date) -> list[Evento]:
        return self.eventos[:bisect_right(self._fechas_eventos, corte)]

    def mediciones_hasta(self, corte: date) -> dict[str, list[Medicion]]:
        return {t: lst[:bisect_right(self._fechas_mediciones[t], corte)]
                for t, lst in self.mediciones.items()}

    def citas_hasta(self, corte: date) -> list[Cita]:
        return self.citas[:bisect_right(self._fechas_citas, corte)]

    def alarmas_hasta(self, corte: date) -> list[Alarma]:
        return [a for a in self.alarmas if a.fecha <= corte]


def _fecha(x) -> date | None:
    return None if pd.isna(x) else pd.Timestamp(x).date()


def leer_csv(data_dir: Path = config.DATA_DIR) -> dict[str, pd.DataFrame]:
    def leer(nombre, fechas=()):
        df = pd.read_csv(data_dir / nombre, encoding="utf-8")
        for c in fechas:
            df[c] = pd.to_datetime(df[c])
        return df

    def booleano(s: pd.Series) -> pd.Series:
        return s if s.dtype == bool else s.astype(str).str.strip().str.lower().eq("true")

    lista = leer("lista_espera.csv", ["fecha_ingreso_lista"])
    lista["diagnostico_cie10"] = lista["diagnostico_cie10"].astype(str).str.strip().str.upper()
    pacientes = leer("pacientes.csv", ["fecha_defuncion"])
    pacientes["fallecido"] = booleano(pacientes["fallecido"])
    mediciones = leer("mediciones.csv", ["fecha_medicion"])
    mediciones["fuera_de_rango"] = booleano(mediciones["fuera_de_rango"])
    return {
        "pacientes": pacientes,
        "lista": lista,
        "eventos": leer("eventos_clinicos.csv", ["fecha_evento"]),
        "mediciones": mediciones,
        "agenda": leer("agenda_box.csv", ["fecha"]),
        "citas": leer("citaciones.csv", ["fecha_cita"]),
    }


NOMBRES_EN_REPOSITORIO = {"pacientes": "pacientes", "lista_espera": "lista", "eventos_clinicos": "eventos",
                          "mediciones": "mediciones", "agenda_box": "agenda", "citaciones": "citas"}


def leer_postgres(conn) -> dict[str, pd.DataFrame]:
    """Los mismos 6 DataFrames que leer_csv(), leídos del esquema raw de RDS (F0005).

    Mismas columnas, en el mismo orden, y mismos tipos que con pandas sobre los CSV: fechas como datetime,
    booleanos, valores numéricos como float y horas de la agenda como texto 'HH:MM'.
    """
    from db.carga import TABLAS
    tablas: dict[str, pd.DataFrame] = {}
    for t in TABLAS:
        if t.nombre not in NOMBRES_EN_REPOSITORIO:
            continue
        columnas = [c for c, _ in t.columnas]
        cur = conn.execute(f"SELECT {', '.join(columnas)} FROM raw.{t.nombre} ORDER BY {', '.join(t.llave)}")
        df = pd.DataFrame(cur.fetchall(), columns=columnas)
        for c, tipo in t.columnas:
            if tipo == "date":
                # Desde texto ISO, igual que al leer el CSV (misma resolución de datetime en pandas)
                df[c] = pd.to_datetime(df[c].map(lambda v: v.isoformat() if v is not None else None))
            elif tipo == "time":
                df[c] = df[c].map(lambda v: v.strftime("%H:%M") if v is not None else None)
            elif tipo == "numeric":
                df[c] = df[c].astype(float)
            elif tipo == "int":
                df[c] = df[c].astype("float64") if df[c].isna().any() else df[c].astype("int64")
            elif tipo == "bool":
                df[c] = df[c].astype(bool)
        tablas[NOMBRES_EN_REPOSITORIO[t.nombre]] = df
    tablas["lista"]["diagnostico_cie10"] = tablas["lista"]["diagnostico_cie10"].astype(str).str.strip().str.upper()
    return {k: tablas[k] for k in ("pacientes", "lista", "eventos", "mediciones", "agenda", "citas")}


class Repositorio:
    """Datos en memoria para el motor y las vistas."""

    def __init__(self, tablas: dict[str, pd.DataFrame]):
        self.tablas = tablas
        self.agenda = tablas["agenda"]
        self.solicitudes: dict[str, Solicitud] = {}
        self.historias: dict[str, Historia] = {}
        self._historias_base: dict[str, Historia] = {}
        self._construir()

    @classmethod
    def desde_csv(cls, data_dir: Path = config.DATA_DIR) -> "Repositorio":
        return cls(leer_csv(data_dir))

    @classmethod
    def desde_postgres(cls, url: str | None = None) -> "Repositorio":
        from db.conexion import conectar
        with conectar(url) as conn:
            return cls(leer_postgres(conn))

    @classmethod
    def crear(cls) -> "Repositorio":
        """Desde RDS si está configurada (F0005); si no, desde los CSV locales."""
        return cls.desde_postgres() if config.usa_rds() else cls.desde_csv()

    # -- construcción ----------------------------------------------------------------------
    def _construir(self):
        t = self.tablas
        historias: dict[str, Historia] = {pid: Historia() for pid in t["pacientes"]["id_paciente"]}

        for r in t["eventos"].itertuples(index=False):
            historias[r.id_paciente].eventos.append(Evento(
                r.id_evento, r.fecha_evento.date(), r.tipo_evento, r.subtipo, r.severidad, r.detalle))
        for r in t["mediciones"].itertuples(index=False):
            f = r.fecha_medicion.date()
            historias[r.id_paciente].mediciones.setdefault(r.tipo_medicion, []).append(Medicion(
                f, r.tipo_medicion, float(r.valor), r.unidad, bool(r.fuera_de_rango),
                f"medicion:{r.id_paciente}/{f.isoformat()}/{r.tipo_medicion}"))
        for r in t["citas"].itertuples(index=False):
            historias[r.id_paciente].citas.append(Cita(
                r.id_cita, r.fecha_cita.date(), r.id_box, r.especialidad, r.estado_cita,
                None if pd.isna(r.minutos_atencion_real) else float(r.minutos_atencion_real)))
        for h in historias.values():
            h.ordenar()
        self._historias_base = historias

        base = t["pacientes"].merge(t["lista"], on="id_paciente")
        for r in base.itertuples(index=False):
            h = historias[r.id_paciente]
            fecha_def = _fecha(r.fecha_defuncion)
            fecha_egreso, motivo = None, None
            if bool(r.fallecido) and fecha_def:
                fecha_egreso, motivo = fecha_def, "fallecido"
            elif r.estado == "atendido":
                # El dataset solo trae el estado final: se usa la primera cita con asistencia
                asist = [c.fecha for c in h.citas if c.estado == "asistio"]
                if asist:
                    fecha_egreso, motivo = min(asist), "atendido"
            self.solicitudes[r.id_solicitud] = Solicitud(
                r.id_solicitud, r.id_paciente, r.nombre_fantasia, int(r.edad), r.sexo, r.comuna,
                r.prevision, r.nivel_socioeconomico, r.especialidad, r.sub_especialidad,
                r.diagnostico_cie10, r.diagnostico_texto, r.prioridad_inicial,
                r.fecha_ingreso_lista.date(), r.origen_derivacion, r.estado, bool(r.fallecido),
                fecha_def, fecha_egreso, motivo)
        self.historias = {pid: self._copiar(h) for pid, h in historias.items()}

    @staticmethod
    def _copiar(h: Historia) -> Historia:
        n = Historia(list(h.eventos), {k: list(v) for k, v in h.mediciones.items()},
                     list(h.citas), list(h.alarmas))
        n.ordenar()
        return n

    # -- datos aportados por el paciente (canal C) ------------------------------------------
    def aplicar_registro(self, evidencias: pd.DataFrame, mensajes: pd.DataFrame, id_paciente: str | None = None):
        """Suma a la historia la evidencia externa VALIDADA y las alarmas validadas.

        La evidencia pendiente no entra al puntaje: solo cuenta lo que un profesional valida.
        """
        ids = [id_paciente] if id_paciente else list(self._historias_base)
        for pid in ids:
            h = self._copiar(self._historias_base[pid])
            ev = evidencias[(evidencias["id_paciente"] == pid) & (evidencias["estado"] == "validada")] \
                if len(evidencias) else evidencias
            for r in ev.itertuples(index=False):
                lo, hi = RANGOS_NORMALES[r.tipo_medicion]
                f = date.fromisoformat(r.fecha_examen)
                h.mediciones.setdefault(r.tipo_medicion, []).append(Medicion(
                    f, r.tipo_medicion, float(r.valor), UNIDADES[r.tipo_medicion],
                    not (lo <= float(r.valor) <= hi), f"externa:{r.id_evidencia}", "externa"))
            al = mensajes[(mensajes["id_paciente"] == pid) & (mensajes["tipo"] == "sintoma_alarma")
                          & (mensajes["estado"] == "validada")] if len(mensajes) else mensajes
            for r in al.itertuples(index=False):
                h.alarmas.append(Alarma(date.fromisoformat(r.fecha), f"mensaje:{r.id_mensaje}", r.detalle))
            h.ordenar()
            self.historias[pid] = h

    # -- utilidades --------------------------------------------------------------------------
    def solicitud_de_paciente(self, id_paciente: str) -> Solicitud:
        return next(s for s in self.solicitudes.values() if s.id_paciente == id_paciente)

    def activas(self, corte: date) -> list[Solicitud]:
        """Solicitudes en la lista a la fecha de corte (ingresadas y sin egreso)."""
        return [s for s in self.solicitudes.values()
                if s.fecha_ingreso <= corte and (s.fecha_egreso is None or corte < s.fecha_egreso)]

    @property
    def fecha_min(self) -> date:
        return min(s.fecha_ingreso for s in self.solicitudes.values())

    @property
    def fecha_max_datos(self) -> date:
        """Última fecha con datos (eventos, mediciones, citas, agenda o ingresos a la lista)."""
        t = self.tablas
        fechas = [t["eventos"]["fecha_evento"].max(), t["mediciones"]["fecha_medicion"].max(),
                  t["citas"]["fecha_cita"].max(), t["agenda"]["fecha"].max(), t["lista"]["fecha_ingreso_lista"].max()]
        return max(f for f in fechas if pd.notna(f)).date()
