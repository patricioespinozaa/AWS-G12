"""Carga de los CSV del HLF al esquema raw de PostgreSQL.

Todo ocurre en una sola transacción: si algo falla (archivo faltante, tipo inválido, llave duplicada,
restricción violada), la base queda como estaba. Se puede repetir cuantas veces haga falta con
--reemplazar, por ejemplo si la base se borra al final del día.

Tres modos, todos versionados en raw.carga_lote y con el valor anterior de cada fila modificada en
raw.cambio_fila (docs/feature/F0005):
- inicial: primera carga.
- reconstruccion (--reemplazar): deja raw IGUAL a la historia completa; borra lo que no venga en los CSV.
  Los esquemas de la app referencian raw, así que si una fila que se borraría está en uso, falla sin borrar.
- incremental (vista_previa + aplicar_incremental): suma la exportación de un periodo nuevo. Inserta lo nuevo,
  actualiza lo que cambió y NUNCA borra: un paciente con datos previos conserva su historia.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path

import psycopg

from . import esquema


class ErrorCarga(RuntimeError):
    pass


def _texto(v: str):
    return v if v != "" else None


def _entero(v: str):
    return int(Decimal(v)) if v != "" else None


def _booleano(v: str):
    v = v.strip().lower()
    if v not in ("true", "false"):
        raise ValueError(f"booleano inválido: {v!r}")
    return v == "true"


def _fecha(v: str):
    return date.fromisoformat(v) if v != "" else None


def _hora(v: str):
    return time.fromisoformat(v) if v != "" else None


def _numero(v: str):
    return Decimal(v) if v != "" else None


CONVERSORES = {"text": _texto, "int": _entero, "bool": _booleano, "date": _fecha, "time": _hora, "numeric": _numero}


@dataclass(frozen=True)
class Tabla:
    nombre: str
    archivo: str | None          # None = tabla derivada
    columnas: tuple[tuple[str, str], ...]
    llave: tuple[str, ...]       # PK, igual que en el DDL


# Orden de carga respetando las llaves foráneas. Debe coincidir con db/sql/raw/001_esquema_raw.sql
TABLAS: tuple[Tabla, ...] = (
    Tabla("pacientes", "pacientes.csv", (
        ("id_paciente", "text"), ("nombre_fantasia", "text"), ("edad", "int"), ("sexo", "text"),
        ("comuna", "text"), ("prevision", "text"), ("nivel_socioeconomico", "text"),
        ("fallecido", "bool"), ("fecha_defuncion", "date")), ("id_paciente",)),
    Tabla("lista_espera", "lista_espera.csv", (
        ("id_paciente", "text"), ("id_solicitud", "text"), ("especialidad", "text"), ("sub_especialidad", "text"),
        ("diagnostico_cie10", "text"), ("diagnostico_texto", "text"), ("prioridad_inicial", "text"),
        ("fecha_ingreso_lista", "date"), ("origen_derivacion", "text"), ("estado", "text")), ("id_solicitud",)),
    Tabla("eventos_clinicos", "eventos_clinicos.csv", (
        ("id_paciente", "text"), ("id_evento", "text"), ("fecha_evento", "date"), ("tipo_evento", "text"),
        ("subtipo", "text"), ("severidad", "text"), ("detalle", "text")), ("id_evento",)),
    Tabla("mediciones", "mediciones.csv", (
        ("id_paciente", "text"), ("fecha_medicion", "date"), ("tipo_medicion", "text"), ("valor", "numeric"),
        ("unidad", "text"), ("fuera_de_rango", "bool")), ("id_paciente", "fecha_medicion", "tipo_medicion")),
    Tabla("box", None, (("id_box", "text"),), ("id_box",)),
    Tabla("agenda_box", "agenda_box.csv", (
        ("id_box", "text"), ("fecha", "date"), ("especialidad", "text"), ("bloque_inicio", "time"),
        ("bloque_fin", "time"), ("capacidad_cupos", "int"), ("cupos_usados", "int"), ("minutos_sobretiempo", "int")),
        ("id_box", "fecha")),
    Tabla("citaciones", "citaciones.csv", (
        ("id_paciente", "text"), ("id_cita", "text"), ("id_box", "text"), ("fecha_cita", "date"),
        ("especialidad", "text"), ("estado_cita", "text"), ("minutos_atencion_real", "int")), ("id_cita",)),
)


def leer_tabla(tabla: Tabla, data_dir: Path) -> list[tuple]:
    """Lee un CSV, valida la cabecera y convierte cada valor al tipo de PostgreSQL."""
    ruta = data_dir / tabla.archivo
    if not ruta.exists():
        raise ErrorCarga(f"No existe {ruta}")
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        esperadas = [c for c, _ in tabla.columnas]
        if sorted(lector.fieldnames or []) != sorted(esperadas):
            raise ErrorCarga(f"{tabla.archivo}: columnas {lector.fieldnames}, se esperaban {esperadas}")
        filas = []
        for n, registro in enumerate(lector, start=2):
            try:
                filas.append(tuple(CONVERSORES[tipo](registro[col].strip()) for col, tipo in tabla.columnas))
            except (ValueError, ArithmeticError) as e:
                raise ErrorCarga(f"{tabla.archivo}, línea {n}: {e}") from e
    return filas


def leer_todo(data_dir: Path) -> dict[str, list[tuple]]:
    datos = {t.nombre: leer_tabla(t, data_dir) for t in TABLAS if t.archivo}
    # box: todos los id_box de la agenda y de las citas
    boxes = {f[0] for f in datos["agenda_box"]} | {f[2] for f in datos["citaciones"]}
    datos["box"] = [(b,) for b in sorted(boxes)]
    return datos


def huellas(data_dir: Path) -> dict[str, str]:
    return {t.archivo: hashlib.sha256((data_dir / t.archivo).read_bytes()).hexdigest() for t in TABLAS if t.archivo}


def filas_en_base(conn: psycopg.Connection) -> dict[str, int]:
    existentes = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'raw'").fetchall()}
    return {t.nombre: conn.execute(f"SELECT count(*) FROM raw.{t.nombre}").fetchone()[0]
            for t in TABLAS if t.nombre in existentes}


def _copiar(conn: psycopg.Connection, destino: str, t: Tabla, filas: list[tuple]):
    cols = ", ".join(c for c, _ in t.columnas)
    with conn.cursor().copy(f"COPY {destino} ({cols}) FROM STDIN") as copia:
        for fila in filas:
            copia.write_row(fila)


def _preparar_staging(conn: psycopg.Connection, t: Tabla, filas: list[tuple]) -> str:
    stg = f"stg_{t.nombre}"
    conn.execute(f"DROP TABLE IF EXISTS {stg}")
    conn.execute(f"CREATE TEMP TABLE {stg} (LIKE raw.{t.nombre} INCLUDING DEFAULTS) ON COMMIT DROP")
    _copiar(conn, stg, t, filas)
    return stg


def _combinar(conn: psycopg.Connection, t: Tabla, filas: list[tuple], id_carga: int) -> dict:
    """Inserta lo nuevo y actualiza lo que cambió (por llave primaria). Nunca borra.

    Antes de actualizar guarda el valor anterior en raw.cambio_fila. Devuelve los conteos y los pacientes
    afectados (los de filas nuevas o modificadas).
    """
    stg = _preparar_staging(conn, t, filas)
    cols = [c for c, _ in t.columnas]
    resto = [c for c in cols if c not in t.llave]
    lista, llave = ", ".join(cols), ", ".join(t.llave)
    igual = " AND ".join(f"r.{c} = s.{c}" for c in t.llave)
    sin_procedencia = "- 'id_carga_alta' - 'id_carga_modificacion'"
    if resto:
        distinto = f"({', '.join(f'r.{c}' for c in resto)}) IS DISTINCT FROM ({', '.join(f's.{c}' for c in resto)})"
        conn.execute(
            f"INSERT INTO raw.cambio_fila (id_carga, tabla, llave, antes, despues) "
            f"SELECT %s, %s, jsonb_build_object({', '.join(f'{chr(39)}{c}{chr(39)}, r.{c}' for c in t.llave)}), "
            f"to_jsonb(r) {sin_procedencia}, to_jsonb(s) {sin_procedencia} "
            f"FROM raw.{t.nombre} r JOIN {stg} s ON {igual} WHERE {distinto}", (id_carga, t.nombre))
        actualizar = (f"DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in resto)}, "
                      f"id_carga_modificacion = EXCLUDED.id_carga_modificacion "
                      f"WHERE ({', '.join(f'raw.{t.nombre}.{c}' for c in resto)}) "
                      f"IS DISTINCT FROM ({', '.join(f'EXCLUDED.{c}' for c in resto)})")
    else:
        actualizar = "DO NOTHING"
    paciente = ", id_paciente" if "id_paciente" in cols else ", NULL::text"
    filas_db = conn.execute(
        f"INSERT INTO raw.{t.nombre} ({lista}, id_carga_alta, id_carga_modificacion) "
        f"SELECT {lista}, %s, %s FROM {stg} ON CONFLICT ({llave}) {actualizar} "
        f"RETURNING (xmax = 0){paciente}", (id_carga, id_carga)).fetchall()
    nuevas = sum(1 for nueva, _ in filas_db if nueva)
    return {"filas": len(filas), "nuevas": nuevas, "modificadas": len(filas_db) - nuevas,
            "sin_cambio": len(filas) - len(filas_db),
            "pacientes": {p for _, p in filas_db if p}, "pacientes_nuevos":
                {p for nueva, p in filas_db if nueva and p} if t.nombre == "pacientes" else set()}


def _borrar_ausentes(conn: psycopg.Connection, t: Tabla) -> int:
    """Solo para reconstruir: borra de raw las filas que ya no están en los CSV. Falla si la app las referencia."""
    igual = " AND ".join(f"s.{c} = r.{c}" for c in t.llave)
    try:
        with conn.transaction():          # savepoint, para traducir el error a uno legible
            return conn.execute(f"DELETE FROM raw.{t.nombre} r WHERE NOT EXISTS "
                                f"(SELECT 1 FROM stg_{t.nombre} s WHERE {igual})").rowcount
    except psycopg.errors.ForeignKeyViolation as e:
        raise ErrorCarga(
            f"raw.{t.nombre}: hay filas que ya no están en los CSV pero las referencian datos de la app "
            f"({e.diag.message_detail or e}). No se borró nada: revisa el CSV o esos datos.") from e


def _bloquear_cargas(conn: psycopg.Connection):
    """Dos cargas nunca se aplican a la vez (se serializan dentro de la transacción)."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('hlf_carga_raw'))")


def _nueva_carga(conn: psycopg.Connection, modo: str, origen: str, cargado_por: str, archivos: dict,
                 periodo: tuple[date | None, date | None] = (None, None), uri: str | None = None) -> int:
    return conn.execute(
        "INSERT INTO raw.carga_lote (inicio, origen, filas, archivos, modo, estado, cargado_por, periodo_desde, "
        "periodo_hasta, uri_archivos) VALUES (now(), %s, '{}'::jsonb, %s, %s, 'validando', %s, %s, %s, %s) "
        "RETURNING id_carga",
        (origen, json.dumps(archivos), modo, cargado_por, periodo[0], periodo[1], uri)).fetchone()[0]


def _aplicar_version(conn: psycopg.Connection, id_carga: int, filas: dict, resumen: dict,
                     advertencias: list | None = None) -> int:
    version = conn.execute("SELECT coalesce(max(version), 0) + 1 FROM raw.carga_lote").fetchone()[0]
    # Fecha de corte de la versión (F0006): el fin del periodo declarado o, si no hay, la última fecha con datos
    conn.execute("UPDATE raw.carga_lote SET estado = 'aplicada', version = %s, fin = now(), filas = %s, "
                 "resumen = %s, advertencias = %s, fecha_corte = coalesce(periodo_hasta, %s) WHERE id_carga = %s",
                 (version, json.dumps(filas), json.dumps(resumen), json.dumps(advertencias or []),
                  ultima_fecha_con_datos(conn), id_carga))
    return version


def ultima_fecha_con_datos(conn: psycopg.Connection) -> date | None:
    return conn.execute(
        "SELECT max(f) FROM (SELECT max(fecha_evento) AS f FROM raw.eventos_clinicos "
        "UNION ALL SELECT max(fecha_medicion) FROM raw.mediciones UNION ALL SELECT max(fecha_cita) FROM raw.citaciones "
        "UNION ALL SELECT max(fecha) FROM raw.agenda_box UNION ALL SELECT max(fecha_ingreso_lista) FROM raw.lista_espera) x"
    ).fetchone()[0]


def cargar(conn: psycopg.Connection, data_dir: Path, reemplazar: bool = False, progreso=print,
           cargado_por: str = "sistema") -> dict:
    """Carga completa: crea el esquema raw si falta y lo deja IGUAL a los CSV (historia completa).

    Primera carga = versión `inicial`. Con datos previos y reemplazar=True = `reconstruccion`: inserta lo
    nuevo, actualiza lo que cambió (guardando el valor anterior) y BORRA lo que no está en los CSV.
    Para sumar una exportación de un periodo nuevo sin borrar nada, usar vista_previa + aplicar_incremental.
    """
    inicio = datetime.now(timezone.utc)
    progreso(f"Leyendo CSV desde {data_dir}")
    datos = leer_todo(data_dir)
    cambios: dict[str, dict[str, int]] = {}
    with conn.transaction():
        esquema.aplicar(conn, "raw")
        previas = filas_en_base(conn)
        hay_datos = any(previas.values())
        if hay_datos and not reemplazar:
            raise ErrorCarga(f"El esquema raw ya tiene datos {previas}. Usa --reemplazar para reconstruirlo, "
                             "o --incremental para sumar un periodo nuevo sin borrar nada.")
        _bloquear_cargas(conn)
        modo = "reconstruccion" if hay_datos else "inicial"
        id_carga = _nueva_carga(conn, modo, str(data_dir), cargado_por, huellas(data_dir))
        if hay_datos:
            progreso("Reconstruyendo raw desde la historia completa (borra lo que no esté en los CSV)")
        for t in TABLAS:                              # padres primero
            r = _combinar(conn, t, datos[t.nombre], id_carga)
            cambios[t.nombre] = {"insertadas": r["nuevas"], "actualizadas": r["modificadas"], "borradas": 0}
        if hay_datos:
            for t in reversed(TABLAS):                # hijos primero
                cambios[t.nombre]["borradas"] = _borrar_ausentes(conn, t)
        for t in TABLAS:
            c = cambios[t.nombre]
            detalle = f"  (+{c['insertadas']} ~{c['actualizadas']} -{c['borradas']})" if hay_datos else ""
            progreso(f"  raw.{t.nombre:<17} {len(datos[t.nombre]):>6} filas{detalle}")
        cargadas = filas_en_base(conn)
        esperadas = {t.nombre: len(datos[t.nombre]) for t in TABLAS}
        if cargadas != esperadas:
            raise ErrorCarga(f"Conteos no coinciden: base {cargadas} vs CSV {esperadas}")
        version = _aplicar_version(conn, id_carga, cargadas, cambios)
    return {"filas": cargadas, "cambios": cambios, "id_carga": id_carga, "version": version,
            "segundos": round((datetime.now(timezone.utc) - inicio).total_seconds(), 1)}


# -- Cargas incrementales (exportaciones por periodo) -------------------------------------------------
TABLAS_POR_ARCHIVO = {t.archivo: t for t in TABLAS if t.archivo}
COLUMNA_FECHA = {"eventos_clinicos": "fecha_evento", "mediciones": "fecha_medicion",
                 "citaciones": "fecha_cita", "agenda_box": "fecha"}
REFERENCIAS_PACIENTE = ("lista_espera", "eventos_clinicos", "mediciones", "citaciones")
MAX_PROBLEMAS_POR_ARCHIVO = 20


@dataclass
class Problema:
    archivo: str
    linea: int | None
    mensaje: str

    def a_dict(self) -> dict:
        return {"archivo": self.archivo, "linea": self.linea, "mensaje": self.mensaje}


def leer_exportacion(data_dir: Path) -> tuple[dict[str, list[tuple]], list[Problema]]:
    """Lee los CSV que traiga una exportación por periodo (todos o algunos de los 6).

    No se detiene en el primer error: devuelve todos los problemas de lectura y las llaves duplicadas, con
    archivo y línea, para mostrarlos juntos en la vista previa.
    """
    datos: dict[str, list[tuple]] = {}
    problemas: list[Problema] = []
    presentes = sorted(p.name for p in Path(data_dir).glob("*.csv"))
    for nombre in presentes:
        if nombre not in TABLAS_POR_ARCHIVO:
            problemas.append(Problema(nombre, None, f"Archivo desconocido. Se esperan: "
                                                    f"{', '.join(sorted(TABLAS_POR_ARCHIVO))}"))
    if not any(n in TABLAS_POR_ARCHIVO for n in presentes):
        problemas.append(Problema("—", None, "La carga no trae ninguno de los archivos del dataset"))
    for nombre in presentes:
        t = TABLAS_POR_ARCHIVO.get(nombre)
        if t is None:
            continue
        try:
            filas = leer_tabla(t, data_dir)
        except ErrorCarga as e:
            texto = str(e)
            m = re.search(r"línea (\d+)", texto)
            problemas.append(Problema(nombre, int(m.group(1)) if m else None, texto.split(": ", 1)[-1]))
            continue
        posiciones = [i for i, (c, _) in enumerate(t.columnas) if c in t.llave]
        vistas: dict[tuple, int] = {}
        repetidas = 0
        for i, fila in enumerate(filas, start=2):
            k = tuple(fila[j] for j in posiciones)
            if k in vistas:
                repetidas += 1
                if repetidas <= MAX_PROBLEMAS_POR_ARCHIVO:
                    problemas.append(Problema(nombre, i, f"Llave repetida {_llave_texto(t, k)} "
                                                         f"(ya está en la línea {vistas[k]})"))
            else:
                vistas[k] = i
        datos[t.nombre] = filas
    if "agenda_box" in datos or "citaciones" in datos:
        boxes = {f[0] for f in datos.get("agenda_box", [])} | {f[2] for f in datos.get("citaciones", [])}
        datos["box"] = [(b,) for b in sorted(boxes)]
    return datos, problemas


def _llave_texto(t: Tabla, k: tuple) -> str:
    return ", ".join(f"{c}={v}" for c, v in zip(t.llave, k))


def _validar_referencias(conn: psycopg.Connection, datos: dict[str, list[tuple]]) -> list[Problema]:
    """Integridad contra lo existente MÁS lo nuevo: un evento puede ser de un paciente de una carga anterior."""
    existentes = {r[0] for r in conn.execute("SELECT id_paciente FROM raw.pacientes").fetchall()}
    nuevos = {f[0] for f in datos.get("pacientes", [])}
    conocidos = existentes | nuevos
    problemas = []
    for nombre in REFERENCIAS_PACIENTE:
        if nombre not in datos:
            continue
        t = next(x for x in TABLAS if x.nombre == nombre)
        j = [c for c, _ in t.columnas].index("id_paciente")
        faltantes = [(i, f[j]) for i, f in enumerate(datos[nombre], start=2) if f[j] not in conocidos]
        for i, pid in faltantes[:MAX_PROBLEMAS_POR_ARCHIVO]:
            problemas.append(Problema(t.archivo, i, f"El paciente {pid} no existe ni viene en pacientes.csv"))
        if len(faltantes) > MAX_PROBLEMAS_POR_ARCHIVO:
            problemas.append(Problema(t.archivo, None, f"… y {len(faltantes) - MAX_PROBLEMAS_POR_ARCHIVO} más"))
    return problemas


def _problema_de_la_base(e: psycopg.Error, t: Tabla, filas: list[tuple]) -> Problema:
    """Traduce una restricción violada (CHECK, NOT NULL…) al archivo y, si se puede, a la línea."""
    archivo = t.archivo or "agenda_box.csv / citaciones.csv"
    detalle = e.diag.message_detail or ""
    linea = None
    m = re.search(r"Failing row contains \(([^,)]*)", detalle)
    if m and t.columnas[0][0] in t.llave:
        valor = m.group(1)
        linea = next((i for i, f in enumerate(filas, start=2) if str(f[0]) == valor), None)
    restriccion = e.diag.constraint_name or type(e).__name__
    return Problema(archivo, linea, f"No cumple la regla {restriccion} de raw.{t.nombre}: {e.diag.message_primary}")


def _advertencias(conn: psycopg.Connection, id_carga: int, datos: dict[str, list[tuple]],
                  periodo: tuple[date | None, date | None], pacientes: set[str]) -> list[dict]:
    """Lo que no bloquea, pero la Administradora debe ver antes de confirmar."""
    avisos = []

    def agregar(tipo, mensaje, ejemplos):
        if ejemplos:
            avisos.append({"tipo": tipo, "mensaje": mensaje, "cantidad": len(ejemplos), "ejemplos": ejemplos[:10]})

    cambios = conn.execute("SELECT tabla, llave, antes, despues FROM raw.cambio_fila WHERE id_carga = %s",
                           (id_carga,)).fetchall()
    agregar("correccion_medicion", "Mediciones ya cargadas que llegan con otro valor (¿corrección?)",
            [f"{ll['id_paciente']} {ll['fecha_medicion']} {ll['tipo_medicion']}: {a['valor']} → {d['valor']}"
             for tab, ll, a, d in cambios if tab == "mediciones"])
    agregar("estado_retrocede", "Solicitudes que vuelven a la lista después de haber egresado (¿corrección o error?)",
            [f"{ll['id_solicitud']}: {a['estado']} → {d['estado']}" for tab, ll, a, d in cambios
             if tab == "lista_espera" and a["estado"] in ("atendido", "egresado", "fallecido")
             and d["estado"] in ("en_espera", "citado")])
    agregar("dato_maestro", "Cambios en datos del paciente (sexo, comuna o previsión)",
            [f"{ll['id_paciente']}: " + ", ".join(f"{c} {a[c]} → {d[c]}" for c in ("sexo", "comuna", "prevision")
                                                  if a[c] != d[c])
             for tab, ll, a, d in cambios if tab == "pacientes"
             and any(a[c] != d[c] for c in ("sexo", "comuna", "prevision"))])
    desde, hasta = periodo
    if desde or hasta:
        fuera = []
        for nombre, col in COLUMNA_FECHA.items():
            if nombre not in datos:
                continue
            t = next(x for x in TABLAS if x.nombre == nombre)
            j = [c for c, _ in t.columnas].index(col)
            fuera += [f"{t.archivo} línea {i}: {f[j]}" for i, f in enumerate(datos[nombre], start=2)
                      if (desde and f[j] < desde) or (hasta and f[j] > hasta)]
        agregar("fuera_de_periodo", "Filas con fecha fuera del periodo declarado", fuera)
    if pacientes:
        agregar("evento_post_defuncion", "Eventos posteriores a la fecha de defunción",
                [f"{p} {e} ({f})" for p, e, f in conn.execute(
                    "SELECT e.id_paciente, e.id_evento, e.fecha_evento FROM raw.eventos_clinicos e "
                    "JOIN raw.pacientes p USING (id_paciente) WHERE p.fecha_defuncion IS NOT NULL "
                    "AND e.fecha_evento > p.fecha_defuncion AND e.id_paciente = ANY(%s)", (list(pacientes),)).fetchall()])
    return avisos


def _ejecutar_incremental(conn: psycopg.Connection, id_carga: int, datos: dict[str, list[tuple]],
                          periodo: tuple[date | None, date | None]) -> dict:
    """Aplica la exportación sobre raw (en la transacción vigente). La vista previa la llama y luego revierte."""
    resumen, pacientes, nuevos = {}, set(), set()
    for t in TABLAS:                                  # padres primero
        if t.nombre not in datos:
            continue
        try:
            with conn.transaction():
                r = _combinar(conn, t, datos[t.nombre], id_carga)
        except (psycopg.errors.IntegrityError, psycopg.errors.DataError) as e:
            raise ErrorValidacion([_problema_de_la_base(e, t, datos[t.nombre])]) from e
        pacientes |= r.pop("pacientes")
        nuevos |= r.pop("pacientes_nuevos")
        resumen[t.nombre] = r
    return {"resumen": resumen, "pacientes_afectados": sorted(pacientes), "pacientes_nuevos": sorted(nuevos),
            "advertencias": _advertencias(conn, id_carga, datos, periodo, pacientes)}


class ErrorValidacion(ErrorCarga):
    def __init__(self, problemas: list[Problema]):
        self.problemas = problemas
        super().__init__("; ".join(f"{p.archivo}{f' línea {p.linea}' if p.linea else ''}: {p.mensaje}"
                                   for p in problemas[:5]))


def vista_previa(conn: psycopg.Connection, data_dir: Path, periodo: tuple[date | None, date | None] = (None, None),
                 cargado_por: str = "sistema", uri_archivos: str | None = None) -> dict:
    """Valida una exportación por periodo y calcula qué cambiaría, SIN modificar raw.

    Registra la carga (estado `lista` si se puede confirmar, `fallida` si tiene errores) y devuelve los
    conteos por tabla, los pacientes afectados, las advertencias y los errores con archivo y línea.
    """
    data_dir = Path(data_dir)
    huellas_archivos = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(data_dir.glob("*.csv"))}
    with conn.transaction():
        esquema.aplicar(conn, "raw")
        previa = conn.execute("SELECT version FROM raw.carga_lote WHERE estado = 'aplicada' AND archivos = %s::jsonb",
                              (json.dumps(huellas_archivos),)).fetchone()
        if previa:
            raise ErrorCarga(f"Estos archivos ya se cargaron en la versión {previa[0]}: no se crea una versión nueva")
        id_carga = _nueva_carga(conn, "incremental", uri_archivos or str(data_dir), cargado_por,
                                huellas_archivos, periodo, uri_archivos)
    datos, problemas = leer_exportacion(data_dir)
    resultado = {"resumen": {}, "pacientes_afectados": [], "pacientes_nuevos": [], "advertencias": []}
    if not problemas:
        try:
            with conn.transaction(force_rollback=True):      # ensayo completo: nada queda escrito
                if referencias := _validar_referencias(conn, datos):
                    raise ErrorValidacion(referencias)
                resultado = _ejecutar_incremental(conn, id_carga, datos, periodo)
        except ErrorValidacion as e:
            problemas = e.problemas
    estado = "fallida" if problemas else "lista"
    filas = {n: len(f) for n, f in datos.items()}
    with conn.transaction():
        conn.execute("UPDATE raw.carga_lote SET estado = %s, filas = %s, resumen = %s, advertencias = %s, "
                     "errores = %s WHERE id_carga = %s",
                     (estado, json.dumps(filas), json.dumps(resultado["resumen"]),
                      json.dumps(resultado["advertencias"]), json.dumps([p.a_dict() for p in problemas]), id_carga))
    return {"id_carga": id_carga, "estado": estado, "filas": filas, **resultado,
            "errores": [p.a_dict() for p in problemas]}


def aplicar_incremental(conn: psycopg.Connection, id_carga: int, data_dir: Path) -> dict:
    """Confirma una carga en estado `lista`: suma la exportación a raw en una transacción y crea la versión."""
    data_dir = Path(data_dir)
    actuales = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(data_dir.glob("*.csv"))}
    datos, problemas = leer_exportacion(data_dir)
    with conn.transaction():
        _bloquear_cargas(conn)
        fila = conn.execute("SELECT estado, archivos, periodo_desde, periodo_hasta FROM raw.carga_lote "
                            "WHERE id_carga = %s FOR UPDATE", (id_carga,)).fetchone()
        if fila is None:
            raise ErrorCarga(f"No existe la carga {id_carga}")
        estado, archivos, desde, hasta = fila
        if estado != "lista":
            raise ErrorCarga(f"La carga {id_carga} está {estado}: solo se confirma una carga lista")
        if actuales != archivos:
            raise ErrorCarga("Los archivos cambiaron desde la vista previa: vuelve a subirlos")
        if problemas or (problemas := _validar_referencias(conn, datos)):
            raise ErrorValidacion(problemas)
        resultado = _ejecutar_incremental(conn, id_carga, datos, (desde, hasta))
        # `filas` de una versión aplicada = totales de raw tras aplicarla (lo que verifica `python -m db verificar`);
        # las filas de cada archivo quedan en el resumen
        version = _aplicar_version(conn, id_carga, filas_en_base(conn), resultado["resumen"], resultado["advertencias"])
    return {"id_carga": id_carga, "version": version, **resultado}


def descartar(conn: psycopg.Connection, id_carga: int) -> None:
    with conn.transaction():
        n = conn.execute("UPDATE raw.carga_lote SET estado = 'descartada', fin = now() WHERE id_carga = %s "
                         "AND estado IN ('validando', 'lista', 'fallida')", (id_carga,)).rowcount
    if n == 0:
        raise ErrorCarga(f"La carga {id_carga} no existe o ya fue aplicada")


def version_datos(conn: psycopg.Connection) -> int:
    """Versión vigente de raw (la última carga aplicada). La app la usa para saber si debe recargar."""
    try:
        return conn.execute("SELECT coalesce(max(version), 0) FROM raw.carga_lote").fetchone()[0]
    except psycopg.errors.UndefinedColumn:
        return 0


def historial(conn: psycopg.Connection) -> list[dict]:
    filas = conn.execute(
        "SELECT id_carga, version, modo, estado, periodo_desde, periodo_hasta, cargado_por, inicio, fin, "
        "filas, resumen, advertencias, errores, archivos, uri_archivos FROM raw.carga_lote "
        "ORDER BY id_carga DESC").fetchall()
    cols = ["id_carga", "version", "modo", "estado", "periodo_desde", "periodo_hasta", "cargado_por", "inicio",
            "fin", "filas", "resumen", "advertencias", "errores", "archivos", "uri_archivos"]
    return [dict(zip(cols, f)) for f in filas]


def cambios_de_carga(conn: psycopg.Connection, id_carga: int, limite: int = 500) -> list[dict]:
    filas = conn.execute("SELECT tabla, llave, antes, despues FROM raw.cambio_fila WHERE id_carga = %s "
                         "ORDER BY id_cambio LIMIT %s", (id_carga, limite)).fetchall()
    return [{"tabla": t, "llave": ll, "antes": a, "despues": d} for t, ll, a, d in filas]


def borrar(conn: psycopg.Connection, nombre: str) -> list[str]:
    """Elimina un esquema, o todos con nombre="todos" (DROP SCHEMA ... CASCADE).

    No borra un esquema del que depende otro que existe (canal → priorizacion → raw): el CASCADE
    eliminaría en silencio las llaves foráneas y los triggers de ese otro esquema.
    """
    with conn.transaction():
        existentes = esquema.existentes(conn)
        if nombre == "todos":
            objetivo = [e for e in reversed(esquema.ESQUEMAS) if e in existentes]
        else:
            dependientes = [e for e in esquema.dependientes(nombre) if e in existentes]
            if dependientes:
                varios = len(dependientes) > 1
                raise ErrorCarga(f"No se borra {nombre}: {' y '.join(dependientes)} "
                                 f"{'dependen' if varios else 'depende'} de él. "
                                 f"{'Bórralos' if varios else 'Bórralo'} antes o usa --esquema todos.")
            objetivo = [nombre] if nombre in existentes else []
        for e in objetivo:
            conn.execute(f"DROP SCHEMA {e} CASCADE")
    return objetivo


def registrar_ubicacion(conn: psycopg.Connection, id_carga: int, uri: str) -> None:
    """Anota dónde quedaron guardados los archivos originales de una carga (S3 o carpeta local)."""
    with conn.transaction():
        conn.execute("UPDATE raw.carga_lote SET uri_archivos = %s, origen = %s WHERE id_carga = %s", (uri, uri, id_carga))
