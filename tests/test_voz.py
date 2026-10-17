"""Asistente por voz (F0011): formatos hablados, evento de Lex, transferencias y una llamada completa en PostgreSQL."""
import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from servicios.asistente import voz
from servicios.asistente.nucleo import Salida

RAIZ = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("n, palabras", [(0, "cero"), (3, "tres"), (14, "catorce"), (21, "veintiuno"),
                                         (35, "treinta y cinco"), (100, "cien"), (120, "ciento veinte"),
                                         (999, "novecientos noventa y nueve"), (1500, "mil quinientos"),
                                         (21000, "veintiún mil"), (2026, "dos mil veintiséis")])
def test_numeros_en_palabras(n, palabras):
    assert voz.numero_a_palabras(n) == palabras


def test_texto_para_voz():
    t = voz.para_voz("**Está en el lugar 3 de 120**. Rango: 14 a 35 días. Cita el 2026-10-14 a las 09:30 (1 de noviembre).")
    assert t == ("Está en el lugar tres de ciento veinte. Rango: catorce a treinta y cinco días. Cita el catorce de "
                 "octubre a las nueve y treinta (primero de noviembre).")
    assert not any(c.isdigit() for c in t) and "*" not in t
    assert voz.fecha_hablada(date(2026, 10, 1)) == "primero de octubre"


def _evento(texto, modo="Speech", confianza=0.9, atributos=None):
    return {"sessionId": "s1", "inputTranscript": texto, "inputMode": modo,
            "transcriptions": [{"transcriptionConfidence": confianza}],
            "sessionState": {"intent": {"name": "ConsultarEstado", "state": "InProgress"},
                             "sessionAttributes": {"telefono": "+56900000001", "contactId": "c-123", **(atributos or {})}}}


def _salida(texto="Está en el lugar 3 de 120.", **kw):
    base = {"id_conversacion": 7, "nivel": "reforzada"}
    base.update(kw)
    return Salida(texto, **base)


def test_lex_sigue_escuchando_y_lee_el_contexto():
    vistos = []
    r = voz.atender(_evento("en qué lugar voy"), lambda e: vistos.append(e) or _salida())
    assert vistos[0].canal == "voz" and vistos[0].id_externo == "c-123" and vistos[0].telefono == "+56900000001"
    assert vistos[0].formato == "voz" and vistos[0].confianza_asr == 0.9
    assert r["sessionState"]["dialogAction"]["type"] == "ElicitIntent"
    assert r["messages"][0]["content"] == "Está en el lugar tres de ciento veinte."
    assert "transferir" not in r["sessionState"]["sessionAttributes"]


def test_dos_turnos_sin_entender_transfieren():
    nunca = lambda e: pytest.fail("no debe llamar al núcleo")  # noqa: E731
    r1 = voz.atender(_evento("mmm", confianza=0.2), nunca)
    assert r1["sessionState"]["dialogAction"]["type"] == "ElicitIntent" and r1["messages"][0]["content"] == voz.NO_ENTENDI
    r2 = voz.atender(_evento("eee", confianza=0.1, atributos=r1["sessionState"]["sessionAttributes"]), nunca)
    a = r2["sessionState"]["sessionAttributes"]
    assert r2["sessionState"]["dialogAction"]["type"] == "Close" and a["transferir"] == "true"
    assert a["motivo_transferencia"] == "baja_confianza"


@pytest.mark.parametrize("derivacion, urgente", [("pide_persona", "false"), ("sintoma_alarma", "true")])
def test_transferencia_con_motivo_y_resumen(derivacion, urgente):
    r = voz.atender(_evento("quiero hablar con alguien"),
                    lambda e: _salida("Le derivo.", derivacion=derivacion, transferir=True))
    a = r["sessionState"]["sessionAttributes"]
    assert r["sessionState"]["dialogAction"]["type"] == "Close" and a["transferir"] == "true"
    assert a["motivo_transferencia"] == derivacion and a["urgente"] == urgente
    assert "quiero hablar con alguien" in a["resumen_transferencia"]          # el agente no vuelve a preguntar


def test_digitos_no_quedan_en_el_resumen():
    r = voz.atender(_evento("123456", modo="DTMF"), lambda e: _salida("No pude.", derivacion="verificacion_fallida"))
    assert "123456" not in r["sessionState"]["sessionAttributes"]["resumen_transferencia"]


def test_flujo_de_connect():
    flujo = json.loads((RAIZ / "infra" / "connect" / "flujo_entrante.json").read_text(encoding="utf-8"))
    acciones = {a["Identifier"]: a for a in flujo["Actions"]}
    assert flujo["StartAction"] in acciones
    for a in flujo["Actions"]:                                                # toda transición apunta a una acción
        t = a.get("Transitions", {})
        destinos = [t.get("NextAction")] + [c["NextAction"] for c in t.get("Conditions", [])] + \
                   [e["NextAction"] for e in t.get("Errors", [])]
        assert all(d in acciones for d in destinos if d), a["Identifier"]
    consentimiento = acciones["consentimiento"]["Transitions"]
    grabar = [c["NextAction"] for c in consentimiento["Conditions"] if c["Condition"]["Operands"] == ["1"]]
    assert grabar == ["grabar"] and consentimiento["NextAction"] == "sin_grabacion"   # solo con el 1 se graba
    assert all(e["NextAction"] == "sin_grabacion" for e in consentimiento["Errors"])
    assert acciones["asistente"]["Parameters"]["LexV2Bot"]["AliasArn"] == "${LexAliasArn}"
    assert acciones["asistente"]["Parameters"]["LexSessionAttributes"]["telefono"] == "$.CustomerEndpoint.Address"
    assert acciones["elegir_cola"]["Parameters"]["QueueId"] == "${ColaArn}"


# -- llamada completa (PostgreSQL) -----------------------------------------------------------------------
pg = pytest.mark.skipif(not __import__("os").environ.get("HLF_TEST_DATABASE_URL"), reason="Requiere PostgreSQL")


@pytest.fixture(scope="module")
def base():
    from apoyo_asistente import preparar
    conn = preparar()
    yield conn
    conn.close()


@pytest.fixture
def llamada(base):
    """Núcleo con un 'SMS' simulado: el código llega aquí, como llegaría al teléfono del paciente."""
    from apoyo_asistente import ModeloGuion
    from servicios.asistente.nucleo import Nucleo
    sms = []

    @contextmanager
    def conexion():
        yield base
    return Nucleo(conexion, modelo=ModeloGuion(), enviar_sms=lambda tel, codigo: sms.append((tel, codigo)) or True), sms, conexion


@pg
@pytest.mark.datos
def test_llamada_completa_con_codigo_por_teclado(base, llamada):
    nucleo, sms, conexion = llamada
    r = voz.atender(_evento("en qué lugar de la lista voy", atributos={"contactId": "llamada-1", "grabacion": "si"}),
                    nucleo.procesar)
    atr = r["sessionState"]["sessionAttributes"]
    id_conv = int(atr["id_conversacion"])
    assert atr["nivel"] == "basica" and sms and sms[-1][0] == "+56900000001"     # el código va al número que llama
    r = voz.atender(_evento(sms[-1][1], modo="DTMF", atributos=atr), nucleo.procesar)
    atr = r["sessionState"]["sessionAttributes"]
    assert atr["nivel"] == "reforzada"
    r = voz.atender(_evento("en qué lugar de la lista voy", atributos=atr), nucleo.procesar)
    texto = r["messages"][0]["content"]
    assert "tres" in texto and "catorce" in texto and not any(ch.isdigit() for ch in texto)   # todo en palabras
    divs = {d[0] for d in base.execute("SELECT tipo_dato FROM canal.divulgacion WHERE id_conversacion = %s", (id_conv,))}
    assert {"posicion", "tiempo_estimado"} <= divs
    turnos = [t[0] for t in base.execute("SELECT texto FROM canal.turno WHERE id_conversacion = %s", (id_conv,))]
    assert sms[-1][1] not in " ".join(turnos)                                    # los dígitos no se guardan
    conv = base.execute("SELECT canal, uri_grabacion FROM canal.conversacion WHERE id_conversacion = %s", (id_conv,)).fetchone()
    assert conv == ("voz", None)                                                 # la grabación la registra la API
    assert voz.registrar_grabacion(conexion, id_conv, "llamada-1", "s3://bucket/hlf/connect/grabaciones")
    uri = base.execute("SELECT uri_grabacion FROM canal.conversacion WHERE id_conversacion = %s", (id_conv,)).fetchone()[0]
    assert uri == "s3://bucket/hlf/connect/grabaciones/llamada-1/"
    assert base.execute("SELECT count(*) FROM canal.consentimiento WHERE id_conversacion = %s AND "
                        "finalidad = 'grabacion_llamada' AND otorgado", (id_conv,)).fetchone()[0] == 1


@pg
@pytest.mark.datos
def test_sin_consentimiento_no_hay_grabacion(base, llamada):
    nucleo, _, _ = llamada
    r = voz.atender(_evento("tengo citas", atributos={"contactId": "llamada-2", "grabacion": "no"}), nucleo.procesar)
    id_conv = int(r["sessionState"]["sessionAttributes"]["id_conversacion"])
    assert base.execute("SELECT uri_grabacion FROM canal.conversacion WHERE id_conversacion = %s",
                        (id_conv,)).fetchone()[0] is None


@pg
@pytest.mark.datos
def test_pedir_una_persona_transfiere_con_motivo(base, llamada):
    nucleo, _, _ = llamada
    r = voz.atender(_evento("quiero hablar con una persona", atributos={"contactId": "llamada-3"}), nucleo.procesar)
    a = r["sessionState"]["sessionAttributes"]
    assert r["sessionState"]["dialogAction"]["type"] == "Close" and a["transferir"] == "true"
    assert a["motivo_transferencia"] == "pide_persona"
    id_conv = int(a["id_conversacion"])
    assert base.execute("SELECT motivo FROM canal.derivacion_humana WHERE id_conversacion = %s",
                        (id_conv,)).fetchone()[0] == "pide_persona"
