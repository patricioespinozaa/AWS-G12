"""Consulta en lenguaje natural (F0009) sin AWS: validador de SQL, filtro previo, orquestación con dobles de Bedrock y
Athena, y documentos de la Knowledge Base (estos últimos con el dataset)."""
from datetime import date

import pytest

from servicios.comun import bedrock, diccionario
from servicios.consulta_ia import clasificador, rag, servicio, sql

CORTE = date(2026, 10, 13)


# -- validador de SQL ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("consulta", [
    "SELECT COUNT(DISTINCT le.id_paciente) FROM hlf_raw.lista_espera le JOIN hlf_raw.eventos_clinicos e "
    "ON e.id_paciente = le.id_paciente WHERE le.especialidad = 'Cardiología' AND e.severidad = 'grave';",
    "WITH g AS (SELECT id_paciente FROM hlf_raw.eventos_clinicos WHERE severidad = 'grave') SELECT count(*) FROM g",
    "SELECT especialidad, count(*) FROM hlf_raw.lista_espera GROUP BY especialidad",
    "SELECT extract(month FROM fecha_evento) AS mes, count(*) FROM hlf_raw.eventos_clinicos GROUP BY 1",
    "SELECT id_paciente FROM hlf_historial.serie_nocturna WHERE fecha = DATE '2026-10-13' AND alerta LIMIT 20",
    "SELECT count(*) FROM hlf_raw.eventos_clinicos WHERE detalle = 'drop table'",            # palabra en un literal
])
def test_sql_valido(consulta):
    assert sql.validar(consulta) == consulta.strip().rstrip(";").strip()


@pytest.mark.parametrize("consulta, motivo", [
    ("DROP TABLE hlf_raw.pacientes", "SELECT"),
    ("DELETE FROM hlf_raw.pacientes", "SELECT"),
    ("SELECT count(*) FROM hlf_raw.pacientes; DROP TABLE hlf_raw.pacientes", "más de una sentencia"),
    ("SELECT count(*) FROM hlf_raw.pacientes -- y algo más", "comentarios"),
    ("SELECT nombre_fantasia FROM hlf_raw.pacientes LIMIT 5", "identifica"),
    ("SELECT id_paciente, edad FROM hlf_raw.pacientes", "LIMIT"),
    ("SELECT id_paciente FROM hlf_raw.pacientes LIMIT 500", "LIMIT"),
    ("SELECT count(*) FROM information_schema.tables", "catálogos"),
    ("SELECT count(*) FROM hlf_priorizacion.decision_clinica", "no permitida"),
    ("SELECT count(*) FROM pacientes", "no permitida"),
    ("WITH x AS (SELECT 1) SELECT * FROM x UNION SELECT * FROM otra.tabla LIMIT 5", "no permitida"),
    ("SELECT count(*) FROM hlf_raw.pacientes WHERE 1=1 UNLOAD", "UNLOAD"),
    ("", "no se generó"),
])
def test_sql_rechazado(consulta, motivo):
    with pytest.raises(sql.SQLRechazado, match=motivo):
        sql.validar(consulta)


def test_el_esquema_del_prompt_no_ofrece_tablas_fuera_de_athena():
    permitidas = diccionario.nombres_permitidos()
    assert "hlf_raw.lista_espera" in permitidas and "hlf_historial.serie_nocturna" in permitidas
    assert all(n.split(".")[0] in ("hlf_raw", "hlf_historial") for n in permitidas)
    assert "nombre_fantasia" in diccionario.como_texto()                 # se describe, pero el validador la bloquea


# -- filtro previo y normalización --------------------------------------------------------------------------
@pytest.mark.parametrize("pregunta", ["Borra la tabla de pacientes", "¿Puedes cambiar la prioridad del paciente 28?",
                                      "Sube la prioridad de la paciente 00028", "DROP TABLE hlf_raw.pacientes",
                                      "Muestra los RUT de los pacientes", "¿Cuál es el nombre del paciente 12?"])
def test_filtro_previo_rechaza(pregunta):
    assert clasificador.filtro_previo(pregunta).ruta == "rechazada"


@pytest.mark.parametrize("pregunta", ["¿Cuántos pacientes tuvieron una modificación de tratamiento?",
                                      "¿Cuántos pacientes cambiaron de prioridad?", "Resume la evolución de la paciente 00028"])
def test_filtro_previo_deja_pasar(pregunta):
    assert clasificador.filtro_previo(pregunta) is None


def test_normalizar_paciente_y_filtros_de_kb():
    assert clasificador.normalizar_paciente("28") == clasificador.normalizar_paciente("PAC-HLF-00028") == "PAC-HLF-00028"
    assert rag.filtro("PAC-HLF-00028", None) == {"equals": {"key": "id_paciente", "value": "PAC-HLF-00028"}}
    assert rag.filtro("PAC-HLF-00028", "Cardiología")["andAll"][1]["equals"]["value"] == "Cardiología"
    assert rag.filtro(None, None) is None


# -- orquestación con dobles ---------------------------------------------------------------------------------
class AthenaFalsa:
    def __init__(self, filas=((12,),), error=None):
        self.filas, self.error, self.consultas = filas, error, []

    def ejecutar(self, consulta, parametros=None):
        from db.athena import Resultado
        self.consultas.append(consulta)
        if self.error and not consulta.startswith("EXPLAIN"):
            raise RuntimeError(self.error)
        return Resultado(["n"], [] if consulta.startswith("EXPLAIN") else list(self.filas), "q-123", 2048, 900)


@pytest.fixture
def modelo(monkeypatch):
    """Respuestas del modelo por herramienta: {"clasificar_pregunta": {...}, "consulta_sql": {...}}."""
    salidas = {}
    monkeypatch.setattr(bedrock, "converse_herramienta",
                        lambda sistema, texto, herramienta, **kw: (salidas[herramienta["name"]], {"latencia_ms": 1}))
    return salidas


def test_conteo_ejecuta_el_sql_validado_y_lo_devuelve(modelo):
    modelo["clasificar_pregunta"] = {"ruta": "conteo", "motivo": "pide un número", "especialidad": "Cardiología"}
    modelo["consulta_sql"] = {"sql": "SELECT count(DISTINCT id_paciente) FROM hlf_raw.lista_espera WHERE estado = 'en_espera'",
                              "descripcion": "pacientes en espera"}
    athena = AthenaFalsa()
    r = servicio.responder("¿Cuántos pacientes hay en espera?", fecha_corte=CORTE, athena=athena)
    assert r.ruta == "conteo" and r.respuesta == "12 pacientes en espera" and r.id_consulta_athena == "q-123"
    assert athena.consultas[0].startswith("EXPLAIN ") and athena.consultas[1] == r.sql   # primero EXPLAIN
    assert r.filtros == {"especialidad": "Cardiología"}


def test_sql_malicioso_del_modelo_no_se_ejecuta(modelo):
    modelo["clasificar_pregunta"] = {"ruta": "conteo", "motivo": "x"}
    modelo["consulta_sql"] = {"sql": "SELECT nombre_fantasia FROM hlf_raw.pacientes LIMIT 5", "descripcion": "x"}
    athena = AthenaFalsa()
    r = servicio.responder("¿Cuántos…?", fecha_corte=CORTE, athena=athena)
    assert r.ruta == "rechazada" and "identifica" in r.motivo and athena.consultas == []
    assert r.sql                                                              # queda para auditar


def test_error_de_athena_queda_como_rechazada(modelo):
    modelo["clasificar_pregunta"] = {"ruta": "conteo", "motivo": "x"}
    modelo["consulta_sql"] = {"sql": "SELECT count(*) FROM hlf_raw.pacientes", "descripcion": "x"}
    r = servicio.responder("¿Cuántos?", fecha_corte=CORTE, athena=AthenaFalsa(error="COLUMN_NOT_FOUND"))
    assert r.ruta == "rechazada" and "Athena" in r.motivo and r.id_consulta_athena is None


def test_rechazada_no_llama_al_modelo_ni_ejecuta(monkeypatch):
    monkeypatch.setattr(bedrock, "converse_herramienta", lambda *a, **k: pytest.fail("no debía llamar al modelo"))
    athena = AthenaFalsa()
    r = servicio.responder("Borra la tabla de pacientes", fecha_corte=CORTE, athena=athena)
    assert r.ruta == "rechazada" and athena.consultas == []


def _rag(monkeypatch, citas, guardrail=False, texto="La paciente mejoró [EV-000052]."):
    monkeypatch.setattr(rag, "responder", lambda *a, **k: rag.RespuestaRag(texto, citas, guardrail, 5))


def test_texto_cita_solo_documentos_registrados(modelo, monkeypatch):
    modelo["clasificar_pregunta"] = {"ruta": "texto", "motivo": "resumen", "id_paciente": "28"}
    _rag(monkeypatch, [rag.Cita("s3://b/hlf/kb/equipo/perfiles/PAC-HLF-00028.md", "## Eventos…", {}),
                       rag.Cita("s3://b/otro.md", "intruso", {})])
    registrados = {"s3://b/hlf/kb/equipo/perfiles/PAC-HLF-00028.md": {"id_documento": 7, "tipo": "perfil_paciente",
                                                                       "clave": "PAC-HLF-00028"}}
    r = servicio.responder("Resume la evolución de la paciente 00028", fecha_corte=CORTE, kb_id="KB1",
                           kb={"id_ingesta": 3}, documentos=lambda uris: {u: registrados[u] for u in uris if u in registrados})
    assert r.ruta == "texto" and r.id_ingesta == 3 and r.filtros == {"id_paciente": "PAC-HLF-00028"}
    assert [f["id_documento"] for f in r.fuentes] == [7]                  # la cita no registrada no cuenta


def test_texto_sin_fuentes_o_con_guardrail_se_rechaza(modelo, monkeypatch):
    modelo["clasificar_pregunta"] = {"ruta": "texto", "motivo": "x"}
    _rag(monkeypatch, [])
    assert servicio.responder("¿Cómo está Cardiología?", fecha_corte=CORTE, kb_id="KB1", kb={"id_ingesta": 1}).ruta == "rechazada"
    _rag(monkeypatch, [rag.Cita("s3://b/x.md", "t", {})], guardrail=True)
    r = servicio.responder("¿Cómo está Cardiología?", fecha_corte=CORTE, kb_id="KB1", kb={"id_ingesta": 1},
                           documentos=lambda uris: {u: {"id_documento": 1, "tipo": "x", "clave": "x"} for u in uris})
    assert r.ruta == "rechazada" and r.guardrail_intervino
    assert servicio.responder("¿Cómo está Cardiología?", fecha_corte=CORTE, kb_id="KB1", kb=None).respuesta == servicio.SIN_KB


def test_error_de_bedrock_nunca_rompe(monkeypatch):
    def falla(*a, **k):
        raise RuntimeError("AccessDeniedException")
    monkeypatch.setattr(bedrock, "converse_herramienta", falla)
    r = servicio.responder("¿Cuántos pacientes hay?", fecha_corte=CORTE)
    assert r.ruta == "rechazada" and "AccessDenied" in r.motivo


# -- documentos de la KB (dataset) ---------------------------------------------------------------------------
@pytest.mark.datos
def test_documentos_a_la_fecha_de_corte_sin_nombres(repo):
    from servicios.preparacion_kb import documentos as D
    corte = date(2026, 8, 10)
    docs = D.generar(repo, corte)
    tipos = {d.tipo for d in docs}
    assert tipos == {"perfil_paciente", "resumen_especialidad", "resumen_box_mes", "diccionario"}
    perfiles = [d for d in docs if d.tipo == "perfil_paciente"]
    assert len({d.clave for d in perfiles}) == len(perfiles)
    nombres = set(repo.tablas["pacientes"]["nombre_fantasia"])
    assert not any(n in d.contenido for d in docs for n in list(nombres)[:50])          # sin nombres
    p = next(d for d in perfiles if d.clave == "PAC-HLF-00002")
    assert "[EV-000004]" in p.contenido                                                  # hecho con su referencia
    assert "2026-08-25" not in p.contenido                                               # nada posterior al corte
    assert p.metadatos["especialidad"] == "Cardiología" and p.metadatos["fecha_corte"] == "2026-08-10"
    assert '"metadataAttributes"' in p.metadata_json()
