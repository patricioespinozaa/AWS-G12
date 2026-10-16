"""Verificación de identidad del paciente (F0010, niveles de F0002).

- ninguna: número desconocido o sin consentimiento → solo información general (preguntas frecuentes).
- basica: el número está registrado (canal.contacto_paciente, por HMAC) y hay consentimiento vigente para el
  asistente → citas, confirmar o avisar inasistencia, reportar síntomas, enviar exámenes.
- reforzada: además, un código de un solo uso enviado al número registrado (SMS; en el simulador se muestra en
  pantalla) → prioridad, posición, tiempo estimado y registros clínicos.
Un tercero (cuidador, familiar) sin `autorizado_informacion` nunca llega a reforzada. Tres códigos fallidos bloquean
la conversación y la derivan a una persona. Nunca se guarda el código ni lo que respondió el paciente.
"""
from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass

from ..comun import cifrado

INTENTOS_MAX = 3
CODIGOS_MAX = 3
VIGENCIA_MIN = 5
NIVELES = ("ninguna", "basica", "reforzada")


@dataclass
class Identidad:
    id_paciente: str | None
    nivel: str
    puede_reforzar: bool
    bloqueada: bool
    codigo_pendiente: bool


def suficiente(nivel: str, minimo: str) -> bool:
    return NIVELES.index(nivel) >= NIVELES.index(minimo)


def _canal_consentimiento(canal: str) -> str:
    return "voz" if canal == "voz" else "whatsapp"            # el simulador usa el consentimiento de WhatsApp


def identificar(conn, id_conversacion: int, canal: str, telefono: str | None) -> None:
    """Primer mensaje de la conversación: busca el número por HMAC y otorga el nivel básico si corresponde."""
    if not telefono:
        return
    try:
        valor_hash = cifrado.hmac_telefono(telefono)
    except ValueError:
        return
    fila = conn.execute(
        "SELECT cp.id_contacto, cp.id_paciente FROM canal.contacto_paciente cp "
        "JOIN canal.v_consentimiento_vigente cv ON cv.id_paciente = cp.id_paciente AND cv.canal = %s "
        "AND cv.finalidad = 'asistente_ia' AND cv.otorgado "
        "WHERE cp.valor_hash = %s AND cp.vigente ORDER BY cp.es_principal DESC, cp.relacion = 'titular' DESC, "
        "cp.id_contacto LIMIT 1", (_canal_consentimiento(canal), valor_hash)).fetchone()
    if fila is None:
        conn.execute("INSERT INTO canal.verificacion_identidad (id_conversacion, metodo, resultado, nivel_otorgado) "
                     "VALUES (%s, 'numero_registrado', 'fallida', 'ninguna')", (id_conversacion,))
        return
    conn.execute("UPDATE canal.conversacion SET id_contacto = %s, id_paciente = %s, nivel_verificacion = 'basica' "
                 "WHERE id_conversacion = %s", (fila[0], fila[1], id_conversacion))
    conn.execute("INSERT INTO canal.verificacion_identidad (id_conversacion, metodo, resultado, nivel_otorgado) "
                 "VALUES (%s, 'numero_registrado', 'exitosa', 'basica')", (id_conversacion,))


def estado(conn, id_conversacion: int) -> Identidad:
    c = conn.execute(
        "SELECT c.id_paciente, c.nivel_verificacion, coalesce(cp.relacion = 'titular' OR cp.autorizado_informacion, false) "
        "FROM canal.conversacion c LEFT JOIN canal.contacto_paciente cp USING (id_contacto) WHERE c.id_conversacion = %s",
        (id_conversacion,)).fetchone()
    bloqueada = conn.execute("SELECT EXISTS (SELECT 1 FROM canal.verificacion_identidad WHERE id_conversacion = %s "
                             "AND resultado = 'bloqueada')", (id_conversacion,)).fetchone()[0]
    pendiente = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM canal.codigo_verificacion WHERE id_conversacion = %s AND usado_en IS NULL "
        "AND expira_en > now() AND intentos < %s)", (id_conversacion, INTENTOS_MAX)).fetchone()[0]
    return Identidad(c[0], c[1], bool(c[0]) and bool(c[2]), bloqueada, pendiente)


def solicitar_codigo(conn, id_conversacion: int, enviar) -> str | None:
    """Genera y envía un código. `enviar(codigo)` lo manda por SMS y devuelve 'sms', o devuelve 'simulador' si se
    muestra en pantalla. Devuelve el código solo en el simulador (para la demo); None si no se pudo pedir."""
    ident = estado(conn, id_conversacion)
    if ident.bloqueada or not ident.puede_reforzar:
        return None
    emitidos = conn.execute("SELECT count(*) FROM canal.codigo_verificacion WHERE id_conversacion = %s",
                            (id_conversacion,)).fetchone()[0]
    if emitidos >= CODIGOS_MAX:
        return None
    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    medio = enviar(codigo)
    conn.execute("INSERT INTO canal.codigo_verificacion (id_conversacion, hash_codigo, enviado_por, expira_en) "
                 "VALUES (%s, %s, %s, now() + make_interval(mins => %s))",
                 (id_conversacion, cifrado.hmac_texto(f"otp:{id_conversacion}:{codigo}"), medio, VIGENCIA_MIN))
    return codigo if medio == "simulador" else None


def verificar_codigo(conn, id_conversacion: int, codigo: str) -> str:
    """'exitosa', 'fallida' o 'bloqueada'. El código no se guarda ni se compara en texto plano."""
    fila = conn.execute(
        "SELECT id_codigo, hash_codigo FROM canal.codigo_verificacion WHERE id_conversacion = %s AND usado_en IS NULL "
        "AND expira_en > now() AND intentos < %s ORDER BY creado_en DESC LIMIT 1",
        (id_conversacion, INTENTOS_MAX)).fetchone()
    esperado = cifrado.hmac_texto(f"otp:{id_conversacion}:{codigo}")
    if fila and hmac.compare_digest(fila[1], esperado):
        conn.execute("UPDATE canal.codigo_verificacion SET usado_en = now() WHERE id_codigo = %s", (fila[0],))
        conn.execute("UPDATE canal.conversacion SET nivel_verificacion = 'reforzada' WHERE id_conversacion = %s",
                     (id_conversacion,))
        conn.execute("INSERT INTO canal.verificacion_identidad (id_conversacion, metodo, resultado, nivel_otorgado) "
                     "VALUES (%s, 'codigo_sms', 'exitosa', 'reforzada')", (id_conversacion,))
        return "exitosa"
    if fila:
        conn.execute("UPDATE canal.codigo_verificacion SET intentos = intentos + 1 WHERE id_codigo = %s", (fila[0],))
    fallidas = conn.execute("SELECT count(*) FROM canal.verificacion_identidad WHERE id_conversacion = %s "
                            "AND metodo = 'codigo_sms' AND resultado = 'fallida'", (id_conversacion,)).fetchone()[0] + 1
    if fallidas >= INTENTOS_MAX:
        conn.execute("INSERT INTO canal.verificacion_identidad (id_conversacion, metodo, resultado, nivel_otorgado) "
                     "VALUES (%s, 'codigo_sms', 'bloqueada', 'ninguna')", (id_conversacion,))
        conn.execute("INSERT INTO canal.derivacion_humana (id_conversacion, motivo, urgencia) "
                     "VALUES (%s, 'verificacion_fallida', 'normal')", (id_conversacion,))
        return "bloqueada"
    conn.execute("INSERT INTO canal.verificacion_identidad (id_conversacion, metodo, resultado, nivel_otorgado) "
                 "VALUES (%s, 'codigo_sms', 'fallida', 'ninguna')", (id_conversacion,))
    return "fallida"
