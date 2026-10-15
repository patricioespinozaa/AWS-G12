"""Registro persistente: lo que genera la app (propuestas, decisiones, serie nocturna, canal del paciente).

Dos implementaciones con la misma interfaz (`Registro`), elegidas con `crear_registro()` (docs/feature/F0005):
- RegistroSQLite: modo local, respaldo de la demo (este archivo).
- RegistroPostgres: RDS, esquemas priorizacion y canal (registro_postgres.py).

Tablas del sistema, separadas de los datos fuente (que nunca se modifican):
- serie_nocturna: resultado de cada corrida nocturna, por solicitud y noche.
- propuesta_prioridad / factor_propuesta: propuestas con su explicación y la fuente de cada factor.
- decision_clinica: lo que decidió el equipo clínico. Nunca se sobrescribe prioridad_inicial.
- evidencia_externa / mensaje_paciente: lo que llega por el canal del paciente.
- corrida_nocturna: bitácora del proceso nocturno.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import pandas as pd

from . import config
from .motor import Decision, Resultado

if TYPE_CHECKING:
    from .archivos import ArchivoGuardado

ESQUEMA = """
CREATE TABLE IF NOT EXISTS serie_nocturna (
    fecha TEXT, id_solicitud TEXT, id_paciente TEXT, especialidad TEXT,
    puntaje REAL, puntaje_nivel REAL, nivel_propuesto TEXT, prioridad_vigente TEXT, prioridad_inicial TEXT,
    cambio TEXT, alerta INTEGER, motivo_principal TEXT,
    posicion_dinamica INTEGER, posicion_estatica INTEGER, total_cola INTEGER,
    PRIMARY KEY (id_solicitud, fecha)
);
CREATE INDEX IF NOT EXISTS ix_serie_fecha ON serie_nocturna (fecha, especialidad);

CREATE TABLE IF NOT EXISTS propuesta_prioridad (
    id_propuesta INTEGER PRIMARY KEY AUTOINCREMENT,
    id_solicitud TEXT, id_paciente TEXT, fecha_corte TEXT, fecha_calculo TEXT,
    puntaje REAL, puntaje_nivel REAL, prioridad_propuesta TEXT, prioridad_vigente TEXT, prioridad_inicial TEXT,
    cambio TEXT, alerta INTEGER, motivos_alerta TEXT, resguardo_aplicado INTEGER,
    version_reglas TEXT, huella_datos TEXT, explicacion_texto TEXT, fuente_explicacion TEXT,
    origen TEXT          -- nocturno | validacion
);
CREATE INDEX IF NOT EXISTS ix_prop_sol ON propuesta_prioridad (id_solicitud, fecha_corte);

CREATE TABLE IF NOT EXISTS factor_propuesta (
    id_propuesta INTEGER, orden INTEGER, codigo TEXT, descripcion TEXT, aporte REAL,
    categoria TEXT, tipo_fuente TEXT, ref_fuente TEXT, fecha_dato TEXT
);
CREATE INDEX IF NOT EXISTS ix_factor_prop ON factor_propuesta (id_propuesta);

CREATE TABLE IF NOT EXISTS decision_clinica (
    id_decision INTEGER PRIMARY KEY AUTOINCREMENT,
    id_propuesta INTEGER, id_solicitud TEXT, fecha_corte TEXT,
    prioridad_anterior TEXT, prioridad_propuesta TEXT,
    decision TEXT, prioridad_final TEXT, motivo TEXT, usuario TEXT, fecha_registro TEXT
);

CREATE TABLE IF NOT EXISTS evidencia_externa (
    id_evidencia TEXT PRIMARY KEY, id_paciente TEXT, fecha_examen TEXT, tipo_medicion TEXT,
    valor REAL, lugar TEXT, archivo TEXT, fecha_recepcion TEXT, estado TEXT,
    revisado_por TEXT, fecha_revision TEXT, nota TEXT
);

CREATE TABLE IF NOT EXISTS mensaje_paciente (
    id_mensaje TEXT PRIMARY KEY, id_paciente TEXT, fecha TEXT, tipo TEXT, detalle TEXT,
    estado TEXT, revisado_por TEXT, fecha_revision TEXT
);

CREATE TABLE IF NOT EXISTS corrida_nocturna (
    id_corrida INTEGER PRIMARY KEY AUTOINCREMENT, inicio TEXT, fin TEXT, desde TEXT, hasta TEXT,
    alcance TEXT, version_reglas TEXT, n_evaluaciones INTEGER, n_propuestas INTEGER, segundos REAL
);
"""


class Registro(Protocol):
    """Lo que la API y el motor necesitan del registro. Los DataFrames tienen las mismas columnas y tipos en
    ambas implementaciones (fechas como texto ISO), para que el resto del código no distinga una de otra."""

    def version(self) -> str: ...
    def conexion(self): ...
    def candado(self, nombre: str): ...
    def reemplazar_serie(self, serie: pd.DataFrame, especialidad: str | None = None): ...
    def serie(self, id_solicitud: str | None = None, especialidad: str | None = None) -> pd.DataFrame: ...
    def serie_resumen(self) -> pd.DataFrame: ...
    def hay_serie(self) -> bool: ...
    def guardar_propuesta(self, r: Resultado, huella: str, explicacion: str, fuente_explicacion: str,
                          origen: str, con=None) -> int: ...
    def borrar_propuestas_nocturnas(self, id_solicitud: str | None = None, con=None): ...
    def propuestas(self, id_solicitud: str | None = None) -> pd.DataFrame: ...
    def factores(self, id_propuesta: int) -> pd.DataFrame: ...
    def registrar_decision(self, id_propuesta: int, r: Resultado, decision: str, prioridad_final: str,
                           motivo: str, usuario: str) -> int: ...
    def decisiones(self, id_solicitud: str | None = None) -> pd.DataFrame: ...
    def decisiones_por_solicitud(self) -> dict[str, list[Decision]]: ...
    def agregar_evidencia(self, id_paciente: str, fecha_examen: date, tipo: str, valor: float, lugar: str,
                          archivo: "ArchivoGuardado | None", fecha_recepcion: date) -> str: ...
    def revisar_evidencia(self, id_evidencia: str, estado: str, revisado_por: str, nota: str): ...
    def evidencias(self) -> pd.DataFrame: ...
    def agregar_mensaje(self, id_paciente: str, fecha: date, tipo: str, detalle: str) -> str: ...
    def revisar_mensaje(self, id_mensaje: str, estado: str, revisado_por: str): ...
    def mensajes(self) -> pd.DataFrame: ...
    def registrar_corrida(self, **kw): ...
    def corridas(self) -> pd.DataFrame: ...


def crear_registro() -> Registro:
    """RegistroPostgres si hay RDS configurada (HLF_DATABASE_URL o HLF_DB_SECRET_ID); si no, SQLite local."""
    if config.usa_rds():
        from .registro_postgres import RegistroPostgres
        return RegistroPostgres()
    return RegistroSQLite()


_CANDADOS: dict[str, threading.Lock] = {}


class RegistroSQLite:
    def __init__(self, ruta: Path = config.DB_PATH):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self.conexion() as c:
            c.executescript(ESQUEMA)

    @contextmanager
    def conexion(self):
        con = sqlite3.connect(self.ruta)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    @contextmanager
    def candado(self, nombre: str):
        """Exclusión mutua (en SQLite solo hay un proceso: basta un candado de hilo)."""
        candado = _CANDADOS.setdefault(nombre, threading.Lock())
        with candado:
            yield

    def consulta(self, sql: str, params=()) -> pd.DataFrame:
        with self.conexion() as c:
            return pd.read_sql_query(sql, c, params=params)

    def version(self) -> str:
        """Cambia cada vez que se escribe algo que afecta las vistas (sirve como llave de caché)."""
        with self.conexion() as c:
            partes = [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
                      ("decision_clinica", "evidencia_externa", "mensaje_paciente", "corrida_nocturna")]
            partes.append(c.execute("SELECT COUNT(*) FROM evidencia_externa WHERE estado != 'pendiente'").fetchone()[0])
            partes.append(c.execute("SELECT COUNT(*) FROM mensaje_paciente WHERE estado != 'pendiente'").fetchone()[0])
        return "-".join(map(str, partes))

    # -- serie nocturna ------------------------------------------------------------------------
    def reemplazar_serie(self, serie: pd.DataFrame, especialidad: str | None = None):
        with self.conexion() as c:
            if especialidad:
                c.execute("DELETE FROM serie_nocturna WHERE especialidad = ?", (especialidad,))
            else:
                c.execute("DELETE FROM serie_nocturna")
            serie.to_sql("serie_nocturna", c, if_exists="append", index=False, chunksize=20000)

    def serie(self, id_solicitud: str | None = None, especialidad: str | None = None) -> pd.DataFrame:
        if id_solicitud:
            return self.consulta("SELECT * FROM serie_nocturna WHERE id_solicitud = ? ORDER BY fecha", (id_solicitud,))
        if especialidad:
            return self.consulta("SELECT * FROM serie_nocturna WHERE especialidad = ?", (especialidad,))
        return self.consulta("SELECT * FROM serie_nocturna")

    def serie_resumen(self) -> pd.DataFrame:
        """Columnas mínimas de la serie para KPIs (más rápido que leer la serie completa)."""
        return self.consulta("SELECT fecha, id_solicitud, nivel_propuesto, prioridad_inicial, cambio, alerta "
                             "FROM serie_nocturna")

    def hay_serie(self) -> bool:
        with self.conexion() as c:
            return c.execute("SELECT EXISTS (SELECT 1 FROM serie_nocturna)").fetchone()[0] == 1

    # -- propuestas ---------------------------------------------------------------------------
    def guardar_propuesta(self, r: Resultado, huella: str, explicacion: str, fuente_explicacion: str,
                          origen: str, con: sqlite3.Connection | None = None) -> int:
        def _guardar(c):
            cur = c.execute(
                "INSERT INTO propuesta_prioridad (id_solicitud, id_paciente, fecha_corte, fecha_calculo, puntaje, puntaje_nivel,"
                " prioridad_propuesta, prioridad_vigente, prioridad_inicial, cambio, alerta, motivos_alerta,"
                " resguardo_aplicado, version_reglas, huella_datos, explicacion_texto, fuente_explicacion, origen)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.id_solicitud, r.id_paciente, r.fecha_corte.isoformat(), datetime.now().isoformat(timespec="seconds"),
                 r.puntaje, r.puntaje_nivel, r.nivel_propuesto, r.prioridad_vigente, r.prioridad_inicial, r.cambio, int(r.alerta),
                 json.dumps(r.motivos_alerta, ensure_ascii=False), int(r.resguardo_aplicado), r.version_reglas,
                 huella, explicacion, fuente_explicacion, origen))
            pid = cur.lastrowid
            c.executemany(
                "INSERT INTO factor_propuesta VALUES (?,?,?,?,?,?,?,?,?)",
                [(pid, i, f.codigo, f.descripcion, round(f.aporte, 3), f.categoria, f.tipo_fuente, f.ref_fuente,
                  f.fecha_dato.isoformat() if f.fecha_dato else None) for i, f in enumerate(r.factores)])
            return pid
        if con is not None:
            return _guardar(con)
        with self.conexion() as c:
            return _guardar(c)

    def borrar_propuestas_nocturnas(self, id_solicitud: str | None = None, con: sqlite3.Connection | None = None):
        def _borrar(c):
            filtro, params = ("AND id_solicitud = ?", (id_solicitud,)) if id_solicitud else ("", ())
            c.execute(f"DELETE FROM factor_propuesta WHERE id_propuesta IN (SELECT id_propuesta FROM "
                      f"propuesta_prioridad WHERE origen = 'nocturno' {filtro})", params)
            c.execute(f"DELETE FROM propuesta_prioridad WHERE origen = 'nocturno' {filtro}", params)
        if con is not None:
            return _borrar(con)
        with self.conexion() as c:
            _borrar(c)

    def propuestas(self, id_solicitud: str | None = None) -> pd.DataFrame:
        if id_solicitud:
            return self.consulta("SELECT * FROM propuesta_prioridad WHERE id_solicitud = ? ORDER BY fecha_corte, "
                                 "id_propuesta", (id_solicitud,))
        return self.consulta("SELECT * FROM propuesta_prioridad")

    def factores(self, id_propuesta: int) -> pd.DataFrame:
        return self.consulta("SELECT * FROM factor_propuesta WHERE id_propuesta = ? ORDER BY orden", (int(id_propuesta),))

    # -- decisiones ---------------------------------------------------------------------------
    def registrar_decision(self, id_propuesta: int, r: Resultado, decision: str, prioridad_final: str,
                           motivo: str, usuario: str) -> int:
        with self.conexion() as c:
            cur = c.execute(
                "INSERT INTO decision_clinica (id_propuesta, id_solicitud, fecha_corte, prioridad_anterior,"
                " prioridad_propuesta, decision, prioridad_final, motivo, usuario, fecha_registro)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (id_propuesta, r.id_solicitud, r.fecha_corte.isoformat(), r.prioridad_vigente, r.nivel_propuesto,
                 decision, prioridad_final, motivo, usuario, datetime.now().isoformat(timespec="seconds")))
            return cur.lastrowid

    def decisiones(self, id_solicitud: str | None = None) -> pd.DataFrame:
        if id_solicitud:
            return self.consulta("SELECT * FROM decision_clinica WHERE id_solicitud = ? ORDER BY fecha_corte, "
                                 "id_decision", (id_solicitud,))
        return self.consulta("SELECT * FROM decision_clinica ORDER BY fecha_corte, id_decision")

    def decisiones_por_solicitud(self) -> dict[str, list[Decision]]:
        out: dict[str, list[Decision]] = {}
        for r in self.decisiones().itertuples(index=False):
            out.setdefault(r.id_solicitud, []).append(Decision(date.fromisoformat(r.fecha_corte), r.prioridad_final))
        return out

    # -- canal del paciente -------------------------------------------------------------------
    def _siguiente_id(self, c, tabla: str, columna: str, prefijo: str) -> str:
        n = c.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] + 1
        return f"{prefijo}-{n:05d}"

    def agregar_evidencia(self, id_paciente: str, fecha_examen: date, tipo: str, valor: float, lugar: str,
                          archivo: "ArchivoGuardado | None", fecha_recepcion: date) -> str:
        with self.conexion() as c:
            ide = self._siguiente_id(c, "evidencia_externa", "id_evidencia", "EXT")
            c.execute("INSERT INTO evidencia_externa VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (ide, id_paciente, fecha_examen.isoformat(), tipo, valor, lugar, archivo.uri if archivo else None,
                       fecha_recepcion.isoformat(), "pendiente", None, None, None))
            return ide

    def revisar_evidencia(self, id_evidencia: str, estado: str, revisado_por: str, nota: str):
        with self.conexion() as c:
            c.execute("UPDATE evidencia_externa SET estado = ?, revisado_por = ?, fecha_revision = ?, nota = ? "
                      "WHERE id_evidencia = ?", (estado, revisado_por, datetime.now().isoformat(timespec="seconds"),
                                                 nota, id_evidencia))

    def evidencias(self) -> pd.DataFrame:
        return self.consulta("SELECT * FROM evidencia_externa ORDER BY id_evidencia")

    def agregar_mensaje(self, id_paciente: str, fecha: date, tipo: str, detalle: str) -> str:
        # Las alarmas requieren revisión; el resto (confirmaciones) se registra directamente
        estado = "pendiente" if tipo == "sintoma_alarma" else "registrado"
        with self.conexion() as c:
            idm = self._siguiente_id(c, "mensaje_paciente", "id_mensaje", "MSG")
            c.execute("INSERT INTO mensaje_paciente VALUES (?,?,?,?,?,?,?,?)",
                      (idm, id_paciente, fecha.isoformat(), tipo, detalle, estado, None, None))
            return idm

    def revisar_mensaje(self, id_mensaje: str, estado: str, revisado_por: str):
        with self.conexion() as c:
            c.execute("UPDATE mensaje_paciente SET estado = ?, revisado_por = ?, fecha_revision = ? "
                      "WHERE id_mensaje = ?", (estado, revisado_por, datetime.now().isoformat(timespec="seconds"),
                                               id_mensaje))

    def mensajes(self) -> pd.DataFrame:
        return self.consulta("SELECT * FROM mensaje_paciente ORDER BY id_mensaje")

    # -- bitácora -----------------------------------------------------------------------------
    def registrar_corrida(self, **kw):
        with self.conexion() as c:
            c.execute("INSERT INTO corrida_nocturna (inicio, fin, desde, hasta, alcance, version_reglas, "
                      "n_evaluaciones, n_propuestas, segundos) VALUES (?,?,?,?,?,?,?,?,?)",
                      (kw["inicio"], kw["fin"], kw["desde"], kw["hasta"], kw["alcance"], kw["version_reglas"],
                       kw["n_evaluaciones"], kw["n_propuestas"], kw["segundos"]))

    def corridas(self) -> pd.DataFrame:
        return self.consulta("SELECT * FROM corrida_nocturna ORDER BY id_corrida DESC")
