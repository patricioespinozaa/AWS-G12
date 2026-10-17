"""Chequeos de la base después de restaurar.

- raw: conteos contra la última carga registrada, huérfanos y propiedades conocidas del dataset.
- priorizacion, canal y consulta: que estén completos (tablas, vistas, llaves foráneas, triggers de auditoría y
  catálogos base), según docs/feature/F0002-modelo-datos-canales.md y F0003-flujos-aws-datos.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

from . import esquema
from .carga import TABLAS


@dataclass
class Chequeo:
    nombre: str
    ok: bool
    detalle: str
    informativo: bool = False     # no falla la verificación; documenta una propiedad conocida del dataset


HUERFANOS = {
    "lista_espera.id_paciente → pacientes": "SELECT count(*) FROM raw.lista_espera l LEFT JOIN raw.pacientes p USING (id_paciente) WHERE p.id_paciente IS NULL",
    "eventos_clinicos.id_paciente → pacientes": "SELECT count(*) FROM raw.eventos_clinicos e LEFT JOIN raw.pacientes p USING (id_paciente) WHERE p.id_paciente IS NULL",
    "mediciones.id_paciente → pacientes": "SELECT count(*) FROM raw.mediciones m LEFT JOIN raw.pacientes p USING (id_paciente) WHERE p.id_paciente IS NULL",
    "citaciones.id_paciente → pacientes": "SELECT count(*) FROM raw.citaciones c LEFT JOIN raw.pacientes p USING (id_paciente) WHERE p.id_paciente IS NULL",
    "agenda_box.id_box → box": "SELECT count(*) FROM raw.agenda_box a LEFT JOIN raw.box b USING (id_box) WHERE b.id_box IS NULL",
    "citaciones.id_box → box": "SELECT count(*) FROM raw.citaciones c LEFT JOIN raw.box b USING (id_box) WHERE b.id_box IS NULL",
}

INFORMATIVOS = {
    "Pacientes con eventos": "SELECT count(DISTINCT id_paciente) FROM raw.eventos_clinicos",
    "Pacientes con mediciones": "SELECT count(DISTINCT id_paciente) FROM raw.mediciones",
    "Pacientes citados": "SELECT count(DISTINCT id_paciente) FROM raw.citaciones",
    "Citas sin bloque de agenda ese día (no cruzar por fecha)":
        "SELECT count(*) FROM raw.citaciones c LEFT JOIN raw.agenda_box a "
        "ON a.id_box = c.id_box AND a.fecha = c.fecha_cita WHERE a.id_box IS NULL",
}


def verificar(conn: psycopg.Connection) -> list[Chequeo]:
    chequeos: list[Chequeo] = []
    existe = conn.execute("SELECT to_regclass('raw.carga_lote') IS NOT NULL").fetchone()[0]
    if not existe:
        return [Chequeo("Esquema raw", False, "no existe: ejecuta python -m db restaurar")]
    tiene_versiones = conn.execute("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'raw' "
                                   "AND table_name = 'carga_lote' AND column_name = 'version')").fetchone()[0]
    # La última versión APLICADA guarda los totales de raw tras aplicarse (las incrementales suman, F0005)
    ultima = conn.execute("SELECT id_carga, fin, filas FROM raw.carga_lote "
                          + ("WHERE estado = 'aplicada' ORDER BY version DESC" if tiene_versiones else "ORDER BY id_carga DESC")
                          + " LIMIT 1").fetchone()
    if not ultima:
        return [Chequeo("Carga registrada", False, "el esquema existe pero no hay cargas en raw.carga_lote")]
    id_carga, fin, esperadas = ultima
    chequeos.append(Chequeo("Última carga", True, f"#{id_carga} el {fin:%Y-%m-%d %H:%M %Z}", informativo=True))
    for t in TABLAS:
        n = conn.execute(f"SELECT count(*) FROM raw.{t.nombre}").fetchone()[0]
        chequeos.append(Chequeo(f"Filas raw.{t.nombre}", n == esperadas.get(t.nombre), f"{n} (esperadas {esperadas.get(t.nombre)})"))
    for nombre, sql in HUERFANOS.items():
        n = conn.execute(sql).fetchone()[0]
        chequeos.append(Chequeo(f"Huérfanos {nombre}", n == 0, str(n)))
    posteriores = conn.execute(
        "SELECT count(*) FROM raw.eventos_clinicos e JOIN raw.pacientes p USING (id_paciente) "
        "WHERE p.fecha_defuncion IS NOT NULL AND e.fecha_evento > p.fecha_defuncion").fetchone()[0]
    chequeos.append(Chequeo("Eventos posteriores a la defunción", posteriores == 0, str(posteriores)))
    for nombre, sql in INFORMATIVOS.items():
        chequeos.append(Chequeo(nombre, True, str(conn.execute(sql).fetchone()[0]), informativo=True))
    return chequeos


# Estructura esperada de los esquemas de la app (docs/feature/F0002-modelo-datos-canales.md)
ESTRUCTURA = {
    "priorizacion": {
        "tablas": ("usuario", "reloj", "estado_app", "corrida_nocturna", "serie_nocturna", "propuesta_prioridad", "factor_propuesta",
                   "decision_clinica", "cita_agendada", "estimacion_espera"),
        "vistas": ("v_prioridad_vigente",),
        "solo_insercion": ("decision_clinica",),
    },
    "canal": {
        "tablas": ("intencion", "contacto_paciente", "consentimiento", "conversacion", "verificacion_identidad",
                   "turno", "divulgacion", "derivacion_humana", "mensaje_paciente", "evidencia_externa",
                   "notificacion"),
        "vistas": ("v_consentimiento_vigente", "v_ia_estado_solicitud", "v_ia_citas", "v_ia_registros"),
        "solo_insercion": ("consentimiento", "turno", "divulgacion"),
    },
    "consulta": {
        "tablas": ("ingesta_kb", "documento_kb", "pregunta", "fuente_respuesta"),
        "vistas": ("v_kb_vigente",),
        "solo_insercion": ("pregunta", "fuente_respuesta"),
    },
}
# Columnas que siempre deben tener llave foránea. Un DROP SCHEMA raw CASCADE las elimina sin avisar.
COLUMNAS_CON_FK = ("id_paciente", "id_solicitud", "id_box", "id_propuesta", "id_conversacion", "id_contacto",
                   "id_corrida", "id_usuario", "id_cita_agendada", "revisado_por", "registrado_por",
                   "agendado_por", "asignado_a", "creada_por", "intencion", "actualizado_por",
                   "id_ingesta", "id_documento", "id_pregunta")
CATALOGOS = {
    "Usuarios de sistema (sistema, asistente_ia)":
        ("SELECT count(*) FROM priorizacion.usuario WHERE id_usuario IN ('sistema', 'asistente_ia')", 2),
    "Intenciones del asistente": ("SELECT count(*) FROM canal.intencion", 10),
    "Reloj (fila única)": ("SELECT count(*) FROM priorizacion.reloj", 1),
    "Usuaria administradora (F0005)": ("SELECT count(*) FROM priorizacion.usuario WHERE id_usuario = 'administradora' "
                                       "AND rol = 'administracion' AND activo", 1),
    "Contador de versión de la app": ("SELECT count(*) FROM priorizacion.estado_app", 1),
    "Historial de cambios de raw (F0005)": ("SELECT count(*) FROM information_schema.tables "
                                            "WHERE table_schema = 'raw' AND table_name = 'cambio_fila'", 1),
}
INFORMATIVOS_APP = {
    "Propuestas": "SELECT count(*) FROM priorizacion.propuesta_prioridad",
    "Decisiones clínicas": "SELECT count(*) FROM priorizacion.decision_clinica",
    "Citas agendadas": "SELECT count(*) FROM priorizacion.cita_agendada",
    "Conversaciones (WhatsApp y voz)": "SELECT count(*) FROM canal.conversacion",
    "Preguntas del equipo clínico": "SELECT count(*) FROM consulta.pregunta",
    "Fecha de corte (reloj)": "SELECT modo || ' · ' || priorizacion.fecha_corte() FROM priorizacion.reloj",
}


def _relaciones(conn: psycopg.Connection, nombre: str) -> dict[str, str]:
    return dict(conn.execute(
        "SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'v') AND NOT c.relispartition", (nombre,)).fetchall())


def verificar_app(conn: psycopg.Connection) -> list[Chequeo]:
    """Revisa que priorizacion, canal y consulta estén completos y con sus protecciones."""
    chequeos: list[Chequeo] = []
    presentes = esquema.existentes(conn)
    for nombre, esperado in ESTRUCTURA.items():
        if nombre not in presentes:
            chequeos.append(Chequeo(f"Esquema {nombre}", False, "no existe: ejecuta python -m db esquema"))
            continue
        rel = _relaciones(conn, nombre)
        faltan = [t for t in esperado["tablas"] if rel.get(t) not in ("r", "p")]
        faltan += [v for v in esperado["vistas"] if rel.get(v) != "v"]
        chequeos.append(Chequeo(f"Tablas y vistas de {nombre}", not faltan,
                                f"faltan {', '.join(faltan)}" if faltan else
                                f"{len(esperado['tablas'])} tablas, {len(esperado['vistas'])} vistas"))
        sin_fk = [f"{t}.{c}" for t, c in conn.execute(
            """SELECT c.relname, a.attname
               FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = %s AND c.relkind IN ('r', 'p') AND NOT c.relispartition
                 AND a.attnum > 0 AND NOT a.attisdropped AND a.attname = ANY(%s)
                 AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'f'
                                 AND a.attnum = ANY(k.conkey))
                 AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p'
                                 AND k.conkey = ARRAY[a.attnum])
               ORDER BY 1, 2""", (nombre, list(COLUMNAS_CON_FK))).fetchall()]
        chequeos.append(Chequeo(f"Llaves foráneas de {nombre}", not sin_fk,
                                f"sin FK: {', '.join(sin_fk)} (¿se borró un esquema con CASCADE?)" if sin_fk else "completas"))
        sin_trigger = [t for t in esperado["solo_insercion"] if not conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = to_regclass(%s) AND NOT tgisinternal "
            "AND tgfoid = 'priorizacion.solo_insercion'::regproc)", (f"{nombre}.{t}",)).fetchone()[0]]
        chequeos.append(Chequeo(f"Auditoría solo inserción en {nombre}", not sin_trigger,
                                f"sin trigger: {', '.join(sin_trigger)}" if sin_trigger else
                                ", ".join(esperado["solo_insercion"])))
    if set(ESTRUCTURA) <= presentes:
        for nombre, (sql, minimo) in CATALOGOS.items():
            n = conn.execute(sql).fetchone()[0]
            chequeos.append(Chequeo(nombre, n >= minimo, f"{n} (mínimo {minimo})"))
        for nombre, sql in INFORMATIVOS_APP.items():
            chequeos.append(Chequeo(nombre, True, str(conn.execute(sql).fetchone()[0]), informativo=True))
    return chequeos
