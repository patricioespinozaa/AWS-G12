"""Asistente del paciente (F0010 WhatsApp, F0011 voz): un núcleo independiente del canal y adaptadores.

    nucleo.py         turno → verificación → modelo con herramientas → auditoría (lo usan WhatsApp, voz y el simulador)
    verificacion.py   número registrado (básica) y código de un solo uso (reforzada), con intentos y bloqueo
    herramientas.py   una función por herramienta, solo sobre las vistas canal.v_ia_* (rol hlf_asistente_ia)
    alarmas.py        detección determinista de síntomas de alarma: derivan siempre a una persona
    whatsapp.py       evento de AWS End User Messaging Social ↔ núcleo; envío de mensajes y plantillas
    recordatorios.py  recordatorios de cita salientes, solo con consentimiento vigente
"""
