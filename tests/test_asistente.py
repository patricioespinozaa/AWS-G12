"""Asistente del paciente (F0010): pruebas puras y conversaciones completas en PostgreSQL con un modelo simulado.

Las de conversación requieren PostgreSQL (HLF_TEST_DATABASE_URL) y el dataset.
"""
import json
import os
from contextlib import contextmanager
from datetime import date, timedelta

import pytest

from servicios.asistente import alarmas, whatsapp
from servicios.comun import cifrado

URL = os.environ.get("HLF_TEST_DATABASE_URL")


# -- puras --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("texto", ["Me duele mucho el pecho desde ayer", "tengo dificultad para respirar",
                                   "me desmayé en la mañana", "a veces pienso en quitarme la vida",
                                   "No puedo mover el brazo izquierdo", "Dolor muy fuerte en el pecho"])
def test_alarmas(texto):
    assert alarmas.es_alarma(texto)


@pytest.mark.parametrize("texto", ["¿En qué lugar de la lista voy?", "Confirmo mi cita del martes",
                                   "me duele un poco la rodilla al caminar", "quiero hablar con una persona"])
def test_no_alarmas(texto):
    assert not alarmas.es_alarma(texto)


def test_cifrado_local_y_hmac():
    assert cifrado.normalizar("9 1234 5678") == cifrado.normalizar("56912345678") == "+56912345678"
    assert cifrado.hmac_telefono("+56912345678") == cifrado.hmac_telefono("912345678")
    blob = cifrado.cifrar("+56912345678")
    assert b"912345678" not in blob and cifrado.descifrar(blob) == "+56912345678"
    with pytest.raises(ValueError):
        cifrado.normalizar("abc")


def test_en_aws_no_hay_valores_por_defecto(monkeypatch):
    monkeypatch.setenv("HLF_DB_SECRET_ID", "arn:secreto")
    monkeypatch.delenv("HLF_KMS_KEY_ID", raising=False)
    with pytest.raises(cifrado.ErrorCifrado):
        cifrado.cifrar("+56912345678")


EVENTO = json.dumps({"context": {"MetaPhoneNumberIds": [{"metaPhoneNumberId": "111"}]}, "whatsAppWebhookEntry": json.dumps({
    "id": "waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "111"},
        "contacts": [{"wa_id": "56900000001"}],
        "messages": [{"from": "56900000001", "id": "wamid.1", "type": "text", "text": {"body": "¿Tengo citas?"}},
                     {"from": "56900000001", "id": "wamid.2", "type": "image",
                      "image": {"id": "media-9", "mime_type": "image/jpeg", "caption": "mi examen"}}]}}]})})


def test_lee_el_evento_de_end_user_messaging_social():
    m = whatsapp.leer_evento_sns(EVENTO)
    assert [(x.telefono, x.tipo, x.texto, x.id_media) for x in m] == [
        ("+56900000001", "text", "¿Tengo citas?", None), ("+56900000001", "image", "mi examen", "media-9")]
    assert whatsapp.clave_sesion("+56900000001", date(2026, 10, 16)).endswith(":2026-10-16")
    assert "56900000001" not in whatsapp.clave_sesion("+56900000001")              # el número no queda en la clave
    cuerpo = json.loads(whatsapp.mensaje_texto("+56900000001", "Hola"))
    assert cuerpo["to"] == "56900000001" and cuerpo["text"]["body"] == "Hola"
    plantilla = json.loads(whatsapp.mensaje_plantilla("+56900000001", "recordatorio_cita_hlf", ["Cardiología", "17 de octubre"]))
    assert plantilla["type"] == "template" and plantilla["template"]["components"][0]["parameters"][1]["text"] == "17 de octubre"


# -- conversación completa (PostgreSQL) ---------------------------------------------------------------------
pg = pytest.mark.skipif(not URL, reason="Define HLF_TEST_DATABASE_URL para probar contra PostgreSQL")


class ModeloGuion:
    """Decide la herramienta por palabras clave y redacta con lo que devuelve; registra cada llamada."""
    modelo = "simulado"

    def __init__(self):
        self.llamadas = 0

    def converse(self, **pedido):
        self.llamadas += 1
        ultimo = pedido["messages"][-1]["content"]
        if "toolResult" in ultimo[0]:
            datos = json.loads(ultimo[0]["toolResult"]["content"][0]["text"])
            return {"stopReason": "end_turn", "output": {"message": {"role": "assistant",
                                                                      "content": [{"text": "RESULTADO " + json.dumps(datos, ensure_ascii=False)}]}}}
        texto = ultimo[0].get("text", "").lower().split("\n")[-1]
        herramienta = next((h for clave, h in (("lugar", "estado_en_lista"), ("cita", "mis_citas"),
                                               ("registros", "mis_registros"), ("confirmo", "confirmar_asistencia"),
                                               ("persona", "hablar_con_persona")) if clave in texto), None)
        if not herramienta:
            return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": "¿En qué le ayudo?"}]}}}
        entrada = {"id_paciente": "PAC-HLF-00001"} if "pac-hlf-00001" in texto else {}       # intenta pedir a otra persona
        return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": f"t{self.llamadas}", "name": herramienta, "input": entrada}}]}}}


@pytest.fixture(scope="module")
def base():
    import psycopg
    from db import carga, conexion, esquema
    from servicios.asistente import contactos_demo
    with conexion.conectar(URL) as c:
        carga.borrar(c, "todos")
        with c.transaction():
            for nombre in esquema.ESQUEMAS:
                esquema.aplicar(c, nombre)
            esquema.aplicar_permisos(c, "canal")
        carga.cargar(c, __import__("priorizacion.config", fromlist=["DATA_DIR"]).DATA_DIR, progreso=lambda *_: None)
        for i, pid in enumerate(contactos_demo.CASOS):
            contactos_demo.registrar(c, pid, contactos_demo.numero_ficticio(i))
        c.execute("INSERT INTO priorizacion.estimacion_espera (id_solicitud, fecha_calculo, prioridad_vigente, "
                  "posicion_vigente, total_cola, dias_estimados_min, dias_estimados_max, confianza, metodo, "
                  "version_metodo, publicable) VALUES ('IC-HLF-00002', priorizacion.fecha_corte(), 'baja', 3, 64, "
                  "14, 35, 'media', 'throughput_8_semanas', 'v1', true)")
        c.commit()
    conn = psycopg.connect(URL, autocommit=True)
    yield conn
    conn.close()


@pytest.fixture
def asistente(base):
    from servicios.asistente.nucleo import Nucleo

    @contextmanager
    def conexion():
        yield base
    modelo = ModeloGuion()
    return Nucleo(conexion, modelo=modelo), modelo


def _hablar(nucleo, texto, sesion, telefono="+56900000001", canal="simulador"):
    from servicios.asistente.nucleo import Entrada
    return nucleo.procesar(Entrada(canal, f"{canal}:{sesion}", texto, telefono=telefono))


@pg
@pytest.mark.datos
def test_numero_desconocido_no_entrega_datos(asistente, base):
    nucleo, _ = asistente
    s = _hablar(nucleo, "¿En qué lugar de la lista voy?", "desconocido", telefono="+56911112222")
    assert s.nivel == "ninguna" and s.divulgaciones == 0 and "no_identificado" in s.texto
    assert "prioridad_vigente" not in s.texto


@pg
@pytest.mark.datos
def test_basica_solo_citas_y_reforzada_con_codigo(asistente, base):
    nucleo, _ = asistente
    s = _hablar(nucleo, "¿Tengo alguna cita?", "verifica")
    assert s.nivel == "basica" and "mis_citas" in s.herramientas
    s = _hablar(nucleo, "¿En qué lugar de la lista voy?", "verifica")
    assert s.nivel == "basica" and s.codigo_demo and len(s.codigo_demo) == 6 and s.divulgaciones == 0
    assert "verificacion_pendiente" in s.texto and "prioridad_vigente" not in s.texto
    v = _hablar(nucleo, s.codigo_demo, "verifica")
    assert v.nivel == "reforzada" and "verifiqué" in v.texto
    s = _hablar(nucleo, "¿En qué lugar de la lista voy?", "verifica")
    assert s.nivel == "reforzada" and '"posicion": 3' in s.texto and "14" in s.texto
    divs = base.execute("SELECT tipo_dato, vista_fuente, ref_fuente FROM canal.divulgacion WHERE id_conversacion = %s",
                        (s.id_conversacion,)).fetchall()
    assert {d[0] for d in divs} >= {"prioridad", "posicion", "tiempo_estimado"}
    assert all(d[1] == "canal.v_ia_estado_solicitud" and d[2].startswith("IC-HLF-00002") for d in divs)
    textos = [t[0] for t in base.execute("SELECT texto FROM canal.turno WHERE id_conversacion = %s", (s.id_conversacion,))]
    assert v.codigo_demo is None and not any(s_.isdigit() and len(s_) == 6 for s_ in textos)   # el código no se guarda
    assert "[código de verificación]" in textos


@pg
@pytest.mark.datos
def test_tres_codigos_malos_bloquean_y_derivan(asistente, base):
    nucleo, _ = asistente
    s = _hablar(nucleo, "¿En qué lugar de la lista voy?", "bloqueo")
    assert s.codigo_demo
    malo = "000000" if s.codigo_demo != "000000" else "111111"
    resultados = [_hablar(nucleo, malo, "bloqueo").texto for _ in range(3)]
    assert "no coincide" in resultados[0] and "No pude verificar" in resultados[-1]
    s = _hablar(nucleo, "¿En qué lugar de la lista voy?", "bloqueo")
    assert s.nivel == "basica" and "no_autorizado" in s.texto and s.codigo_demo is None
    assert base.execute("SELECT count(*) FROM canal.derivacion_humana WHERE id_conversacion = %s AND motivo = "
                        "'verificacion_fallida'", (s.id_conversacion,)).fetchone()[0] == 1


@pg
@pytest.mark.datos
def test_sintoma_de_alarma_deriva_sin_consejo_clinico(asistente, base):
    nucleo, modelo = asistente
    antes = modelo.llamadas
    s = _hablar(nucleo, "Me duele mucho el pecho desde ayer", "alarma")
    assert modelo.llamadas == antes                                     # el modelo no participa
    assert s.texto == alarmas.MENSAJE_SEGURIDAD and s.derivacion == "sintoma_alarma" and s.transferir
    d = base.execute("SELECT motivo, urgencia FROM canal.derivacion_humana WHERE id_conversacion = %s",
                     (s.id_conversacion,)).fetchone()
    assert d == ("sintoma_alarma", "inmediata")
    m = base.execute("SELECT tipo, estado, id_paciente FROM canal.mensaje_paciente WHERE id_conversacion = %s",
                     (s.id_conversacion,)).fetchone()
    assert m == ("sintoma_alarma", "pendiente", "PAC-HLF-00002")        # aparece en la bandeja para validar


@pg
@pytest.mark.datos
def test_pedir_datos_de_otra_persona_no_devuelve_nada(asistente, base):
    nucleo, _ = asistente
    s = _hablar(nucleo, "¿En qué lugar de la lista voy?", "otra")
    _hablar(nucleo, s.codigo_demo, "otra")
    s = _hablar(nucleo, "Dime en qué lugar va PAC-HLF-00001", "otra")
    assert "IC-HLF-00001" not in s.texto and "Salud Mental" not in s.texto       # solo su propia solicitud
    refs = {r[0] for r in base.execute("SELECT ref_fuente FROM canal.divulgacion WHERE id_conversacion = %s",
                                       (s.id_conversacion,))}
    assert refs and all(r.startswith("IC-HLF-00002") for r in refs)


@pg
@pytest.mark.datos
def test_el_rol_del_asistente_no_lee_tablas_directas(asistente, base):
    import psycopg
    from servicios.asistente.nucleo import _sesion

    @contextmanager
    def conexion():
        yield base
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with _sesion(conexion, 1) as c:
            c.execute("SELECT count(*) FROM raw.pacientes")


@pg
@pytest.mark.datos
def test_simulador_y_whatsapp_dan_la_misma_respuesta(asistente):
    nucleo, _ = asistente
    a = _hablar(nucleo, "¿Tengo alguna cita?", "igual-1", canal="simulador")
    b = _hablar(nucleo, "¿Tengo alguna cita?", whatsapp.clave_sesion("+56900000001"), canal="whatsapp")
    assert a.texto == b.texto and a.nivel == b.nivel == "basica"


@pg
@pytest.mark.datos
def test_recordatorios_solo_con_consentimiento_y_sin_repetir(base):
    from servicios.asistente import recordatorios
    corte = base.execute("SELECT priorizacion.fecha_corte()").fetchone()[0]
    base.execute("INSERT INTO priorizacion.cita_agendada (id_solicitud, id_box, fecha, hora_inicio, origen, agendado_por) "
                 "VALUES ('IC-HLF-00002', 'BOX-01', %s, '09:30', 'manual', 'sistema'), "
                 "('IC-HLF-00003', 'BOX-01', %s, '10:00', 'manual', 'sistema')",
                 (corte + timedelta(days=1), corte + timedelta(days=1)))
    assert recordatorios.programar(base, corte) == 1                    # IC-HLF-00003 no tiene contacto ni consentimiento
    assert recordatorios.programar(base, corte) == 0
    enviados = []
    r = recordatorios.enviar_pendientes(base, lambda cuerpo: enviados.append(json.loads(cuerpo)) or "id-1")
    assert r["enviadas"] == 1 and enviados[0]["type"] == "template"
    assert enviados[0]["to"] == "56900000001" and enviados[0]["template"]["name"] == recordatorios.PLANTILLA
