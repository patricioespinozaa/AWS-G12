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
from .registro import ROL_ADMINISTRACION, decisiones_a_objetos

SERIE = """
    SELECT s.fecha::text AS fecha, s.id_solicitud, le.id_paciente, le.especialidad, s.puntaje::float8 AS puntaje,
           s.puntaje_nivel::float8 AS puntaje_nivel, s.nivel_propuesto, s.prioridad_vigente, le.prioridad_inicial,
           s.cambio, s.alerta::int AS alerta, s.motivo_principal, s.posicion_dinamica, s.posicion_estatica,
           s.total_cola, s.ajuste_puntaje::float8 AS ajuste_puntaje
    FROM priorizacion.serie_nocturna s JOIN raw.lista_espera le USING (id_solicitud)"""
COLUMNAS_SERIE = ["id_solicitud", "fecha", "puntaje", "puntaje_nivel", "nivel_propuesto", "prioridad_vigente",
                  "cambio", "alerta", "motivo_principal", "posicion_dinamica", "posicion_estatica", "total_cola",
                  "ajuste_puntaje"]
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
           to_char(fecha_registro, 'YYYY-MM-DD"T"HH24:MI:SS') AS fecha_registro,
           puntaje_calculado::float8 AS puntaje_calculado, ajuste_puntaje::float8 AS ajuste_puntaje
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
           version_reglas, n_evaluaciones, n_propuestas, segundos::float8 AS segundos, origen, estado, id_carga,
           detalle::text AS detalle, error
    FROM priorizacion.corrida_nocturna ORDER BY id_corrida DESC"""
ESTIMACIONES = """
    SELECT id_solicitud, fecha_calculo::text AS fecha_calculo, prioridad_vigente, posicion_vigente, total_cola,
           dias_estimados_min, dias_estimados_max, confianza, metodo, version_metodo, publicable::int AS publicable
    FROM priorizacion.estimacion_espera"""
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
            self._copiar_serie(c, serie)

    @staticmethod
    def _copiar_serie(c: psycopg.Connection, serie: pd.DataFrame):
        if serie.empty:
            return
        for anio in sorted({int(f[:4]) for f in serie["fecha"].astype(str).unique()}):
            c.execute("SELECT priorizacion.asegurar_particion_serie(%s)", (anio,))
        filas = serie[COLUMNAS_SERIE].astype(object).where(serie[COLUMNAS_SERIE].notna(), None)
        with c.cursor().copy(f"COPY priorizacion.serie_nocturna ({', '.join(COLUMNAS_SERIE)}) FROM STDIN") as copia:
            for f in filas.itertuples(index=False):
                copia.write_row((f.id_solicitud, f.fecha, f.puntaje, f.puntaje_nivel, f.nivel_propuesto,
                                 f.prioridad_vigente, f.cambio, bool(f.alerta), f.motivo_principal,
                                 int(f.posicion_dinamica), int(f.posicion_estatica), int(f.total_cola),
                                 f.ajuste_puntaje or 0))

    def reemplazar_noches(self, serie: pd.DataFrame, fechas: set[str]):
        """Reemplaza solo las noches indicadas (todas las especialidades). Lo usa la consolidación (F0006)."""
        with self.conexion() as c:
            c.execute("DELETE FROM priorizacion.serie_nocturna WHERE fecha = ANY(%s::date[])", (sorted(fechas),))
            self._copiar_serie(c, serie)

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
                           motivo: str, usuario: str, ajuste_puntaje: float | None = None) -> int:
        with self.conexion() as c:
            return c.execute(
                "INSERT INTO priorizacion.decision_clinica (id_propuesta, id_solicitud, fecha_corte, "
                "prioridad_anterior, prioridad_propuesta, decision, prioridad_final, motivo, id_usuario, "
                "puntaje_calculado, ajuste_puntaje) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id_decision",
                (id_propuesta, r.id_solicitud, r.fecha_corte, r.prioridad_vigente, r.nivel_propuesto, decision,
                 prioridad_final, motivo, usuario, r.puntaje, ajuste_puntaje)).fetchone()[0]

    def decisiones(self, id_solicitud: str | None = None) -> pd.DataFrame:
        if id_solicitud:
            return self.consulta(DECISIONES + " WHERE id_solicitud = %s ORDER BY fecha_corte, id_decision",
                                 (id_solicitud,))
        return self.consulta(DECISIONES + " ORDER BY fecha_corte, id_decision")

    def decisiones_por_solicitud(self) -> dict[str, list[Decision]]:
        return decisiones_a_objetos(self.decisiones())

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
        origen = kw.get("origen") or ("completo" if kw["alcance"] == "historia completa" else "solicitud")
        with self.conexion() as c:
            c.execute("INSERT INTO priorizacion.corrida_nocturna (inicio, fin, desde, hasta, alcance, version_reglas, "
                      "n_evaluaciones, n_propuestas, segundos, origen, estado) "
                      "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'completa')",
                      (datetime.fromisoformat(kw["inicio"]), datetime.fromisoformat(kw["fin"]), kw["desde"],
                       kw["hasta"], kw["alcance"], kw["version_reglas"], kw["n_evaluaciones"], kw["n_propuestas"],
                       kw["segundos"], origen))

    def corridas(self) -> pd.DataFrame:
        return self.consulta(CORRIDAS)

    # -- consolidación (F0006) ----------------------------------------------------------------------
    def fecha_corte(self) -> date | None:
        """La fecha de los datos: fin del periodo de la última versión aplicada (o la fija del modo manual)."""
        with self._lock:
            return self._con().execute("SELECT priorizacion.fecha_corte()").fetchone()[0]

    # -- personas (F0007) ---------------------------------------------------------------------------
    def sincronizar_usuario(self, id_usuario: str, nombre: str) -> bool:
        """Crea o actualiza a la persona autenticada (rol `administracion`) en priorizacion.usuario, que es la FK
        de todas las columnas *_por. Devuelve si puede entrar: activa y con ese rol (una cuenta desactivada en la
        base no entra aunque su token sea válido). No sube la versión de la app."""
        with self._lock:
            c = self._con()
            with c.transaction():
                c.execute("INSERT INTO priorizacion.usuario (id_usuario, nombre, rol) VALUES (%s, %s, %s) "
                          "ON CONFLICT (id_usuario) DO UPDATE SET nombre = EXCLUDED.nombre "
                          "WHERE priorizacion.usuario.nombre IS DISTINCT FROM EXCLUDED.nombre",
                          (id_usuario, nombre, ROL_ADMINISTRACION))
                activo, rol = c.execute("SELECT activo, rol FROM priorizacion.usuario WHERE id_usuario = %s",
                                        (id_usuario,)).fetchone()
        return bool(activo) and rol == ROL_ADMINISTRACION

    def usuarios(self) -> pd.DataFrame:
        return self.consulta("SELECT id_usuario, nombre, rol, activo::int AS activo FROM priorizacion.usuario "
                             "WHERE rol = %s ORDER BY id_usuario", (ROL_ADMINISTRACION,))

    def activar_usuario(self, id_usuario: str, activo: bool) -> bool:
        with self.conexion() as c:
            return c.execute("UPDATE priorizacion.usuario SET activo = %s WHERE id_usuario = %s",
                             (activo, id_usuario)).rowcount > 0

    def modo_fecha(self) -> str:
        """`datos` (la fecha de la última versión aplicada) o `manual` (fijada para un ensayo)."""
        with self._lock:
            fila = self._con().execute("SELECT modo FROM priorizacion.reloj WHERE id = 1").fetchone()
        return fila[0] if fila else "datos"

    def iniciar_corrida(self, origen: str, alcance: str, desde: date, hasta: date, id_carga: int | None = None) -> int:
        from . import reglas as R
        with self.conexion() as c:
            return c.execute("INSERT INTO priorizacion.corrida_nocturna (inicio, desde, hasta, alcance, version_reglas, "
                             "origen, estado, id_carga) VALUES (now(), %s, %s, %s, %s, %s, 'en_curso', %s) "
                             "RETURNING id_corrida",
                             (desde, max(desde, hasta), alcance, R.VERSION_REGLAS, origen, id_carga)).fetchone()[0]

    def terminar_corrida(self, id_corrida: int, estado: str, n_evaluaciones: int = 0, n_propuestas: int = 0,
                         detalle: dict | None = None, error: str | None = None):
        with self.conexion() as c:
            c.execute("UPDATE priorizacion.corrida_nocturna SET fin = now(), estado = %s, n_evaluaciones = %s, "
                      "n_propuestas = %s, segundos = extract(epoch FROM now() - inicio), detalle = %s, error = %s "
                      "WHERE id_corrida = %s",
                      (estado, n_evaluaciones, n_propuestas, json.dumps(detalle or {}, ensure_ascii=False, default=str),
                       error, id_corrida))

    def corrida_en_curso(self) -> bool:
        with self._lock:
            return self._con().execute("SELECT EXISTS (SELECT 1 FROM priorizacion.corrida_nocturna "
                                       "WHERE estado = 'en_curso')").fetchone()[0]

    def guardar_estimaciones(self, fecha: date, estimaciones: pd.DataFrame):
        with self.conexion() as c:
            c.execute("DELETE FROM priorizacion.estimacion_espera WHERE fecha_calculo = %s", (fecha,))
            if len(estimaciones):
                with c.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO priorizacion.estimacion_espera (id_solicitud, fecha_calculo, prioridad_vigente, "
                        "posicion_vigente, total_cola, dias_estimados_min, dias_estimados_max, confianza, metodo, "
                        "version_metodo, publicable) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        [(f.id_solicitud, fecha, f.prioridad_vigente, int(f.posicion_vigente), int(f.total_cola),
                          int(f.dias_estimados_min), int(f.dias_estimados_max), f.confianza, f.metodo,
                          f.version_metodo, bool(f.publicable)) for f in estimaciones.itertuples(index=False)])

    def estimaciones(self, id_solicitud: str | None = None) -> pd.DataFrame:
        if id_solicitud:
            return self.consulta(ESTIMACIONES + " WHERE id_solicitud = %s ORDER BY fecha_calculo", (id_solicitud,))
        return self.consulta(ESTIMACIONES + " ORDER BY fecha_calculo, id_solicitud")
