"""Recordatorios de cita salientes (F0010): canal.notificacion → plantilla aprobada de WhatsApp.

- `programar`: una notificación por cada cita agendada para el día siguiente a la fecha de corte, solo si el paciente
  tiene consentimiento vigente de recordatorios por WhatsApp y un contacto de WhatsApp vigente. Nunca se repite.
- `enviar_pendientes`: envía las programadas con la plantilla aprobada (WhatsApp exige plantillas para iniciar una
  conversación) y deja el resultado. Sin WhatsApp configurado, quedan programadas.
Lo corre la consolidación nocturna después de recalcular.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..comun import cifrado
from . import whatsapp

PLANTILLA = "recordatorio_cita_hlf"
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")


def programar(conn, fecha_corte: date) -> int:
    manana = fecha_corte + timedelta(days=1)
    with conn.transaction():
        return conn.execute(
            "INSERT INTO canal.notificacion (id_paciente, id_contacto, canal, tipo, id_cita_agendada, plantilla, "
            "programada_para, creada_por) "
            "SELECT le.id_paciente, cp.id_contacto, 'whatsapp', 'recordatorio_cita', ca.id_cita_agendada, %s, now(), 'sistema' "
            "FROM priorizacion.cita_agendada ca JOIN raw.lista_espera le USING (id_solicitud) "
            "JOIN canal.v_consentimiento_vigente cv ON cv.id_paciente = le.id_paciente AND cv.canal = 'whatsapp' "
            "  AND cv.finalidad = 'recordatorios' AND cv.otorgado "
            "JOIN LATERAL (SELECT id_contacto FROM canal.contacto_paciente c WHERE c.id_paciente = le.id_paciente "
            "  AND c.tipo = 'whatsapp' AND c.vigente ORDER BY c.es_principal DESC, c.id_contacto LIMIT 1) cp ON true "
            "WHERE ca.fecha = %s AND ca.estado IN ('programada', 'confirmada') AND NOT EXISTS ("
            "  SELECT 1 FROM canal.notificacion n WHERE n.id_cita_agendada = ca.id_cita_agendada "
            "  AND n.tipo = 'recordatorio_cita')", (PLANTILLA, manana)).rowcount


def _fecha_hablada(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]}"


def enviar_pendientes(conn, enviar_fn=None) -> dict:
    """`enviar_fn(cuerpo) → id` envía por WhatsApp; sin ella no se envía nada (quedan programadas)."""
    if enviar_fn is None:
        n = conn.execute("SELECT count(*) FROM canal.notificacion WHERE estado = 'programada'").fetchone()[0]
        return {"programadas": n, "enviadas": 0, "fallidas": 0}
    filas = conn.execute(
        "SELECT n.id_notificacion, cp.valor_cifrado, le.especialidad, ca.fecha, ca.hora_inicio "
        "FROM canal.notificacion n JOIN canal.contacto_paciente cp USING (id_contacto) "
        "JOIN priorizacion.cita_agendada ca USING (id_cita_agendada) JOIN raw.lista_espera le USING (id_solicitud) "
        "WHERE n.estado = 'programada' AND n.programada_para <= now() AND n.canal = 'whatsapp' "
        "ORDER BY n.programada_para LIMIT 500").fetchall()
    enviadas = fallidas = 0
    for id_n, cifrado_tel, especialidad, fecha, hora in filas:
        try:
            telefono = cifrado.descifrar(cifrado_tel)
            enviar_fn(whatsapp.mensaje_plantilla(telefono, PLANTILLA, [
                especialidad, _fecha_hablada(fecha), hora.strftime("%H:%M") if hora else "la hora indicada"]))
            conn.execute("UPDATE canal.notificacion SET estado = 'enviada', enviada_en = now(), intentos = intentos + 1 "
                         "WHERE id_notificacion = %s", (id_n,))
            enviadas += 1
        except Exception as e:  # noqa: BLE001
            conn.execute("UPDATE canal.notificacion SET estado = CASE WHEN intentos >= 2 THEN 'fallida' ELSE estado END, "
                         "intentos = intentos + 1, error = %s WHERE id_notificacion = %s", (type(e).__name__, id_n))
            fallidas += 1
    return {"programadas": len(filas) - enviadas - fallidas, "enviadas": enviadas, "fallidas": fallidas}
