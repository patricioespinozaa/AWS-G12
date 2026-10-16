"""Exámenes externos con lectura asistida (F0012): validación de citas sobre 10 documentos sintéticos, texto de
Textract y el flujo en PostgreSQL (pendiente sin valores → lectura → validación con los valores que confirma la persona)."""
import importlib.util
import io
import os
import re
from datetime import date
from pathlib import Path

import pytest

from servicios.ocr_examenes import extraccion, texto

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("examenes_sinteticos", RAIZ / "scripts" / "examenes_sinteticos.py")
SINTETICOS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SINTETICOS)
URL = os.environ.get("HLF_TEST_DATABASE_URL")


def _linea(texto_doc: str, *claves) -> str:
    return next((l for l in texto_doc.split("\n") if all(k.lower() in l.lower() for k in claves)), "")


def modelo_correcto(texto_doc: str, esperado: dict) -> dict:
    """Lo que haría un buen modelo: cada dato con la línea del documento donde aparece."""
    lineas = texto_doc.split("\n")
    p = {"tipo_medicion": esperado["tipo_medicion"] or "", "lugar": lineas[0], "citas": {"lugar": lineas[0]}, "confianza": 0.9}
    if esperado["tipo_medicion"]:
        fila = next(l for l in lineas if extraccion._nombra(l, esperado["tipo_medicion"]))
        numeros = re.findall(r"(?<![\w.,])\d+(?:[.,]\d+)?", fila)            # números sueltos (no el 1 de HbA1c)
        valor_txt = next((x for x in numeros if extraccion._numero(x) == esperado["valor"]), numeros[0])
        unidad = next((u for u in ("mmol/L", "mg/dL", "%", "mmHg", "L/min", "puntos", "/10") if u.lower() in fila.lower()), "")
        p.update(valor=valor_txt, unidad=unidad)
        p["citas"].update(tipo_medicion=fila, valor=fila, unidad=fila)
    if esperado["fecha_examen"]:
        fila_fecha = next(l for l in lineas if extraccion._fechas_en(l))
        p["fecha_examen"] = esperado["fecha_examen"]
        p["citas"]["fecha_examen"] = fila_fecha
    return p


def modelo_inventor(texto_doc: str, esperado: dict) -> dict:
    """Un modelo que inventa: valor y fecha sin respaldo, tipo equivocado y citas que no están en el documento."""
    return {"tipo_medicion": "glicemia", "valor": "123", "unidad": "mg/dL", "fecha_examen": "2026-01-01",
            "lugar": "Clínica Inventada", "confianza": 0.99,
            "citas": {"tipo_medicion": texto_doc.split("\n")[0], "valor": "Glicemia 123 mg/dL",
                      "unidad": "mg/dL", "fecha_examen": texto_doc.split("\n")[0], "lugar": "Clínica Inventada"}}


@pytest.mark.parametrize("nombre, formato, texto_doc, esperado", SINTETICOS.DOCUMENTOS, ids=[d[0] for d in SINTETICOS.DOCUMENTOS])
def test_lectura_correcta_de_los_10_documentos(nombre, formato, texto_doc, esperado):
    lectura = extraccion.validar(modelo_correcto(texto_doc, esperado), texto_doc)
    obtenido = {c: lectura.valor(c) for c in ("tipo_medicion", "valor", "fecha_examen")}
    obtenido["valor"] = float(obtenido["valor"]) if obtenido["valor"] is not None else None
    assert obtenido == {c: esperado[c] for c in ("tipo_medicion", "valor", "fecha_examen")}


@pytest.mark.parametrize("modelo", [modelo_correcto, modelo_inventor])
def test_toda_propuesta_tiene_cita_literal_y_nada_se_inventa(modelo):
    for nombre, _, texto_doc, esperado in SINTETICOS.DOCUMENTOS:
        lectura = extraccion.validar(modelo(texto_doc, esperado), texto_doc)
        for c in lectura.campos.values():
            if c.valor is not None:
                assert c.cita and extraccion.normalizar(c.cita) in extraccion.normalizar(texto_doc), (nombre, c)
        if modelo is modelo_inventor:
            assert lectura.valor("valor") is None and lectura.valor("lugar") is None, nombre
            assert lectura.valor("fecha_examen") is None, nombre                 # 2026-01-01 no está en ningún documento


def test_unidades_solo_con_tabla_explicita():
    doc = "LAB\nFecha: 01/09/2026\nGlucosa | 7,2 | mmol/L"
    p = {"tipo_medicion": "glicemia", "valor": "7,2", "unidad": "mmol/L", "fecha_examen": "2026-09-01",
         "citas": {"tipo_medicion": "Glucosa | 7,2 | mmol/L", "valor": "Glucosa | 7,2", "unidad": "7,2 | mmol/L",
                   "fecha_examen": "Fecha: 01/09/2026"}}
    lectura = extraccion.validar(p, doc)
    assert lectura.valor("valor") == "129.7" and lectura.valor("unidad") == "mg/dL" and "18,016" in lectura.campos["valor"].nota
    doc2 = "LAB\nPresion sistolica 21 kPa"                                     # sin conversión: queda para revisión
    p2 = {"tipo_medicion": "presion_sistolica", "valor": "21", "unidad": "kPa", "fecha_examen": "",
          "citas": {"tipo_medicion": "Presion sistolica 21 kPa", "valor": "Presion sistolica 21 kPa", "unidad": "21 kPa"}}
    lectura2 = extraccion.validar(p2, doc2)
    assert lectura2.valor("valor") is None and lectura2.valor("tipo_medicion") == "presion_sistolica"


def test_texto_de_textract_con_tablas():
    bloques = [
        {"Id": "l1", "BlockType": "LINE", "Text": "LABORATORIO ANDES"},
        {"Id": "t", "BlockType": "TABLE", "Relationships": [{"Type": "CHILD", "Ids": ["c1", "c2"]}]},
        {"Id": "c1", "BlockType": "CELL", "RowIndex": 1, "ColumnIndex": 1, "Relationships": [{"Type": "CHILD", "Ids": ["w1"]}]},
        {"Id": "c2", "BlockType": "CELL", "RowIndex": 1, "ColumnIndex": 2, "Relationships": [{"Type": "CHILD", "Ids": ["w2", "w3"]}]},
        {"Id": "w1", "BlockType": "WORD", "Text": "Glicemia"}, {"Id": "w2", "BlockType": "WORD", "Text": "156"},
        {"Id": "w3", "BlockType": "WORD", "Text": "mg/dL"},
    ]
    assert texto._texto(bloques) == "LABORATORIO ANDES\nGlicemia | 156 mg/dL"


def test_los_archivos_sinteticos_se_generan(tmp_path):
    pytest.importorskip("PIL")
    rutas = SINTETICOS.escribir(tmp_path)
    assert len(rutas) == 10 and {r.suffix for r in rutas} == {".pdf", ".png"}
    assert rutas[0].read_bytes().startswith(b"%PDF") and (tmp_path / "esperado.json").exists()


# -- flujo en PostgreSQL -------------------------------------------------------------------------------------
class S3Falso:
    def __init__(self, contenido=b"%PDF-1.4 examen", tipo="application/pdf"):
        self.contenido, self.tipo = contenido, tipo

    def head_object(self, Bucket, Key):
        return {"ContentType": self.tipo, "ContentLength": len(self.contenido)}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.contenido)}


class TextractFalso:
    def __init__(self, texto_doc):
        self.lineas = texto_doc.split("\n")

    def analyze_document(self, **_):
        return {"Blocks": [{"Id": str(i), "BlockType": "LINE", "Text": l} for i, l in enumerate(self.lineas)]}


@pytest.fixture(scope="module")
def base():
    from apoyo_asistente import preparar
    conn = preparar()
    yield conn
    conn.close()


@pytest.mark.datos
@pytest.mark.skipif(not URL, reason="Requiere PostgreSQL")
def test_flujo_completo_y_solo_cuenta_al_validar(base, monkeypatch):
    import psycopg
    from api.rutas import examenes
    from priorizacion import config
    from priorizacion.datos import Repositorio
    from priorizacion.registro_postgres import RegistroPostgres
    from servicios.ocr_examenes import proceso
    monkeypatch.setattr(config, "S3_BUCKET", "bucket-prueba")
    monkeypatch.setattr(config, "EXAMENES_ESCANEO", False)
    nombre, _, texto_doc, esperado = SINTETICOS.DOCUMENTOS[0]
    clave = "hlf/canal/evidencias/PAC-HLF-00002/abc/01.pdf"
    with base.transaction():
        r = examenes.crear_evidencia(base, "PAC-HLF-00002", clave, s3=S3Falso())
    ide = r["id_evidencia"]
    fila = base.execute("SELECT estado, tipo_medicion, valor, sha256_archivo, escaneo_malware FROM canal.evidencia_externa "
                        "WHERE id_evidencia = %s", (ide,)).fetchone()
    assert fila[0] == "pendiente" and fila[1] is None and fila[2] is None and len(fila[3]) == 64 and fila[4] == "sin_escaneo"
    with pytest.raises(Exception):                                            # otro paciente: la clave no corresponde
        examenes.crear_evidencia(base, "PAC-HLF-00001", clave, s3=S3Falso())

    proceso.leer(base, ide, textract=TextractFalso(texto_doc),
                 proponer=lambda t: (modelo_correcto(t, esperado), {}))
    propuesta = proceso.ultima_lectura(base, ide)
    assert propuesta["valor"]["valor"] == "156" and propuesta["valor"]["cita"] in texto_doc
    assert base.execute("SELECT estado, valor FROM canal.evidencia_externa WHERE id_evidencia = %s",
                        (ide,)).fetchone() == ("pendiente", None)               # la propuesta no toca la evidencia

    registro = RegistroPostgres(URL)
    repo = Repositorio.desde_postgres(URL)
    repo.aplicar_registro(registro.evidencias(), registro.mensajes(), "PAC-HLF-00002")
    assert not any(m.ref == f"externa:{ide}" for ms in repo.historias["PAC-HLF-00002"].mediciones.values() for m in ms)

    with pytest.raises(psycopg.errors.CheckViolation):                        # validar exige tipo, valor y fecha
        registro.revisar_evidencia(str(ide), "validada", "administradora", "")
    registro.revisar_evidencia(str(ide), "validada", "administradora", "ok",
                               {"tipo_medicion": "glicemia", "valor": 156.0, "fecha_examen": date(2026, 8, 12)})
    repo.aplicar_registro(registro.evidencias(), registro.mensajes(), "PAC-HLF-00002")
    externas = [m for m in repo.historias["PAC-HLF-00002"].mediciones.get("glicemia", []) if m.ref == f"externa:{ide}"]
    assert len(externas) == 1 and externas[0].valor == 156.0                  # recién ahora cuenta

    with pytest.raises(psycopg.errors.RaiseException):                        # la propuesta es auditoría: no se edita
        base.execute("UPDATE canal.lectura_examen SET valor_propuesto = '999' WHERE id_evidencia = %s", (ide,))


@pytest.mark.datos
@pytest.mark.skipif(not URL, reason="Requiere PostgreSQL")
def test_archivo_infectado_no_se_lee_ni_se_valida(base, monkeypatch):
    import psycopg
    from api.rutas import examenes
    from priorizacion import config
    from servicios.ocr_examenes import proceso
    monkeypatch.setattr(config, "S3_BUCKET", "bucket-prueba")
    monkeypatch.setattr(config, "EXAMENES_ESCANEO", True)
    with base.transaction():
        r = examenes.crear_evidencia(base, "PAC-HLF-00028", "hlf/canal/evidencias/PAC-HLF-00028/x/f.png",
                                     s3=S3Falso(b"\x89PNG", "image/png"))
    ide = r["id_evidencia"]
    assert r["escaneo"] == "pendiente"
    with pytest.raises(PermissionError):                                      # sin escaneo limpio no se lee
        proceso.leer(base, ide, textract=TextractFalso("x"), proponer=lambda t: ({}, {}))
    base.execute("UPDATE canal.evidencia_externa SET escaneo_malware = 'infectado', estado_lectura = 'bloqueada' "
                 "WHERE id_evidencia = %s", (ide,))
    with pytest.raises(psycopg.errors.CheckViolation):
        base.execute("UPDATE canal.evidencia_externa SET estado = 'validada', tipo_medicion = 'PHQ9', valor = 5, "
                     "fecha_examen = '2026-09-01', revisado_por = 'administradora', fecha_revision = now() "
                     "WHERE id_evidencia = %s", (ide,))
