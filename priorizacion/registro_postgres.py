"""Registro sobre RDS PostgreSQL: esquemas priorizacion y canal (F0002), con la interfaz de `Registro`.

Devuelve DataFrames con las mismas columnas y tipos que RegistroSQLite (fechas como texto ISO, banderas como
0/1), así la API y el motor no distinguen una implementación de otra. Las diferencias con SQLite:
- Las columnas que el modelo no duplica (especialidad, prioridad_inicial, id_paciente) salen de raw.lista_espera.
- Los IDs de evidencias y mensajes son números en la base; se exponen como texto (la API los trata como opacos).
- Toda escritura sube priorizacion.estado_app.version en la misma transacción: así cada tarea del backend sabe
  cuándo refrescar su caché (varias tareas detrás del ALB).
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import date, datetime

import pandas as pd
import psycopg

from . import config
from .motor import Decision, Resultado

SERIE = """
    SELECT s.fecha::text AS fecha, s.id_solicitud, le.id_paciente, le.especialidad, s.puntaje::float8 AS puntaje,
           s.puntaje_nivel::float8 AS puntaje_nivel, s.nivel_propuesto, s.prioridad_vigente, le.prioridad_inicial,
           s.cambio, s.alerta::int AS alerta, s.motivo_principal, s.posicion_dinamica, s.posicion_estatica,
           s.total_cola
    FROM priorizacion.serie_nocturna s JOIN raw.lista_espera le USING (id_solicitud)"""
COLUMNAS_SERIE = ["id_solicitud", "fecha", "puntaje", "puntaje_nivel", "nivel_propuesto", "prioridad_vigente",
                  "cambio", "alerta", "motivo_principal", "posicion_dinamica", "posicion_estatica", "total_cola"]
PROPUESTAS = """
    SELECT p.id_propuesta, p.id_solicitud, le.id_paciente, p.fecha_corte::text AS fecha_corte,
           to_char(p.fecha_calculo, 'YYYY-MM-DD"T"HH24:MI:SS') AS fecha_calculo, p.puntaje::float8 AS puntaje,
           p.puntaje_nivel::float8 AS puntaje_nivel, p.prioridad_propuesta, p.prioridad_vigente,
           le.prioridad_inicial, p.cambio, p.alerta::int AS alerta, p.motivos_alerta::text AS motivos_alerta,
           p.resguardo_aplicado::int AS resguardo_aplicado, p.version_reglas, p.huella_datos, p.explicacion_texto,
           p.fuente_explicacion, p.origen
    FROM priorizacion.propuesta_prioridad p JOIN raw.lista_espera le USING (id_solicitud)"""
DECISIONES = """
    SELECT id_decision, id_propuesta, id_solicitud, fecha_corte::text AS fecha_corte, prioridad_anterior,
           prioridad_propuesta, decision, prioridad_final, motivo, id_usuario AS usuario,
           to_char(fecha_registro, 'YYYY-MM-DD"T"HH24:MI:SS') AS fecha_registro
    FROM priorizacion.decision_clinica"""
EVIDENCIAS = """
    SELECT id_evidencia::text AS id_evidencia, id_paciente, fecha_examen::text AS fecha_examen, tipo_medicion,
           valor::float8 AS valor, lugar, uri_archivo AS archivo, fecha_recepcion::text AS fecha_recepcion, estado,
           revisado_por, to_char(fecha_revision, 'YYYY-MM-DD"T"HH24:MI:SS') AS fecha_revision, nota
    FROM canal.evidencia_externa ORDER BY evidencia_externa.id_evidencia"""
MENSAJES = """
    SELECT id_mensaje::text AS id_mensaje, id_paciente, fecha::text AS fecha, tipo, detalle, estado, revisado_por,
           to_char(fecha_revision, 'YYYY-MM-DD"T"HH24:MI:SS') AS fecha_revision
    FROM canal.mensaje_paciente ORDER BY mensaje_paciente.id_mensaje"""
CORRIDAS = """
    SELECT id_corrida, to_char(inicio, 'YYYY-MM-DD"T"HH24:MI:SS') AS inicio,
           to_char(fin, 'YYYY-MM-DD"T"HH24:MI:SS') AS fin, desde::text AS desde, hasta::text AS hasta, alcance,
           version_reglas, n_evaluaciones, n_propuestas, segundos::float8 AS segundos
    FROM priorizacion.corrida_nocturna ORDER BY id_corrida DESC"""
FUENTE_EXPLICACION = {"plantilla": "plantilla", "bedrock": "llm", "llm": "llm"}


class RegistroPostgres:
    def __init__(self, url: str | None = None):
        self._url = url
        self._lock = threading.RLock()
        self._conn: psycopg.Connection | None = None

    # -- conexión ---------------------------------------------------------------------------------
    def _abrir(self) -> psycopg.Connection:
        from db.conexion import conectar
        conn = conectar(self._url)
        conn.autocommit = True
        return conn

    def _con(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed or self._conn.broken:
            self._conn = self._abrir()
        return self._conn

    @contextmanager
    def conexion(self):
        """Una transacción. Al terminar sin error se confirma, y la versión de la app sube."""
        with self._lock:
            conn = self._con()
            with conn.transaction():
                yield conn
                self._tocar(conn)

    @contextmanager
    def candado(self, nombre: str):
        """Exclusión mutua entre tareas (pg_advisory_lock en una conexión propia)."""
        conn = self._abrir()
        try:
            conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (nombre,))
            yield
        finally:
            conn.close()

    @staticmethod
    def _tocar(conn: psycopg.Connection):
        conn.execute("UPDATE priorizacion.estado_app SET version = version + 1, actualizado_en = now() WHERE id = 1")

    def consulta(self, sql: str, params=()) -> pd.DataFrame:
        with self._lock:
            cur = self._con().execute(sql, params)
            columnas = [d.name for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columnas)

    def version(self) -> str:
        with self._lock:
            app, datos = self._con().execute(
                "SELECT (SELECT version FROM priorizacion.estado_app WHERE id = 1), "
                "(SELECT coalesce(max(version), 0) FROM raw.carga_lote)").fetchone()
        return f"{app}-{datos}"

    def version_datos(self) -> int:
        """Versión de raw (última carga aplicada): si cambia, la app recarga el repositorio en memoria."""
        with self._lock:
            return self._con().execute("SELECT coalesce(max(version), 0) FROM raw.carga_lote").fetchone()[0]

    # -- serie nocturna -----------------------------------------------------------------------------
    def reemplazar_serie(self, serie: pd.DataFrame, especialidad: str | None = None):
        with self.conexion() as c:
            if especialidad:
                c.execute("DELETE FROM priorizacion.serie_nocturna s USING raw.lista_espera le "
                          "WHERE s.id_solicitud = le.id_solicitud AND le.especialidad = %s", (especialidad,))
            else:
                c.execute("DELETE FROM priorizacion.serie_nocturna")
            filas = serie[COLUMNAS_SERIE].astype(object).where(serie[COLUMNAS_SERIE].notna(), None)
            with c.cursor().copy(f"COPY priorizacion.serie_nocturna ({', '.join(COLUMNAS_SERIE)}) FROM STDIN") as copia:
                for f in filas.itertuples(index=False):
                    copia.write_row((f.id_solicitud, f.fecha, f.puntaje, f.puntaje_nivel, f.nivel_propuesto,
                                     f.prioridad_vigente, f.cambio, bool(f.alerta), f.motivo_principal,
                                     int(f.posicion_dinamica), int(f.posicion_estatica), int(f.total_cola)))

    def serie(self, id_solicitud: str | None = None, especialidad: str | None = None) -> pd.DataFrame:
        if id_solicitud:
            return self.consulta(SERIE + " WHERE s.id_solicitud = %s ORDER BY s.fecha", (id_solicitud,))
        if especialidad:
            return self.consulta(SERIE + " WHERE le.especialidad = %s", (especialidad,))
        return self.consulta(SERIE)

    def serie_resumen(self) -> pd.DataFrame:
        return self.consulta("SELECT s.fecha::text AS fecha, s.id_solicitud, s.nivel_propuesto, le.prioridad_inicial, "
                             "s.cambio, s.alerta::int AS alerta FROM priorizacion.serie_nocturna s "
                             "JOIN raw.lista_espera le USING (id_solicitud)")

    def hay_serie(self) -> bool:
        with self._lock:
            return self._con().execute("SELECT EXISTS (SELECT 1 FROM priorizacion.serie_nocturna)").fetchone()[0]

    # -- propuestas ---------------------------------------------------------------------------------
    def guardar_propuesta(self, r: Resultado, huella: str, explicacion: str, fuente_explicacion: str,
                          origen: str, con: psycopg.Connection | None = None) -> int:
        def _guardar(c):
            pid = c.execute(
                "INSERT INTO priorizacion.propuesta_prioridad (id_solicitud, origen, fecha_corte, puntaje, "
                "puntaje_nivel, prioridad_propuesta, prioridad_vigente, cambio, alerta, motivos_alerta, "
                "resguardo_aplicado, version_reglas, huella_datos, explicacion_texto, fuente_explicacion) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id_propuesta",
                (r.id_solicitud, origen, r.fecha_corte, r.puntaje, r.puntaje_nivel, r.nivel_propuesto,
                 r.prioridad_vigente, r.cambio, bool(r.alerta), json.dumps(r.motivos_alerta, ensure_ascii=False),
                 bool(r.resguardo_aplicado), r.version_reglas, huella, explicacion,
                 FUENTE_EXPLICACION.get(fuente_explicacion, "plantilla"))).fetchone()[0]
            with c.cursor() as cur:
                cur.executemany(
                    "INSERT INTO priorizacion.factor_propuesta (id_propuesta, orden, codigo, descripcion, aporte, "
                    "categoria, tipo_fuente, ref_fuente, fecha_dato) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [(pid, i, f.codigo, f.descripcion, round(f.aporte, 3), f.categoria, f.tipo_fuente, f.ref_fuente,
                      f.fecha_dato) for i, f in enumerate(r.factores)])
            return pid
        if con is not None:
            return _guardar(con)
        with self.conexion() as c:
            return _guardar(c)

    def borrar_propuestas_nocturnas(self, id_solicitud: str | None = None, con: psycopg.Connection | None = None):
        def _borrar(c):
            filtro, params = ("AND id_solicitud = %s", (id_solicitud,)) if id_solicitud else ("", ())
            # factor_propuesta se borra en cascada
            c.execute(f"DELETE FROM priorizacion.propuesta_prioridad WHERE origen = 'nocturno' {filtro}", params)
        if con is not None:
            return _borrar(con)
        with self.conexion() as c:
            _borrar(c)

    def propuestas(self, id_solicitud: str | None = None) -> pd.DataFrame:
        if id_solicitud:
            return self.consulta(PROPUESTAS + " WHERE p.id_solicitud = %s ORDER BY p.fecha_corte, p.id_propuesta",
                                 (id_solicitud,))
        return self.consulta(PROPUESTAS)

    def factores(self, id_propuesta: int) -> pd.DataFrame:
        return self.consulta("SELECT id_propuesta, orden, codigo, descripcion, aporte::float8 AS aporte, categoria, "
                             "tipo_fuente, ref_fuente, fecha_dato::text AS fecha_dato FROM priorizacion.factor_propuesta "
                             "WHERE id_propuesta = %s ORDER BY orden", (int(id_propuesta),))

    # -- decisiones ---------------------------------------------------------------------------------
    def registrar_decision(self, id_propuesta: int, r: Resultado, decision: str, prioridad_final: str,
                           motivo: str, usuario: str) -> int:
        with self.conexion() as c:
            return c.execute(
                "INSERT INTO priorizacion.decision_clinica (id_propuesta, id_solicitud, fecha_corte, "
                "prioridad_anterior, prioridad_propuesta, decision, prioridad_final, motivo, id_usuario) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id_decision",
                (id_propuesta, r.id_solicitud, r.fecha_corte, r.prioridad_vigente, r.nivel_propuesto, decision,
                 prioridad_final, motivo, usuario)).fetchone()[0]

    def decisiones(self, id_solicitud: str | None = None) -> pd.DataFrame:
        if id_solicitud:
            return self.consulta(DECISIONES + " WHERE id_solicitud = %s ORDER BY fecha_corte, id_decision",
                                 (id_solicitud,))
        return self.consulta(DECISIONES + " ORDER BY fecha_corte, id_decision")

    def decisiones_por_solicitud(self) -> dict[str, list[Decision]]:
        out: dict[str, list[Decision]] = {}
        for r in self.decisiones().itertuples(index=False):
            out.setdefault(r.id_solicitud, []).append(Decision(date.fromisoformat(r.fecha_corte), r.prioridad_final))
        return out

    # -- canal del paciente -------------------------------------------------------------------------
    def agregar_evidencia(self, id_paciente: str, fecha_examen: date, tipo: str, valor: float, lugar: str,
                          archivo, fecha_recepcion: date) -> str:
        with self.conexion() as c:
            ide = c.execute(
                "INSERT INTO canal.evidencia_externa (id_paciente, canal_origen, fecha_examen, tipo_medicion, valor, "
                "lugar, uri_archivo, sha256_archivo, tipo_mime, fecha_recepcion) "
                "VALUES (%s, 'web', %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id_evidencia",
                (id_paciente, fecha_examen, tipo, valor, lugar or "",
                 archivo.uri if archivo else None, archivo.sha256 if archivo else None,
                 archivo.tipo_mime if archivo else None, fecha_recepcion)).fetchone()[0]
        return str(ide)

    def revisar_evidencia(self, id_evidencia: str, estado: str, revisado_por: str, nota: str):
        with self.conexion() as c:
            c.execute("UPDATE canal.evidencia_externa SET estado = %s, revisado_por = %s, fecha_revision = now(), "
                      "nota = %s WHERE id_evidencia = %s", (estado, revisado_por, nota, int(id_evidencia)))

    def evidencias(self) -> pd.DataFrame:
        return self.consulta(EVIDENCIAS)

    def agregar_mensaje(self, id_paciente: str, fecha: date, tipo: str, detalle: str) -> str:
        # Las alarmas requieren revisión; el resto (confirmaciones) se registra directamente
        estado = "pendiente" if tipo == "sintoma_alarma" else "registrado"
        with self.conexion() as c:
            idm = c.execute(
                "INSERT INTO canal.mensaje_paciente (id_paciente, canal_origen, fecha, tipo, detalle, estado) "
                "VALUES (%s, 'web', %s, %s, %s, %s) RETURNING id_mensaje",
                (id_paciente, fecha, tipo, detalle or "", estado)).fetchone()[0]
        return str(idm)

    def revisar_mensaje(self, id_mensaje: str, estado: str, revisado_por: str):
        with self.conexion() as c:
            c.execute("UPDATE canal.mensaje_paciente SET estado = %s, revisado_por = %s, fecha_revision = now() "
                      "WHERE id_mensaje = %s", (estado, revisado_por, int(id_mensaje)))

    def mensajes(self) -> pd.DataFrame:
        return self.consulta(MENSAJES)

    # -- bitácora -----------------------------------------------------------------------------------
    def registrar_corrida(self, **kw):
        with self.conexion() as c:
            c.execute("INSERT INTO priorizacion.corrida_nocturna (inicio, fin, desde, hasta, alcance, version_reglas, "
                      "n_evaluaciones, n_propuestas, segundos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                      (datetime.fromisoformat(kw["inicio"]), datetime.fromisoformat(kw["fin"]), kw["desde"],
                       kw["hasta"], kw["alcance"], kw["version_reglas"], kw["n_evaluaciones"], kw["n_propuestas"],
                       kw["segundos"]))

    def corridas(self) -> pd.DataFrame:
        return self.consulta(CORRIDAS)
