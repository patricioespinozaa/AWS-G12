"""Chequeos del esquema raw después de cargar. Los conteos esperados salen de la última carga registrada."""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

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
    ultima = conn.execute("SELECT id_carga, fin, filas FROM raw.carga_lote ORDER BY id_carga DESC LIMIT 1").fetchone()
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
