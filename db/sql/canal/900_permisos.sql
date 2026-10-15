-- Permisos del canal del paciente. Requiere CREATEROLE.
--   hlf_app           : la bandeja clínica revisa mensajes, evidencias y derivaciones.
--   hlf_asistente_ia  : el backend de WhatsApp/voz (Lambda). Solo lee las vistas v_ia_* (filtradas por el
--                       paciente verificado) y registra la conversación. No ve teléfonos ni tablas raw.
--   CREATE ROLE hlf_bot LOGIN PASSWORD '...';  GRANT hlf_asistente_ia TO hlf_bot;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hlf_app') THEN
        CREATE ROLE hlf_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hlf_asistente_ia') THEN
        CREATE ROLE hlf_asistente_ia NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA canal TO hlf_app, hlf_asistente_ia;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA canal TO hlf_app;

-- Asistente: identificar al que llama (sin ver el número), consultar y registrar
GRANT SELECT ON canal.intencion, canal.v_consentimiento_vigente TO hlf_asistente_ia;
GRANT EXECUTE ON FUNCTION canal.paciente_verificado(text) TO hlf_asistente_ia;
GRANT SELECT (id_contacto, id_paciente, tipo, valor_hash, relacion, autorizado_informacion, vigente)
    ON canal.contacto_paciente TO hlf_asistente_ia;
GRANT SELECT ON canal.v_ia_estado_solicitud, canal.v_ia_citas, canal.v_ia_registros TO hlf_asistente_ia;
GRANT SELECT, INSERT ON canal.conversacion, canal.verificacion_identidad, canal.turno, canal.divulgacion,
    canal.derivacion_humana, canal.consentimiento TO hlf_asistente_ia;
GRANT UPDATE (id_paciente, id_contacto, nivel_verificacion, fin, estado, uri_grabacion)
    ON canal.conversacion TO hlf_asistente_ia;
GRANT INSERT ON canal.mensaje_paciente, canal.evidencia_externa TO hlf_asistente_ia;
GRANT UPDATE (estado, enviada_en, intentos, id_conversacion, error) ON canal.notificacion TO hlf_asistente_ia;
GRANT SELECT ON canal.notificacion TO hlf_asistente_ia;
