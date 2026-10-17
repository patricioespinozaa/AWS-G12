"""Cargas por periodo (F0005 fase B): las exportaciones nuevas se SUMAN a lo existente y quedan versionadas.

El dataset se parte en dos exportaciones como las entregaría el HLF:
- Periodo 1 (hasta CORTE): los pacientes que ya estaban en la lista, con el estado que tenían en ese momento
  (un paciente atendido o fallecido después del corte aparece todavía en espera).
- Periodo 2: los ingresos nuevos, los eventos, mediciones, citas y agenda desde 30 días antes del corte
  (solapamiento), y los datos de pacientes y solicitudes que cambiaron (estado final, defunción).
Cargar el periodo 1 y luego sumar el 2 debe dejar raw IDÉNTICO a cargar el dataset completo de una vez.

Requiere PostgreSQL (HLF_TEST_DATABASE_URL) y el dataset.
"""
import csv
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from db import carga, conexion, esquema
from priorizacion.config import DATA_DIR

URL = os.environ.get("HLF_TEST_DATABASE_URL")
pytestmark = [pytest.mark.datos,
              pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")]
CORTE = date(2026, 6, 30)
SOLAPAMIENTO = timedelta(days=30)
SIN_PROGRESO = {"progreso": lambda *_: None}


def _leer(archivo: str) -> tuple[list[str], list[dict]]:
    with (DATA_DIR / archivo).open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        return list(lector.fieldnames), list(lector)


def _escribir(carpeta: Path, archivo: str, columnas: list[str], filas: list[dict]):
    carpeta.mkdir(parents=True, exist_ok=True)
    with (carpeta / archivo).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)


def _d(s: str) -> date | None:
    return date.fromisoformat(s) if s else None


@pytest.fixture(scope="module")
def periodos(tmp_path_factory) -> tuple[Path, Path, dict]:
    """Parte el dataset en dos exportaciones por periodo. Devuelve sus carpetas y lo que se espera que cambie."""
    base = tmp_path_factory.mktemp("periodos")
    p1, p2 = base / "periodo1", base / "periodo2"
    col_pac, pacientes = _leer("pacientes.csv")
    col_lis, lista = _leer("lista_espera.csv")
    col_ev, eventos = _leer("eventos_clinicos.csv")
    col_me, mediciones = _leer("mediciones.csv")
    col_ci, citas = _leer("citaciones.csv")
    col_ag, agenda = _leer("agenda_box.csv")

    # Egreso conocido al momento del corte: primera cita con asistencia (atendido) o defunción (fallecido)
    asistio = {}
    for c in citas:
        if c["estado_cita"] == "asistio":
            f = _d(c["fecha_cita"])
            asistio[c["id_paciente"]] = min(asistio.get(c["id_paciente"], f), f)
    defuncion = {p["id_paciente"]: _d(p["fecha_defuncion"]) for p in pacientes}

    lista_p1, cambia_estado = [], set()
    for s in lista:
        if _d(s["fecha_ingreso_lista"]) > CORTE:
            continue
        fila = dict(s)
        egreso = asistio.get(s["id_paciente"]) if s["estado"] == "atendido" else \
            defuncion.get(s["id_paciente"]) if s["estado"] == "fallecido" else None
        if egreso and egreso > CORTE:
            fila["estado"] = "en_espera"
            cambia_estado.add(s["id_solicitud"])
        lista_p1.append(fila)
    en_p1 = {s["id_paciente"] for s in lista_p1}
    pacientes_p1, cambia_paciente = [], set()
    for p in pacientes:
        if p["id_paciente"] not in en_p1:
            continue
        fila = dict(p)
        if defuncion[p["id_paciente"]] and defuncion[p["id_paciente"]] > CORTE:
            fila["fallecido"], fila["fecha_defuncion"] = "false", ""
            cambia_paciente.add(p["id_paciente"])
        pacientes_p1.append(fila)

    def hasta(filas, col, limite, pacientes_ok=None):
        return [f for f in filas if _d(f[col]) <= limite and (pacientes_ok is None or f["id_paciente"] in pacientes_ok)]

    def desde(filas, col, inicio):
        return [f for f in filas if _d(f[col]) > inicio]

    _escribir(p1, "pacientes.csv", col_pac, pacientes_p1)
    _escribir(p1, "lista_espera.csv", col_lis, lista_p1)
    _escribir(p1, "eventos_clinicos.csv", col_ev, hasta(eventos, "fecha_evento", CORTE, en_p1))
    _escribir(p1, "mediciones.csv", col_me, hasta(mediciones, "fecha_medicion", CORTE, en_p1))
    _escribir(p1, "citaciones.csv", col_ci, hasta(citas, "fecha_cita", CORTE, en_p1))
    _escribir(p1, "agenda_box.csv", col_ag, hasta(agenda, "fecha", CORTE))

    inicio_p2 = CORTE - SOLAPAMIENTO
    ev2, me2, ci2 = desde(eventos, "fecha_evento", inicio_p2), desde(mediciones, "fecha_medicion", inicio_p2), \
        desde(citas, "fecha_cita", inicio_p2)
    # Lo de antes del solapamiento de pacientes que no estaban en el periodo 1 (ingresaron después del corte)
    nuevos = {s["id_paciente"] for s in lista} - en_p1
    ev2 += [f for f in eventos if f["id_paciente"] in nuevos and _d(f["fecha_evento"]) <= inicio_p2]
    me2 += [f for f in mediciones if f["id_paciente"] in nuevos and _d(f["fecha_medicion"]) <= inicio_p2]
    ci2 += [f for f in citas if f["id_paciente"] in nuevos and _d(f["fecha_cita"]) <= inicio_p2]
    lista_p2 = [s for s in lista if s["id_paciente"] in nuevos or s["id_solicitud"] in cambia_estado]
    con_datos_p2 = {f["id_paciente"] for f in ev2 + me2 + ci2} | {s["id_paciente"] for s in lista_p2} | cambia_paciente
    _escribir(p2, "pacientes.csv", col_pac, [p for p in pacientes if p["id_paciente"] in con_datos_p2])
    _escribir(p2, "lista_espera.csv", col_lis, lista_p2)
    _escribir(p2, "eventos_clinicos.csv", col_ev, ev2)
    _escribir(p2, "mediciones.csv", col_me, me2)
    _escribir(p2, "citaciones.csv", col_ci, ci2)
    _escribir(p2, "agenda_box.csv", col_ag, desde(agenda, "fecha", inicio_p2))
    esperado = {"cambia_estado": cambia_estado, "cambia_paciente": cambia_paciente, "nuevos": nuevos,
                "pacientes_p1": en_p1}
    return p1, p2, esperado


@pytest.fixture
def conn():
    with conexion.conectar(URL) as c:
        carga.borrar(c, "todos")
        with c.transaction():
            for nombre in esquema.ESQUEMAS:
                esquema.aplicar(c, nombre)
        yield c


def _raw(c) -> dict[str, set]:
    """Contenido de raw sin las columnas de procedencia, para comparar con la carga completa."""
    salida = {}
    for t in carga.TABLAS:
        cols = ", ".join(col for col, _ in t.columnas)
        salida[t.nombre] = set(c.execute(f"SELECT {cols} FROM raw.{t.nombre}").fetchall())
    return salida


def test_periodos_bien_formados(periodos):
    p1, p2, esp = periodos
    assert esp["cambia_estado"] and esp["cambia_paciente"] and esp["nuevos"]   # el caso es interesante
    assert len(list(p1.glob("*.csv"))) == len(list(p2.glob("*.csv"))) == 6


def test_dos_periodos_dejan_raw_igual_que_la_carga_completa(conn, periodos):
    p1, p2, esp = periodos
    carga.cargar(conn, p1, **SIN_PROGRESO)
    previa = carga.vista_previa(conn, p2, (CORTE - SOLAPAMIENTO, date(2026, 10, 13)), cargado_por="administradora")
    assert previa["estado"] == "lista", previa["errores"]
    res = carga.aplicar_incremental(conn, previa["id_carga"], p2)
    assert res["version"] == 2
    assert res["resumen"] == previa["resumen"]                       # la vista previa fue exacta
    sumado = _raw(conn)

    carga.borrar(conn, "todos")
    with conn.transaction():
        esquema.aplicar(conn, "raw")
    carga.cargar(conn, DATA_DIR, **SIN_PROGRESO)
    assert sumado == _raw(conn)                                       # suma, no reemplaza


def test_la_historia_previa_se_conserva_y_se_suma(conn, periodos):
    p1, p2, esp = periodos
    carga.cargar(conn, p1, **SIN_PROGRESO)
    antes = {r[0] for r in conn.execute("SELECT id_evento FROM raw.eventos_clinicos").fetchall()}
    previa = carga.vista_previa(conn, p2, cargado_por="administradora")
    carga.aplicar_incremental(conn, previa["id_carga"], p2)
    despues = {r[0] for r in conn.execute("SELECT id_evento FROM raw.eventos_clinicos").fetchall()}
    assert antes < despues                                            # nada se borró y hay eventos nuevos
    # Un paciente con eventos en ambos periodos los tiene todos
    con_ambos = conn.execute("""
        SELECT id_paciente FROM raw.eventos_clinicos GROUP BY id_paciente
        HAVING count(DISTINCT id_carga_alta) = 2 LIMIT 1""").fetchone()
    assert con_ambos is not None
    resumen = previa["resumen"]["eventos_clinicos"]
    assert resumen["sin_cambio"] > 0                                  # el solapamiento no duplicó
    assert resumen["nuevas"] == len(despues) - len(antes)


def test_cambios_quedan_en_el_historial(conn, periodos):
    p1, p2, esp = periodos
    carga.cargar(conn, p1, **SIN_PROGRESO)
    previa = carga.vista_previa(conn, p2, cargado_por="administradora")
    res = carga.aplicar_incremental(conn, previa["id_carga"], p2)
    cambios = carga.cambios_de_carga(conn, res["id_carga"], limite=10_000)
    estados = {c["llave"]["id_solicitud"]: (c["antes"]["estado"], c["despues"]["estado"])
               for c in cambios if c["tabla"] == "lista_espera"}
    assert set(estados) == esp["cambia_estado"]
    assert all(a == "en_espera" and d in ("atendido", "fallecido") for a, d in estados.values())
    fallecidos = {c["llave"]["id_paciente"] for c in cambios if c["tabla"] == "pacientes"
                  and c["antes"]["fallecido"] is False and c["despues"]["fallecido"] is True}
    assert fallecidos == esp["cambia_paciente"]
    # Procedencia: la solicitud cambiada quedó marcada con la carga que la modificó
    sol = next(iter(esp["cambia_estado"]))
    alta, modif = conn.execute("SELECT id_carga_alta, id_carga_modificacion FROM raw.lista_espera "
                               "WHERE id_solicitud = %s", (sol,)).fetchone()
    assert modif == res["id_carga"] and alta != modif


def test_vista_previa_y_descartar_no_dejan_huella(conn, periodos):
    p1, p2, _ = periodos
    carga.cargar(conn, p1, **SIN_PROGRESO)
    conn.commit()
    antes = _raw(conn)
    previa = carga.vista_previa(conn, p2, cargado_por="administradora")
    assert previa["resumen"]["eventos_clinicos"]["nuevas"] > 0
    assert _raw(conn) == antes
    assert conn.execute("SELECT count(*) FROM raw.cambio_fila").fetchone()[0] == 0
    carga.descartar(conn, previa["id_carga"])
    assert _raw(conn) == antes
    with pytest.raises(carga.ErrorCarga, match="descartada"):
        carga.aplicar_incremental(conn, previa["id_carga"], p2)


def test_los_mismos_archivos_no_crean_otra_version(conn, periodos):
    p1, p2, _ = periodos
    carga.cargar(conn, p1, **SIN_PROGRESO)
    previa = carga.vista_previa(conn, p2, cargado_por="administradora")
    carga.aplicar_incremental(conn, previa["id_carga"], p2)
    with pytest.raises(carga.ErrorCarga, match="ya se cargaron en la versión 2"):
        carga.vista_previa(conn, p2, cargado_por="administradora")


def test_errores_bloquean_con_archivo_y_linea(conn, periodos, tmp_path):
    p1, _, _ = periodos
    carga.cargar(conn, p1, **SIN_PROGRESO)
    columnas, eventos = _leer("eventos_clinicos.csv")
    malos = [dict(eventos[0], id_evento="EV-900001", id_paciente="PAC-NO-EXISTE"),
             dict(eventos[1], id_evento="EV-900002", fecha_evento="2026-13-45"),
             dict(eventos[2], id_evento="EV-900003"), dict(eventos[3], id_evento="EV-900003")]
    _escribir(tmp_path, "eventos_clinicos.csv", columnas, malos)
    previa = carga.vista_previa(conn, tmp_path, cargado_por="administradora")
    assert previa["estado"] == "fallida"
    assert any(e["archivo"] == "eventos_clinicos.csv" and e["linea"] == 3 for e in previa["errores"])   # fecha
    _escribir(tmp_path, "eventos_clinicos.csv", columnas, [malos[0], malos[2], malos[3]])
    previa = carga.vista_previa(conn, tmp_path, cargado_por="administradora")
    lineas = {(e["linea"], e["mensaje"].split(" ")[0]) for e in previa["errores"]}
    assert (4, "Llave") in lineas                                     # llave repetida en la línea 4
    _escribir(tmp_path, "eventos_clinicos.csv", columnas, [malos[0]])
    previa = carga.vista_previa(conn, tmp_path, cargado_por="administradora")
    assert previa["errores"] == [{"archivo": "eventos_clinicos.csv", "linea": 2,
                                  "mensaje": "El paciente PAC-NO-EXISTE no existe ni viene en pacientes.csv"}]
    with pytest.raises(carga.ErrorCarga):
        carga.aplicar_incremental(conn, previa["id_carga"], tmp_path)


def test_advertencias_de_correccion_y_fuera_de_periodo(conn, periodos, tmp_path):
    p1, _, _ = periodos
    carga.cargar(conn, p1, **SIN_PROGRESO)
    columnas, mediciones = _leer("mediciones.csv")
    fila = next(m for m in mediciones if _d(m["fecha_medicion"]) <= CORTE)
    corregida = dict(fila, valor=str(float(fila["valor"]) + 1))
    _escribir(tmp_path, "mediciones.csv", columnas, [corregida])
    previa = carga.vista_previa(conn, tmp_path, (date(2026, 9, 1), date(2026, 9, 30)), cargado_por="administradora")
    assert previa["estado"] == "lista"
    tipos = {a["tipo"] for a in previa["advertencias"]}
    assert {"correccion_medicion", "fuera_de_periodo"} <= tipos


def test_historial_lista_las_versiones(conn, periodos):
    p1, p2, _ = periodos
    carga.cargar(conn, p1, **SIN_PROGRESO)
    previa = carga.vista_previa(conn, p2, (CORTE, date(2026, 10, 13)), cargado_por="administradora")
    carga.aplicar_incremental(conn, previa["id_carga"], p2)
    h = carga.historial(conn)
    assert [(c["version"], c["modo"], c["estado"]) for c in h] == [(2, "incremental", "aplicada"),
                                                                  (1, "inicial", "aplicada")]
    assert h[0]["cargado_por"] == "administradora" and h[0]["periodo_desde"] == CORTE
    assert set(h[0]["archivos"]) == {p.name for p in p2.glob("*.csv")}
    assert carga.version_datos(conn) == 2


def test_rol_de_cargas_no_puede_borrar(conn):
    for nombre in esquema.ESQUEMAS:
        esquema.aplicar_permisos(conn, nombre)
    conn.commit()
    with conn.transaction(force_rollback=True):
        conn.execute("SET LOCAL ROLE hlf_cargas")
        import psycopg
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("DELETE FROM raw.eventos_clinicos")


def test_verificacion_en_verde_despues_de_sumar_un_periodo(conn, periodos):
    from db import verificacion
    p1, p2, _ = periodos
    carga.cargar(conn, p1, **SIN_PROGRESO)
    previa = carga.vista_previa(conn, p2, cargado_por="administradora")
    carga.aplicar_incremental(conn, previa["id_carga"], p2)
    chequeos = verificacion.verificar(conn) + verificacion.verificar_app(conn)
    assert all(c.ok for c in chequeos if not c.informativo), [(c.nombre, c.detalle) for c in chequeos if not c.ok]
