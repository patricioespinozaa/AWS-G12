"""Adaptador de voz (F0011): Amazon Connect → Lex V2 → (Lambda) → API → núcleo del asistente → Lex → Polly.

- Lex reconoce la voz (o los dígitos del teclado) y entrega el texto; el núcleo responde con frases cortas.
- `para_voz`: cifras y fechas en palabras ("lugar tres de ciento veinte", "catorce de octubre"), sin símbolos.
- Transferencia a la cola humana (atributos de sesión que lee el flujo de Connect): síntoma de alarma, pedir una
  persona, verificación bloqueada o dos turnos sin entender. El resumen va en `resumen_transferencia` para que el
  agente no vuelva a preguntar lo mismo.
- Los dígitos marcados (código) no se transcriben ni se guardan: el núcleo los resuelve sin registrarlos.
"""
from __future__ import annotations

import re
from datetime import date

UNIDADES = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
            "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno",
            "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho",
            "veintinueve"]
DECENAS = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}
CENTENAS = {1: "ciento", 2: "doscientos", 3: "trescientos", 4: "cuatrocientos", 5: "quinientos", 6: "seiscientos",
            7: "setecientos", 8: "ochocientos", 9: "novecientos"}
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")
CONFIANZA_MINIMA = 0.4
FALLOS_PARA_TRANSFERIR = 2
NO_ENTENDI = "Disculpe, no le entendí. ¿Me lo puede repetir con otras palabras?"
TRANSFIRIENDO = "Le comunico con una persona del equipo del hospital. Por favor, no corte."


def numero_a_palabras(n: int) -> str:
    if n < 0:
        return "menos " + numero_a_palabras(-n)
    if n < 30:
        return UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        return DECENAS[d] + (f" y {UNIDADES[u]}" if u else "")
    if n == 100:
        return "cien"
    if n < 1000:
        c, r = divmod(n, 100)
        return CENTENAS[c] + (f" {numero_a_palabras(r)}" if r else "")
    if n < 1_000_000:
        m, r = divmod(n, 1000)
        prefijo = numero_a_palabras(m)
        prefijo = prefijo[:-3] + "ún" if prefijo.endswith("veintiuno") else (prefijo[:-1] if prefijo.endswith("uno") else prefijo)
        miles = "mil" if m == 1 else f"{prefijo} mil"
        return miles + (f" {numero_a_palabras(r)}" if r else "")
    return str(n)


def fecha_hablada(d: date) -> str:
    return f"{numero_a_palabras(d.day) if d.day != 1 else 'primero'} de {MESES[d.month - 1]}"


def para_voz(texto: str) -> str:
    """Texto listo para Polly: sin markdown ni símbolos, fechas y cifras en palabras."""
    t = re.sub(r"[*_#`>\[\]]", "", texto)
    t = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: fecha_hablada(date(int(m[1]), int(m[2]), int(m[3]))), t)
    t = re.sub(r"\b(\d{1,2}) de (" + "|".join(MESES) + r")\b",
               lambda m: f"{numero_a_palabras(int(m[1])) if m[1] != '1' else 'primero'} de {m[2]}", t)
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: numero_a_palabras(int(m[1])) + (
        f" y {numero_a_palabras(int(m[2]))}" if int(m[2]) else " en punto"), t)
    t = re.sub(r"(\d+),(\d+)", lambda m: f"{numero_a_palabras(int(m[1]))} coma {numero_a_palabras(int(m[2]))}", t)
    t = re.sub(r"\b\d{1,6}\b", lambda m: numero_a_palabras(int(m[0])), t)
    t = t.replace("%", " por ciento").replace("&", " y ").replace("/", " de ")
    return re.sub(r"\s+", " ", t).strip()


# -- evento de Lex V2 ---------------------------------------------------------------------------------------
def leer_evento(evento: dict) -> dict:
    """Lo que necesita el núcleo desde un evento de Lex V2 (code hook de fulfillment o de diálogo)."""
    sesion = evento.get("sessionState", {})
    atributos = dict(sesion.get("sessionAttributes") or {})
    transcripciones = evento.get("transcriptions") or []
    confianza = transcripciones[0].get("transcriptionConfidence") if transcripciones else None
    return {
        "texto": (evento.get("inputTranscript") or "").strip(),
        "modo": evento.get("inputMode", "Speech"),          # Speech | DTMF | Text
        "confianza": confianza,
        "id_externo": atributos.get("contactId") or evento.get("sessionId", ""),
        "telefono": atributos.get("telefono"),
        "intencion": (sesion.get("intent") or {}).get("name"),
        "atributos": atributos,
    }


def respuesta_lex(evento: dict, texto: str, atributos: dict, cerrar: bool) -> dict:
    """Respuesta de Lex V2: sigue escuchando (ElicitIntent) o cierra para que el flujo de Connect transfiera."""
    intencion = dict((evento.get("sessionState") or {}).get("intent") or {"name": "FallbackIntent"})
    intencion["state"] = "Fulfilled"
    accion = {"type": "Close"} if cerrar else {"type": "ElicitIntent"}
    return {"sessionState": {"dialogAction": accion, "intent": intencion,
                             "sessionAttributes": {k: str(v) for k, v in atributos.items()}},
            "messages": [{"contentType": "PlainText", "content": texto}]}


def registrar_grabacion(conexion, id_conversacion: int, contact_id: str, uri_base: str) -> bool:
    """El paciente aceptó la grabación en el flujo de Connect: queda el consentimiento (canal voz, finalidad
    grabacion_llamada) y la URI donde Connect guarda el audio. Sin paciente identificado no se registra nada (y el
    flujo no graba). Devuelve si quedó registrada."""
    from .nucleo import _sesion
    with _sesion(conexion, id_conversacion) as conn:
        fila = conn.execute("SELECT id_paciente FROM canal.conversacion WHERE id_conversacion = %s AND canal = 'voz'",
                            (id_conversacion,)).fetchone()
        if not fila or not fila[0]:
            return False
        conn.execute("INSERT INTO canal.consentimiento (id_paciente, canal, finalidad, otorgado, medio_registro, "
                     "id_conversacion, registrado_por) VALUES (%s, 'voz', 'grabacion_llamada', true, 'voz', %s, "
                     "'asistente_ia')", (fila[0], id_conversacion))
        conn.execute("UPDATE canal.conversacion SET uri_grabacion = %s WHERE id_conversacion = %s",
                     (f"{uri_base.rstrip('/')}/{contact_id}/", id_conversacion))
    return True


def atender(evento: dict, procesar) -> dict:
    """`procesar(Entrada) → Salida` es el núcleo. Decide si se transfiere y devuelve la respuesta para Lex."""
    from .nucleo import Entrada
    e = leer_evento(evento)
    atributos = e["atributos"]
    fallos = int(atributos.get("fallos", "0") or 0)
    if not e["texto"] or (e["modo"] == "Speech" and e["confianza"] is not None and e["confianza"] < CONFIANZA_MINIMA):
        fallos += 1
        atributos["fallos"] = fallos
        if fallos >= FALLOS_PARA_TRANSFERIR:
            atributos.update(transferir="true", motivo_transferencia="baja_confianza",
                             resumen_transferencia="El paciente no fue entendido en dos intentos.")
            return respuesta_lex(evento, TRANSFIRIENDO, atributos, cerrar=True)
        return respuesta_lex(evento, NO_ENTENDI, atributos, cerrar=False)
    s = procesar(Entrada("voz", e["id_externo"], e["texto"], telefono=e["telefono"], formato="voz",
                         confianza_asr=e["confianza"]))
    atributos.update(fallos=0, nivel=s.nivel, id_conversacion=s.id_conversacion)
    if s.transferir or s.derivacion in ("verificacion_fallida", "sintoma_alarma", "pide_persona"):
        motivo = s.derivacion or "pide_persona"
        atributos.update(transferir="true", motivo_transferencia=motivo,
                         urgente="true" if motivo == "sintoma_alarma" else "false",
                         resumen_transferencia=f"Motivo: {motivo}. Verificación: {s.nivel}. Último mensaje del paciente: "
                                               f"{e['texto'][:180] if e['modo'] != 'DTMF' else '(dígitos)'}")
        texto = para_voz(s.texto) + " " + TRANSFIRIENDO
        return respuesta_lex(evento, texto.strip(), atributos, cerrar=True)
    return respuesta_lex(evento, para_voz(s.texto), atributos, cerrar=False)
