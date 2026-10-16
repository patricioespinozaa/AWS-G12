"""Núcleo del asistente del paciente (F0010), independiente del canal: WhatsApp, voz (F0011) y el simulador de la app.

Por cada mensaje:
1. Conversación por (canal, id_externo); en el primer mensaje, identificación por el número (verificacion.py).
2. Sin pasar por el modelo: un código de 6 dígitos pendiente se verifica aquí (y no queda en el turno), y un síntoma
   de alarma se deriva a una persona con urgencia inmediata y recibe un mensaje fijo de seguridad.
3. El modelo (Claude en Bedrock, con guardrail) responde usando herramientas. Cada herramienta corre en su propia
   transacción con el rol hlf_asistente_ia y la conversación de la sesión: solo ve al paciente verificado. Si falta
   verificación, el núcleo pide el código en lugar de ejecutar la herramienta.
4. Turno del paciente, turno del asistente y cada dato entregado (canal.divulgacion) quedan registrados.
El modelo nunca escribe SQL, nunca ve el número de teléfono ni el código, y nunca decide prioridades.
"""
from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Protocol

from priorizacion import config

from ..comun import bedrock
from . import alarmas, herramientas as H, verificacion as V

log = logging.getLogger("hlf.asistente")
VERSION_PROMPT = "asistente-v1"
ROL = "hlf_asistente_ia"
MAX_ITERACIONES = 4
HISTORIAL_TURNOS = 12
_CODIGO = re.compile(r"^\s*(\d{6})\s*$")

SISTEMA = """Eres el asistente virtual del Hospital Clínico Dra. Eloísa Díaz La Florida para pacientes en lista de espera de especialidad. Hablas en español de Chile, con cercanía y respeto, de usted.

Reglas:
- Solo informas lo que devuelven las herramientas. Nunca inventes datos, fechas ni posiciones.
- No das consejos médicos, no interpretas exámenes ni síntomas, no diagnosticas y no indicas tratamientos. Si te lo piden, ofrece derivar a una persona (herramienta hablar_con_persona con motivo pregunta_clinica).
- La prioridad la decide el equipo clínico. La posición en la lista no es una fecha garantizada de atención: dilo siempre que informes una posición o un tiempo estimado.
- Solo atiendes al paciente de esta conversación. Si piden datos de otra persona, explica que no puedes entregarlos.
- Si una herramienta indica que falta verificar la identidad, explica que se envió un código y pide que lo escriba.
- Si hay registros que se conversan con una persona, no los describas: ofrece derivar.
{formato}"""
FORMATO = {
    "texto": "- Responde en 2 a 4 frases cortas, sin listas largas ni formato markdown.",
    "voz": "- Es una llamada telefónica: responde en 1 o 2 frases cortas, sin listas, sin abreviaturas ni símbolos. "
           "Di las fechas como '14 de octubre'.",
}
SIN_SERVICIO = ("En este momento no puedo responder. Avisé al equipo del hospital para que le contacten. "
                "Si es urgente, llame al SAMU (131).")
BLOQUEO_GUARDRAIL = ("No puedo responder eso por este medio. Si quiere, le derivo con una persona del equipo del "
                     "hospital.")


class Modelo(Protocol):
    def converse(self, **pedido) -> dict: ...


class ModeloBedrock:
    """Converse de Bedrock con el guardrail de F0008. El modelo del asistente puede ser más rápido que el de la app."""

    def __init__(self, modelo: str | None = None):
        self.modelo = modelo or config.ASISTENTE_MODELO_ID

    def converse(self, **pedido) -> dict:
        pedido["modelId"] = self.modelo
        if config.BEDROCK_GUARDRAIL_ID:
            pedido["guardrailConfig"] = {"guardrailIdentifier": config.BEDROCK_GUARDRAIL_ID,
                                         "guardrailVersion": config.BEDROCK_GUARDRAIL_VERSION, "trace": "disabled"}
        return bedrock.cliente().converse(**pedido)


@dataclass
class Entrada:
    canal: str                     # whatsapp | voz | simulador
    id_externo: str                # sesión: wa:<hmac>:<día>, ContactId de Connect, sim:<uuid>
    texto: str
    telefono: str | None = None    # E.164 del que escribe o llama (nunca va al modelo ni a los logs)
    formato: str = "texto"         # texto | voz
    confianza_asr: float | None = None


@dataclass
class Salida:
    texto: str
    id_conversacion: int
    nivel: str
    herramientas: list[str] = field(default_factory=list)
    divulgaciones: int = 0
    derivacion: str | None = None  # motivo, si se derivó en este turno
    transferir: bool = False       # voz: pasar a la cola humana
    codigo_demo: str | None = None  # solo simulador: el código que en producción llega por SMS
    latencia_ms: int = 0


@contextmanager
def _sesion(conexion, id_conversacion: int | None = None):
    """Una transacción con el rol del asistente y (si se conoce) la conversación de la sesión."""
    with conexion() as conn:
        with conn.transaction():
            conn.execute(f"SET LOCAL ROLE {ROL}")
            if id_conversacion is not None:
                conn.execute("SELECT set_config('canal.id_conversacion', %s, true)", (str(id_conversacion),))
            yield conn


def _nuevo_turno(conn, id_conversacion: int, emisor: str, texto: str, intencion: str | None = None,
                 confianza_asr: float | None = None) -> int:
    n = conn.execute("SELECT coalesce(max(n_turno), 0) + 1 FROM canal.turno WHERE id_conversacion = %s",
                     (id_conversacion,)).fetchone()[0]
    conn.execute("INSERT INTO canal.turno (id_conversacion, n_turno, emisor, texto, intencion, confianza_asr) "
                 "VALUES (%s, %s, %s, %s, %s, %s)", (id_conversacion, n, emisor, texto[:4000], intencion, confianza_asr))
    return n


class Nucleo:
    def __init__(self, conexion: Callable, modelo: Modelo | None = None,
                 enviar_sms: Callable[[str, str], bool] | None = None, buscar_faq: Callable | None = None):
        """`conexion()` devuelve un context manager con una conexión psycopg en autocommit."""
        self.conexion = conexion
        self.modelo = modelo or ModeloBedrock()
        self.enviar_sms = enviar_sms
        self.buscar_faq = buscar_faq

    # -- conversación ---------------------------------------------------------------------------------
    def _conversacion(self, conn, e: Entrada) -> int:
        modelo = getattr(self.modelo, "modelo", "simulado")
        fila = conn.execute(
            "INSERT INTO canal.conversacion (canal, direccion, id_externo, modelo_ia, version_prompt) "
            "VALUES (%s, 'entrante', %s, %s, %s) ON CONFLICT (canal, id_externo) DO NOTHING RETURNING id_conversacion",
            (e.canal, e.id_externo, modelo, VERSION_PROMPT)).fetchone()
        if fila:
            conn.execute("SELECT set_config('canal.id_conversacion', %s, true)", (str(fila[0]),))
            V.identificar(conn, fila[0], e.canal, e.telefono)
            return fila[0]
        return conn.execute("SELECT id_conversacion FROM canal.conversacion WHERE canal = %s AND id_externo = %s",
                            (e.canal, e.id_externo)).fetchone()[0]

    def _enviar_codigo(self, e: Entrada) -> Callable[[str], str | None]:
        def enviar(codigo: str):
            if e.canal == "simulador":
                return "simulador"
            if self.enviar_sms and e.telefono and self.enviar_sms(e.telefono, codigo):
                return "sms"
            return None
        return enviar

    # -- un mensaje -----------------------------------------------------------------------------------
    def procesar(self, e: Entrada) -> Salida:
        t0 = time.perf_counter()
        texto = (e.texto or "").strip()[:2000]
        with _sesion(self.conexion) as conn:
            id_conv = self._conversacion(conn, e)
            conn.execute("SELECT set_config('canal.id_conversacion', %s, true)", (str(id_conv),))
            ident = V.estado(conn, id_conv)
            salida = Salida("", id_conv, ident.nivel)
            # 1. Código de verificación: se resuelve aquí y no se guarda
            if ident.codigo_pendiente and (m := _CODIGO.match(texto)):
                _nuevo_turno(conn, id_conv, "paciente", "[código de verificación]", confianza_asr=e.confianza_asr)
                resultado = V.verificar_codigo(conn, id_conv, m.group(1))
                salida.texto = {
                    "exitosa": "Gracias, verifiqué su identidad. ¿Qué le gustaría consultar?",
                    "fallida": "El código no coincide. Revise el mensaje y escríbalo de nuevo.",
                    "bloqueada": "No pude verificar su identidad. Una persona del equipo del hospital le contactará.",
                }[resultado]
                if resultado == "bloqueada":
                    salida.derivacion = "verificacion_fallida"
                salida.nivel = "reforzada" if resultado == "exitosa" else salida.nivel
                return self._cerrar(conn, id_conv, salida, None, [], t0)
            _nuevo_turno(conn, id_conv, "paciente", texto, confianza_asr=e.confianza_asr)
            # 2. Síntoma de alarma: nunca pasa por el modelo
            if alarmas.es_alarma(texto):
                if ident.id_paciente:
                    conn.execute(
                        "INSERT INTO canal.mensaje_paciente (id_paciente, id_conversacion, canal_origen, fecha, tipo, "
                        "detalle, estado) VALUES (%s, %s, %s, priorizacion.fecha_corte(), 'sintoma_alarma', %s, 'pendiente')",
                        (ident.id_paciente, id_conv, "web" if e.canal == "simulador" else e.canal, texto[:500]))
                conn.execute("INSERT INTO canal.derivacion_humana (id_conversacion, motivo, urgencia) "
                             "VALUES (%s, 'sintoma_alarma', 'inmediata')", (id_conv,))
                salida.texto, salida.derivacion, salida.transferir = alarmas.MENSAJE_SEGURIDAD, "sintoma_alarma", True
                return self._cerrar(conn, id_conv, salida, "reportar_sintoma", [], t0)
            historial = self._historial(conn, id_conv)
        # 3. Modelo con herramientas, fuera de la transacción (puede tardar segundos)
        divulgaciones, usadas, intencion = [], [], None
        try:
            texto_respuesta, guardrail = self._dialogo(e, id_conv, historial, divulgaciones, usadas, salida)
        except Exception as ex:  # noqa: BLE001 — sin modelo, se deriva
            log.warning("Asistente sin modelo: %s", type(ex).__name__)
            texto_respuesta, guardrail = SIN_SERVICIO, False
            salida.derivacion = "baja_confianza"
        if guardrail:
            texto_respuesta, salida.derivacion = BLOQUEO_GUARDRAIL, salida.derivacion or "pregunta_clinica"
        for nombre in usadas:
            if H.CATALOGO[nombre][3]:
                intencion = H.CATALOGO[nombre][3]
                break
        if "hablar_con_persona" in usadas:
            salida.transferir = True
            salida.derivacion = salida.derivacion or "pide_persona"
        salida.texto = texto_respuesta
        with _sesion(self.conexion, id_conv) as conn:
            if salida.derivacion in ("baja_confianza", "pregunta_clinica") and "hablar_con_persona" not in usadas:
                conn.execute("INSERT INTO canal.derivacion_humana (id_conversacion, motivo, urgencia) "
                             "VALUES (%s, %s, 'normal')", (id_conv, salida.derivacion))
            salida.nivel = V.estado(conn, id_conv).nivel
            return self._cerrar(conn, id_conv, salida, intencion, divulgaciones, t0)

    def _cerrar(self, conn, id_conv, salida: Salida, intencion, divulgaciones, t0) -> Salida:
        n = _nuevo_turno(conn, id_conv, "asistente_ia", salida.texto, intencion)
        if divulgaciones:
            id_paciente = conn.execute("SELECT id_paciente FROM canal.conversacion WHERE id_conversacion = %s",
                                       (id_conv,)).fetchone()[0]
            for d in divulgaciones:
                conn.execute("INSERT INTO canal.divulgacion (id_conversacion, n_turno, id_paciente, tipo_dato, "
                             "vista_fuente, ref_fuente, valor_informado) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                             (id_conv, n, id_paciente, d.tipo_dato, d.vista_fuente, d.ref_fuente, d.valor_informado[:500]))
        salida.divulgaciones = len(divulgaciones)
        salida.latencia_ms = round((time.perf_counter() - t0) * 1000)
        bedrock.registrar("asistente", canal=conn.execute("SELECT canal FROM canal.conversacion WHERE id_conversacion = %s",
                                                          (id_conv,)).fetchone()[0],
                          id_conversacion=id_conv, nivel=salida.nivel, herramientas=salida.herramientas,
                          divulgaciones=salida.divulgaciones, derivacion=salida.derivacion, latencia_ms=salida.latencia_ms)
        return salida

    def _historial(self, conn, id_conv: int) -> list[dict]:
        filas = conn.execute("SELECT emisor, texto FROM canal.turno WHERE id_conversacion = %s ORDER BY n_turno DESC "
                             "LIMIT %s", (id_conv, HISTORIAL_TURNOS)).fetchall()[::-1]
        mensajes: list[dict] = []
        for emisor, texto in filas:
            rol = "user" if emisor == "paciente" else "assistant"
            if mensajes and mensajes[-1]["role"] == rol:
                mensajes[-1]["content"][0]["text"] += "\n" + texto
            else:
                mensajes.append({"role": rol, "content": [{"text": texto}]})
        while mensajes and mensajes[0]["role"] != "user":       # Converse empieza con el usuario
            mensajes.pop(0)
        return mensajes

    def _dialogo(self, e: Entrada, id_conv: int, mensajes: list[dict], divulgaciones: list, usadas: list,
                 salida: Salida) -> tuple[str, bool]:
        sistema = SISTEMA.format(formato=FORMATO.get(e.formato, FORMATO["texto"]))
        herramientas = H.especificaciones(list(H.CATALOGO))
        for _ in range(MAX_ITERACIONES):
            r = self.modelo.converse(system=[{"text": sistema}], messages=mensajes,
                                     inferenceConfig={"maxTokens": 400 if e.formato == "voz" else 700},
                                     toolConfig={"tools": herramientas})
            if r.get("stopReason") == "guardrail_intervened":
                return "", True
            contenido = r.get("output", {}).get("message", {}).get("content", [])
            mensajes.append({"role": "assistant", "content": contenido})
            usos = [b["toolUse"] for b in contenido if "toolUse" in b]
            if not usos:
                return "".join(b.get("text", "") for b in contenido).strip() or SIN_SERVICIO, False
            resultados = []
            for uso in usos:
                datos = self._herramienta(e, id_conv, uso["name"], uso.get("input") or {}, divulgaciones, salida)
                usadas.append(uso["name"])
                resultados.append({"toolResult": {"toolUseId": uso["toolUseId"],
                                                  "content": [{"text": json.dumps(datos, ensure_ascii=False, default=str)}]}})
            mensajes.append({"role": "user", "content": resultados})
        return SIN_SERVICIO, False

    def _herramienta(self, e: Entrada, id_conv: int, nombre: str, args: dict, divulgaciones: list,
                     salida: Salida) -> dict:
        if nombre not in H.CATALOGO:
            return {"error": "herramienta desconocida"}
        salida.herramientas.append(nombre)
        minimo = H.CATALOGO[nombre][2]
        with _sesion(self.conexion, id_conv) as conn:
            ident = V.estado(conn, id_conv)
            if not V.suficiente(ident.nivel, minimo):
                if not ident.id_paciente:
                    return {"estado": "no_identificado",
                            "mensaje": "Este número no está registrado o no tiene consentimiento para el asistente. "
                                       "Solo se puede entregar información general."}
                if minimo == "reforzada":
                    if ident.bloqueada or not ident.puede_reforzar:
                        return {"estado": "no_autorizado",
                                "mensaje": "No es posible entregar esta información por este medio; ofrece derivar."}
                    if not ident.codigo_pendiente:
                        codigo = V.solicitar_codigo(conn, id_conv, self._enviar_codigo(e))
                        if codigo is None and e.canal != "simulador":
                            return {"estado": "no_autorizado",
                                    "mensaje": "No se pudo enviar el código de verificación; ofrece derivar."}
                        salida.codigo_demo = codigo
                    return {"estado": "verificacion_pendiente",
                            "mensaje": "Se envió un código de 6 dígitos al número registrado. Pídele que lo escriba "
                                       "para continuar."}
            ejecutor = H.EJECUTORES[nombre]
            if nombre in H.CON_CANAL:
                r = ejecutor(conn, args, canal_origen="web" if e.canal == "simulador" else e.canal)
            elif nombre == "preguntas_frecuentes":
                r = ejecutor(conn, args, buscar=self.buscar_faq)
            else:
                r = ejecutor(conn, args)
        divulgaciones.extend(r.divulgaciones)
        if nombre == "hablar_con_persona":
            salida.derivacion = args.get("motivo") or "pide_persona"
        return r.datos
