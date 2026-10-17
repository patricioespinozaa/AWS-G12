"""Módulo db: lectura y conversión de los CSV y CLI (siempre); carga, esquemas y reglas del modelo en
PostgreSQL (si hay base de prueba). Modelo en docs/feature/F0001-subida-datos-aws.md y F0002-modelo-datos-canales.md.

Para correr las pruebas de integración, apunta a una base desechable (se borran y recrean los esquemas):
    HLF_TEST_DATABASE_URL=postgresql://postgres@localhost:55432/hlf_test python -m pytest tests/test_db.py
"""
import os
import shutil
from datetime import date, time
from decimal import Decimal

import psycopg
import pytest

from db import carga, conexion, esquema, verificacion
from db.__main__ import main as cli
from priorizacion.config import DATA_DIR


def test_lee_y_convierte_los_csv():
    datos = carga.leer_todo(DATA_DIR)
    assert {t: len(f) for t, f in datos.items()} == {
        "pacientes": 500, "lista_espera": 500, "eventos_clinicos": 786, "mediciones": 2487,
        "agenda_box": 2188, "citaciones": 257, "box": 20}
    p = datos["pacientes"][0]
    assert isinstance(p[2], int) and isinstance(p[7], bool)
    assert all(f[8] is None for f in datos["pacientes"] if f[7] is False)          # vacío → NULL
    assert isinstance(datos["mediciones"][0][3], Decimal)
    assert datos["agenda_box"][0][3] == time(8, 30)
    assert isinstance(datos["lista_espera"][0][7], date)
    asistio = [f for f in datos["citaciones"] if f[5] == "asistio"]
    assert all(f[6] is not None for f in asistio)
    assert all(f[6] is None for f in datos["citaciones"] if f[5] != "asistio")


def test_cabecera_distinta_falla(tmp_path):
    (tmp_path / "pacientes.csv").write_text("id_paciente,edad\nPAC-1,30\n", encoding="utf-8")
    with pytest.raises(carga.ErrorCarga, match="columnas"):
        carga.leer_tabla(carga.TABLAS[0], tmp_path)


def test_booleano_invalido_falla():
    with pytest.raises(ValueError):
        carga.CONVERSORES["bool"]("si")


def test_url_sin_clave_al_mostrar():
    assert conexion.describir("postgresql://u:secreta@h:5432/b") == "postgresql://u:****@h:5432/b"


def test_llaves_de_carga_son_columnas_de_la_tabla():
    for t in carga.TABLAS:
        assert set(t.llave) <= {c for c, _ in t.columnas}, t.nombre


def test_esquemas_en_orden_de_dependencia():
    assert esquema.resolver("todos") == ("raw", "priorizacion", "canal", "consulta")
    assert esquema.dependientes("raw") == ("priorizacion", "canal", "consulta")
    assert esquema.dependientes("priorizacion") == ("canal", "consulta")
    assert esquema.dependientes("canal") == ()                     # consulta no depende de canal
    for nombre in esquema.ESQUEMAS:
        archivos = [a.name for a in (esquema.SQL_DIR / nombre).glob("*.sql")]
        assert any(a.startswith("0") for a in archivos) and any(a.startswith("9") for a in archivos), nombre


def test_borrar_exige_esquema_explicito():
    with pytest.raises(SystemExit):
        cli(["--url", "postgresql://x@localhost/x", "borrar", "--confirmar"])


URL = os.environ.get("HLF_TEST_DATABASE_URL")
integracion = pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")
SIN_PROGRESO = {"progreso": lambda *_: None}


@pytest.fixture
def conn():
    """Base limpia: los tres esquemas creados y raw cargado."""
    with conexion.conectar(URL) as c:
        carga.borrar(c, "todos")
        with c.transaction():
            for nombre in esquema.ESQUEMAS:
                esquema.aplicar(c, nombre)
        carga.cargar(c, DATA_DIR, **SIN_PROGRESO)
        yield c


def _copiar_csv(destino):
    for t in carga.TABLAS:
        if t.archivo:
            shutil.copy(DATA_DIR / t.archivo, destino / t.archivo)


def _propuesta(c, id_solicitud="IC-HLF-00001") -> int:
    return c.execute(
        """INSERT INTO priorizacion.propuesta_prioridad (id_solicitud, origen, fecha_corte, puntaje, puntaje_nivel,
           prioridad_propuesta, prioridad_vigente, cambio, alerta, version_reglas, huella_datos, explicacion_texto,
           fuente_explicacion) VALUES (%s, 'validacion', '2026-10-13', 72, 70, 'alta', 'media', 'sube', true, 'v1',
           'abc', 'Sube por urgencia', 'plantilla') RETURNING id_propuesta""", (id_solicitud,)).fetchone()[0]


def _decision(c, id_propuesta, decision="acepta", final="alta", id_solicitud="IC-HLF-00001"):
    c.execute("""INSERT INTO priorizacion.decision_clinica (id_propuesta, id_solicitud, fecha_corte, prioridad_anterior,
                 prioridad_propuesta, decision, prioridad_final, motivo, id_usuario)
                 VALUES (%s, %s, '2026-10-13', 'media', 'alta', %s, %s, 'Evolución', 'sistema')""",
              (id_propuesta, id_solicitud, decision, final))


@integracion
def test_restaurar_es_repetible_y_verifica(conn):
    with pytest.raises(carga.ErrorCarga, match="--reemplazar"):
        carga.cargar(conn, DATA_DIR, **SIN_PROGRESO)
    res = carga.cargar(conn, DATA_DIR, reemplazar=True, **SIN_PROGRESO)
    assert res["filas"]["mediciones"] == 2487
    assert all(c == {"insertadas": 0, "actualizadas": 0, "borradas": 0} for c in res["cambios"].values())
    chequeos = verificacion.verificar(conn) + verificacion.verificar_app(conn)
    assert all(c.ok for c in chequeos if not c.informativo), [c for c in chequeos if not c.ok]


@integracion
def test_esquemas_idempotentes(conn):
    with conn.transaction():
        for nombre in esquema.ESQUEMAS:
            esquema.aplicar(conn, nombre)
    assert all(c.ok for c in verificacion.verificar_app(conn) if not c.informativo)


@integracion
def test_recarga_conserva_los_datos_de_la_app(conn):
    _decision(conn, _propuesta(conn))
    conn.commit()
    carga.cargar(conn, DATA_DIR, reemplazar=True, **SIN_PROGRESO)       # con TRUNCATE esto fallaba
    assert conn.execute("SELECT count(*) FROM priorizacion.decision_clinica").fetchone()[0] == 1


@integracion
def test_recarga_aplica_los_cambios_del_csv(conn, tmp_path):
    _copiar_csv(tmp_path)
    pac = (tmp_path / "pacientes.csv").read_text(encoding="utf-8").splitlines()
    campos = pac[1].split(",")
    campos[4] = "Comuna Modificada"                                       # columna comuna
    pac[1] = ",".join(campos)
    (tmp_path / "pacientes.csv").write_text("\n".join(pac) + "\n", encoding="utf-8")
    cit = (tmp_path / "citaciones.csv").read_text(encoding="utf-8").splitlines()
    (tmp_path / "citaciones.csv").write_text("\n".join(cit[:-1]) + "\n", encoding="utf-8")
    res = carga.cargar(conn, tmp_path, reemplazar=True, **SIN_PROGRESO)
    assert res["cambios"]["pacientes"] == {"insertadas": 0, "actualizadas": 1, "borradas": 0}
    assert res["cambios"]["citaciones"]["borradas"] == 1
    assert res["filas"]["citaciones"] == 256


@integracion
def test_recarga_no_borra_filas_que_usa_la_app(conn, tmp_path):
    _propuesta(conn)
    conn.commit()
    antes = carga.filas_en_base(conn)
    _copiar_csv(tmp_path)
    lineas = (tmp_path / "lista_espera.csv").read_text(encoding="utf-8").splitlines()
    (tmp_path / "lista_espera.csv").write_text(
        "\n".join(x for x in lineas if ",IC-HLF-00001," not in x) + "\n", encoding="utf-8")
    with pytest.raises(carga.ErrorCarga, match="referencian datos de la app"):
        carga.cargar(conn, tmp_path, reemplazar=True, **SIN_PROGRESO)
    assert carga.filas_en_base(conn) == antes                          # la transacción revirtió todo


@integracion
def test_error_en_un_csv_no_deja_carga_parcial(conn, tmp_path):
    _copiar_csv(tmp_path)
    lineas = (tmp_path / "citaciones.csv").read_text(encoding="utf-8").splitlines()
    lineas.append(lineas[1])                      # id_cita duplicado
    (tmp_path / "citaciones.csv").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    antes = carga.filas_en_base(conn)
    with pytest.raises(Exception):
        carga.cargar(conn, tmp_path, reemplazar=True, **SIN_PROGRESO)
    conn.rollback()
    assert carga.filas_en_base(conn) == antes          # la transacción revirtió todo


@integracion
def test_borrar_no_deja_llaves_foraneas_huerfanas(conn):
    with pytest.raises(carga.ErrorCarga, match="depende"):
        carga.borrar(conn, "raw")
    assert carga.borrar(conn, "canal") == ["canal"]
    assert carga.borrar(conn, "todos") == ["consulta", "priorizacion", "raw"]


@integracion
def test_verificacion_detecta_una_fk_perdida(conn):
    with conn.transaction(force_rollback=True):
        conn.execute("ALTER TABLE priorizacion.cita_agendada DROP CONSTRAINT cita_agendada_id_solicitud_fkey")
        fallas = [c for c in verificacion.verificar_app(conn) if not c.ok]
        assert fallas and "cita_agendada.id_solicitud" in fallas[0].detalle


@integracion
def test_reglas_de_priorizacion(conn):
    pid = _propuesta(conn)
    _decision(conn, pid)
    casos = [
        lambda: _decision(conn, pid, "acepta", "baja"),                          # acepta debe tomar la propuesta
        lambda: _decision(conn, pid, "ajusta", "alta", "IC-HLF-00002"),           # propuesta de otra solicitud
        lambda: conn.execute("UPDATE priorizacion.decision_clinica SET motivo = 'x'"),   # auditoría
    ]
    for caso in casos:
        with pytest.raises(psycopg.Error), conn.transaction():
            caso()
    vigente = conn.execute("SELECT prioridad_vigente FROM priorizacion.v_prioridad_vigente "
                           "WHERE id_solicitud = 'IC-HLF-00001'").fetchone()[0]
    assert vigente == "alta"


@integracion
def test_vistas_del_asistente_exigen_verificacion(conn):
    conn.execute("""INSERT INTO priorizacion.estimacion_espera VALUES ('IC-HLF-00001', current_date, NULL, 'alta',
                    3, 120, 14, 35, 'media', 'throughput_8_semanas', 'v1', true)""")
    conv = conn.execute("INSERT INTO canal.conversacion (canal, direccion, id_externo) "
                        "VALUES ('voz', 'entrante', 'connect-1') RETURNING id_conversacion").fetchone()[0]

    def visibles():
        with conn.transaction():
            conn.execute(f"SET LOCAL canal.id_conversacion = '{conv}'")
            return conn.execute("SELECT (SELECT count(*) FROM canal.v_ia_citas), "
                                "(SELECT count(*) FROM canal.v_ia_estado_solicitud)").fetchone()

    assert visibles() == (0, 0)
    conn.execute("UPDATE canal.conversacion SET id_paciente = 'PAC-HLF-00001', nivel_verificacion = 'basica' "
                 "WHERE id_conversacion = %s", (conv,))
    assert visibles()[1] == 0                                   # básica no alcanza para la prioridad
    conn.execute("UPDATE canal.conversacion SET nivel_verificacion = 'reforzada' WHERE id_conversacion = %s", (conv,))
    assert visibles()[1] == 1
    conn.execute("UPDATE canal.conversacion SET estado = 'finalizada', fin = now() WHERE id_conversacion = %s", (conv,))
    assert visibles() == (0, 0)                                 # conversación cerrada: nada


@integracion
def test_reglas_del_canal(conn):
    casos = [
        "INSERT INTO canal.mensaje_paciente (id_paciente, canal_origen, fecha, tipo, estado) "
        "VALUES ('PAC-HLF-00001', 'voz', '2026-10-13', 'sintoma_alarma', 'registrado')",
        "INSERT INTO canal.evidencia_externa (id_paciente, canal_origen, fecha_examen, tipo_medicion, valor, "
        "fecha_recepcion, estado) VALUES ('PAC-HLF-00001', 'web', '2026-10-01', 'HbA1c', 8, '2026-10-02', 'validada')",
        "INSERT INTO canal.conversacion (canal, direccion, id_externo, nivel_verificacion) "
        "VALUES ('voz', 'entrante', 'x', 'basica')",
    ]
    for sql in casos:
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            conn.execute(sql)


# -- Reloj de la demo (flujo D) -----------------------------------------------------------------------
def _reloj(c, fecha):
    c.execute("UPDATE priorizacion.reloj SET modo = 'demo', fecha_demo = %s, actualizado_por = 'sistema'", (fecha,))


@integracion
def test_reloj_real_y_demo(conn):
    assert conn.execute("SELECT priorizacion.fecha_corte() = current_date").fetchone()[0]
    assert conn.execute("SELECT priorizacion.avanzar_reloj()").fetchone()[0] is None      # modo real: no avanza
    _reloj(conn, date(2026, 6, 1))
    assert conn.execute("SELECT priorizacion.avanzar_reloj()").fetchone()[0] == date(2026, 6, 2)
    assert conn.execute("SELECT priorizacion.avanzar_reloj(7)").fetchone()[0] == date(2026, 6, 9)
    assert conn.execute("SELECT priorizacion.fecha_corte()").fetchone()[0] == date(2026, 6, 9)
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute("UPDATE priorizacion.reloj SET fecha_demo = NULL")
    with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
        conn.execute("INSERT INTO priorizacion.reloj (id, modo, actualizado_por) VALUES (1, 'real', 'sistema')")


@integracion
def test_vistas_del_asistente_respetan_la_fecha_de_corte(conn):
    pac, sol = "PAC-HLF-00001", "IC-HLF-00001"
    fechas_ev = [r[0] for r in conn.execute(
        "SELECT fecha_evento FROM raw.eventos_clinicos WHERE id_paciente = %s ORDER BY 1", (pac,)).fetchall()]
    assert len(fechas_ev) >= 2
    corte = fechas_ev[0]                                         # justo en el primer evento
    conn.execute("""INSERT INTO priorizacion.estimacion_espera VALUES
                    (%s, %s, NULL, 'alta', 9, 120, 30, 60, 'media', 'm', 'v1', true),
                    (%s, %s, NULL, 'alta', 3, 120, 10, 20, 'media', 'm', 'v1', true)""",
                 (sol, corte, sol, fechas_ev[-1]))
    conv = conn.execute("""INSERT INTO canal.conversacion (canal, direccion, id_externo, id_paciente, nivel_verificacion)
                           VALUES ('whatsapp', 'entrante', 'wa-1', %s, 'reforzada') RETURNING id_conversacion""",
                        (pac,)).fetchone()[0]
    _reloj(conn, corte)

    def leer(sql):
        with conn.transaction():
            conn.execute(f"SET LOCAL canal.id_conversacion = '{conv}'")
            return conn.execute(sql).fetchall()

    eventos = leer("SELECT fecha FROM canal.v_ia_registros WHERE tipo_registro = 'evento'")
    assert eventos and all(f <= corte for (f,) in eventos)        # nada del "futuro"
    assert leer("SELECT posicion_vigente, fecha_corte FROM canal.v_ia_estado_solicitud") == [(9, corte)]
    futuras = leer("SELECT estado, temporalidad FROM canal.v_ia_citas WHERE fecha > priorizacion.fecha_corte()")
    assert all(f == ("programada", "proxima") for f in futuras)  # resultado aún desconocido a esa fecha
    _reloj(conn, fechas_ev[-1])
    assert leer("SELECT posicion_vigente FROM canal.v_ia_estado_solicitud") == [(3,)]   # avanzó en la cola


@integracion
def test_asistente_usa_la_fecha_de_corte_sin_leer_priorizacion(conn):
    with conexion.conectar(URL) as admin:
        admin.execute("SET client_min_messages = warning")
        for nombre in esquema.ESQUEMAS:
            esquema.aplicar_permisos(admin, nombre)
        admin.commit()
    conv = conn.execute("""INSERT INTO canal.conversacion (canal, direccion, id_externo, id_paciente, nivel_verificacion)
                           VALUES ('voz', 'entrante', 'c-1', 'PAC-HLF-00001', 'basica') RETURNING id_conversacion""").fetchone()[0]
    with conn.transaction(force_rollback=True):
        conn.execute("SET LOCAL ROLE hlf_asistente_ia")
        conn.execute(f"SET LOCAL canal.id_conversacion = '{conv}'")
        assert conn.execute("SELECT count(*) FROM canal.v_ia_citas").fetchone()[0] >= 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT * FROM priorizacion.reloj")


# -- Consulta del equipo clínico (flujo A) ------------------------------------------------------------
def _ingesta(c, audiencia="equipo_clinico", kb="KB-EQUIPO"):
    return c.execute("""INSERT INTO consulta.ingesta_kb (knowledge_base_id, data_source_id, audiencia, fecha_corte,
                        version_plantilla) VALUES (%s, 'DS-1', %s, '2026-10-13', 'perfil-v1') RETURNING id_ingesta""",
                     (kb, audiencia)).fetchone()[0]


def _documento(c, ing, tipo="perfil_paciente", clave="PAC-HLF-00001", pac="PAC-HLF-00001"):
    return c.execute("""INSERT INTO consulta.documento_kb (id_ingesta, tipo, clave, id_paciente, s3_uri, sha256, metadatos)
                        VALUES (%s, %s, %s, %s, %s, repeat('a', 64), '{"especialidad": "Cardiología"}')
                        RETURNING id_documento""",
                     (ing, tipo, clave, pac, f"s3://hlf/kb/{tipo}/{clave}.md")).fetchone()[0]


@integracion
def test_kb_del_paciente_no_admite_perfiles(conn):
    ing = _ingesta(conn, "paciente", "KB-PACIENTE")
    _documento(conn, ing, "faq_paciente", "que-llevar", None)
    with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
        _documento(conn, ing)                                     # un perfil nunca va a la KB del paciente
    with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
        _ingesta(conn, "paciente", "KB-PACIENTE")                 # una sola ingesta en curso por KB


@integracion
def test_pregunta_trazable(conn):
    ing = _ingesta(conn)
    doc = _documento(conn, ing)
    conn.execute("""UPDATE consulta.ingesta_kb SET ingestion_job_id = 'job-1', estado = 'completa', fin = now(),
                    n_documentos = 1 WHERE id_ingesta = %s""", (ing,))
    pid = conn.execute("""INSERT INTO consulta.pregunta (id_usuario, texto, ruta, id_ingesta, respuesta, modelo_ia,
                          version_prompt) VALUES ('sistema', '¿Cómo evolucionó el paciente 1?', 'texto', %s,
                          'Tuvo una visita a urgencia…', 'claude', 'p1') RETURNING id_pregunta""", (ing,)).fetchone()[0]
    conn.execute("INSERT INTO consulta.fuente_respuesta VALUES (%s, 0, %s, 'visita_urgencia 2026-05-02', 0.91)", (pid, doc))
    assert conn.execute("SELECT id_ingesta FROM consulta.v_kb_vigente").fetchone()[0] == ing
    casos = [
        "INSERT INTO consulta.pregunta (id_usuario, texto, ruta, respuesta, modelo_ia, version_prompt) "
        "VALUES ('sistema', '¿Cuántos?', 'conteo', '12', 'claude', 'p1')",                # conteo sin SQL
        "INSERT INTO consulta.pregunta (id_usuario, texto, ruta, respuesta, modelo_ia, version_prompt) "
        "VALUES ('sistema', '¿Qué pasó?', 'texto', 'x', 'claude', 'p1')",                 # texto sin KB
        "UPDATE consulta.pregunta SET respuesta = 'otra'",                                 # auditoría
    ]
    for sql in casos:
        with pytest.raises(psycopg.Error), conn.transaction():
            conn.execute(sql)
