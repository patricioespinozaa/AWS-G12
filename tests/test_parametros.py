"""Configuración de las reglas, versionada (F0014): catálogo, validación, aplicar, simular, versiones y API."""
import os
import threading
import time

import pandas as pd
import pytest

from priorizacion import parametros as P
from priorizacion import reglas as R
from priorizacion.registro import RegistroSQLite

URL = os.environ.get("HLF_TEST_DATABASE_URL")
UCI = "evento.hospitalizacion.ingreso_uci"


@pytest.fixture(autouse=True)
def fabrica():
    """Cada prueba parte y termina con los valores de fábrica (los parámetros son globales del proceso)."""
    previos, numero = P.vigentes(), P.numero_vigente
    P.aplicar({}, 0)
    yield
    P.aplicar(previos, numero)


def test_catalogo_completo_y_dentro_de_sus_limites():
    claves = [p.clave for p in P.CATALOGO]
    assert len(claves) == len(set(claves))
    for p in P.CATALOGO:
        valor = p.leer()
        if p.tipo == "opcion":
            assert valor in p.opciones, p.clave
        else:
            assert p.minimo <= valor <= p.maximo, p.clave
            assert (p.tipo != "entero") or float(valor).is_integer(), p.clave
    # Todo valor numérico de las reglas que cambia el puntaje está en el catálogo
    assert {(t, s) for t, s in R.PESO_EVENTO} == {p.llave for p in P.CATALOGO if p.atributo == "PESO_EVENTO"}
    assert set(R.RIESGO_BASAL_DX) == {p.llave for p in P.CATALOGO if p.atributo == "RIESGO_BASAL_DX"}
    assert {"UMBRAL_ALTA", "VIDA_MEDIA_DIAS", "EDAD_UMBRAL_MAYOR", "PESO_TENDENCIA", "TASA_NO_SHOW_GLOBAL"} <= set(P.ATRIBUTOS)
    assert P.normalizar({}) == P.fabrica()


@pytest.mark.parametrize("valores, clave, texto", [
    ({"no.existe": 1}, "no.existe", "no es un parámetro"),
    ({UCI: 99}, UCI, "entre"),
    ({UCI: "mucho"}, UCI, "número"),
    ({"evento.vida_media_dias": 30.5}, "evento.vida_media_dias", "entero"),
    ({"riesgo.dx.I50": "altísimo"}, "riesgo.dx.I50", "alto, medio, bajo"),
    ({"nivel.umbral_media": 25}, "nivel.umbral_media", "menor que el umbral de alta"),
    ({"edad.umbral": 80}, "edad.umbral", "menor que la edad del tramo mayor"),
    ({"medicion.glicemia.minimo": 150}, "medicion.glicemia.maximo", "mayor que el mínimo"),
])
def test_validacion_nombra_el_parametro(valores, clave, texto):
    with pytest.raises(P.ErrorValidacion) as e:
        P.normalizar(valores)
    assert clave in e.value.errores and texto in e.value.errores[clave]


def test_aplicar_y_volver_a_fabrica_sin_tocar_la_foto():
    P.aplicar({UCI: 20, "medicion.glicemia.maximo": 180, "riesgo.dx.E03": "alto", "edad.umbral_mayor": 80}, 3)
    assert R.PESO_EVENTO[("hospitalizacion", "ingreso UCI")] == 20
    assert R.RANGOS_NORMALES["glicemia"] == (70.0, 180)
    assert R.RIESGO_BASAL_DX["E03"][0] == "alto" and "Hipotiroidismo" in R.RIESGO_BASAL_DX["E03"][1]
    assert R.puntos_edad(78) == R.EDAD_PUNTOS and R.puntos_edad(80) == R.EDAD_PUNTOS_MAYOR
    assert R.VERSION_REGLAS == "reglas-v0.1+c3" and P.numero_vigente == 3
    assert P.FABRICA["PESO_EVENTO"][("hospitalizacion", "ingreso UCI")] == 12.0      # la foto no cambia
    assert any("80 años" in regla for _, regla, _ in R.tabla_reglas())               # la tabla legible también
    P.aplicar({}, 0)
    assert R.VERSION_REGLAS == "reglas-v0.1" and P.vigentes() == P.fabrica()


@pytest.mark.datos
def test_pesos_mayores_suben_el_puntaje_de_don_manuel(repo):
    from datetime import date
    from priorizacion.motor import evaluar
    sol, corte = repo.solicitud_de_paciente("PAC-HLF-00002"), date(2026, 7, 20)
    antes = evaluar(sol, repo.historias[sol.id_paciente], corte)
    mas = {p.clave: min(p.maximo, p.leer() + 5) for p in P.CATALOGO if p.atributo == "PESO_EVENTO" and p.leer() > 0}
    P.aplicar(mas, 1)
    despues = evaluar(sol, repo.historias[sol.id_paciente], corte)
    assert despues.puntaje_nivel > antes.puntaje_nivel and despues.version_reglas == "reglas-v0.1+c1"
    assert antes.version_reglas == "reglas-v0.1"
    P.aplicar({}, 0)
    assert evaluar(sol, repo.historias[sol.id_paciente], corte).puntaje == antes.puntaje   # fábrica = hoy


def test_simulacion_temporal_vuelve_a_la_vigente():
    P.aplicar({UCI: 15}, 2)
    with P.temporal({UCI: 1}):
        assert R.PESO_EVENTO[("hospitalizacion", "ingreso UCI")] == 1 and R.VERSION_REGLAS.endswith("simulacion")
    assert R.PESO_EVENTO[("hospitalizacion", "ingreso UCI")] == 15 and R.VERSION_REGLAS == "reglas-v0.1+c2"
    with pytest.raises(RuntimeError), P.temporal({UCI: 1}):
        raise RuntimeError("falla dentro de la simulación")
    assert R.PESO_EVENTO[("hospitalizacion", "ingreso UCI")] == 15


def test_la_simulacion_espera_a_los_calculos_en_curso():
    orden = []
    dentro = threading.Event()

    def calculo():
        with P.lectura():
            dentro.set()
            time.sleep(0.3)
            orden.append("calculo")

    hilo = threading.Thread(target=calculo)
    hilo.start()
    dentro.wait()
    with P.escritura():
        orden.append("simulacion")
    hilo.join()
    assert orden == ["calculo", "simulacion"]
    with P.escritura(), P.lectura(), P.escritura():      # el escritor puede leer y es reentrante
        pass


def _versiones(registro):
    with pytest.raises(ValueError):
        registro.guardar_version_reglas(P.fabrica(), {}, "Sin cambios", "administradora")
    with pytest.raises(ValueError):
        registro.guardar_version_reglas(P.fabrica(), {UCI: {"anterior": 12, "nuevo": 20}}, " ", "administradora")
    valores = P.normalizar({UCI: 20})
    n1 = registro.guardar_version_reglas(valores, P.diferencias(P.fabrica(), valores), "Calibración UCI", "administradora")
    n2 = registro.guardar_version_reglas(P.fabrica(), P.diferencias(valores, P.fabrica()), "Vuelve a fábrica",
                                         "administradora", restaura=None)
    assert (n1, n2) == (1, 2)
    vigente = registro.version_reglas_vigente()
    assert vigente["numero"] == 2 and vigente["version"] == "reglas-v0.1+c2" and vigente["valores"][UCI] == 12.0
    df = registro.versiones_reglas()
    assert list(df["numero"]) == [2, 1] and df.iloc[1]["cambios"][UCI] == {"anterior": 12.0, "nuevo": 20}
    P.aplicar({UCI: 5}, 9)
    assert P.aplicar_vigente(registro) == 2 and R.VERSION_REGLAS == "reglas-v0.1+c2"
    return df


def test_versiones_en_sqlite(tmp_path):
    registro = RegistroSQLite(tmp_path / "r.sqlite")
    assert registro.version_reglas_vigente() is None and P.aplicar_vigente(registro) == 0
    antes = registro.version()
    _versiones(registro)
    assert registro.version() != antes                   # la caché de la API se invalida


@pytest.mark.skipif(not URL, reason="Requiere PostgreSQL")
def test_versiones_en_postgres_igual_que_sqlite(tmp_path):
    import psycopg
    from db import carga, conexion, esquema
    from priorizacion.registro_postgres import RegistroPostgres
    with conexion.conectar(URL) as c:
        carga.borrar(c, "todos")
        with c.transaction():
            for nombre in esquema.ESQUEMAS:
                esquema.aplicar(c, nombre)
    pg = _versiones(RegistroPostgres(URL))
    P.aplicar({}, 0)
    sq = _versiones(RegistroSQLite(tmp_path / "r.sqlite"))
    forma = lambda df: {c: pd.api.types.infer_dtype(df[c], skipna=True) for c in df.columns}   # noqa: E731
    assert forma(pg) == forma(sq)
    assert pg.drop(columns="creada_en").to_dict("records") == sq.drop(columns="creada_en").to_dict("records")
    with psycopg.connect(URL) as c:
        with pytest.raises(psycopg.errors.RaiseException):            # solo inserción
            c.execute("UPDATE priorizacion.version_reglas SET motivo = 'otro motivo' WHERE numero = 1")
        c.rollback()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):        # la autora existe
            c.execute("INSERT INTO priorizacion.version_reglas (numero, version, valores, cambios, motivo, creada_por) "
                      "VALUES (3, 'x', '{}', '{\"a\": 1}', 'motivo largo', 'nadie')")
        c.rollback()
        c.execute("INSERT INTO priorizacion.corrida_nocturna (inicio, fin, origen, alcance, desde, hasta, version_reglas) "
                  "VALUES (now(), now(), 'reglas', 'cambio de reglas', '2026-01-01', '2026-01-02', 'reglas-v0.1+c1')")


# -- API (con el dataset) ------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cliente():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


@pytest.mark.datos
def test_api_simular_guardar_y_restaurar(cliente, monkeypatch):
    from api import estado as E
    lanzados = []
    monkeypatch.setattr(E, "consolidar_en_segundo_plano", lambda origen, **kw: lanzados.append((origen, kw)) or True)
    P.aplicar_vigente(E.registro)
    inicial = P.numero_vigente
    r = cliente.get("/api/reglas").json()
    uci = next(p for p in r["parametros"] if p["clave"] == UCI)
    assert uci["valor"] == uci["fabrica"] == 12.0 and uci["grupo"] == "Eventos clínicos"
    assert {"Niveles", "Eventos clínicos", "Riesgo basal", "Mediciones", "Patrones", "Gestión del box"} <= {
        p["grupo"] for p in r["parametros"]} and r["solo_lectura"]

    bandeja_antes = cliente.get("/api/bandeja").json()["filas"]
    sim = cliente.post("/api/reglas/simulacion", json={"valores": {"nivel.umbral_alta": 12}}).json()
    assert sim["suben"] > 0 and sim["bajan"] == 0 and sim["niveles"]["alta"]["simulado"] > sim["niveles"]["alta"]["actual"]
    assert P.numero_vigente == inicial and cliente.get("/api/bandeja").json()["filas"] == bandeja_antes   # no guarda

    assert cliente.post("/api/reglas/versiones", json={"valores": {UCI: 20}, "motivo": ""}).status_code == 422
    malo = cliente.post("/api/reglas/versiones", json={"valores": {UCI: 99}, "motivo": "Probar límites"})
    assert malo.status_code == 422 and UCI in malo.json()["detail"]["errores"]
    assert cliente.post("/api/reglas/versiones", json={"valores": {}, "motivo": "Sin cambios"}).status_code == 422

    g = cliente.post("/api/reglas/versiones", json={"valores": {UCI: 20}, "motivo": "Calibración con el equipo"}).json()
    assert g["numero"] == inicial + 1 and g["cambios"][0]["anterior"] == 12.0 and g["cambios"][0]["nuevo"] == 20
    assert lanzados[-1] == ("reglas", {"desde_cero": True})
    assert cliente.get("/api/meta").json()["version_reglas"] == f"reglas-v0.1+c{g['numero']}"
    v = cliente.get("/api/reglas/versiones").json()
    assert v["vigente"] == g["numero"] and v["versiones"][0]["creada_por"] and v["versiones"][-1]["numero"] == 0

    monkeypatch.setattr(E, "estado_consolidacion", lambda: {"en_curso": True, "fecha_corte": "2026-10-13"})
    assert cliente.post("/api/reglas/versiones/0/restaurar", json={"motivo": "Volver"}).status_code == 409
    monkeypatch.undo()
    monkeypatch.setattr(E, "consolidar_en_segundo_plano", lambda origen, **kw: True)
    f = cliente.post("/api/reglas/versiones/0/restaurar", json={"motivo": "Volver a fábrica"}).json()
    assert f["numero"] == g["numero"] + 1 and P.vigentes() == P.fabrica()
    assert cliente.post("/api/reglas/versiones/999/restaurar", json={"motivo": "No existe"}).status_code == 404
