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

-- Asistente (F0010): el backend toma el rol en cada transacción (SET LOCAL ROLE hlf_asistente_ia), así que el usuario
-- con que se conecta debe ser miembro. Los códigos de un solo uso se crean y se marcan usados.
DO $$
BEGIN
    IF NOT pg_has_role(current_user, 'hlf_asistente_ia', 'MEMBER') THEN
        EXECUTE format('GRANT hlf_asistente_ia TO %I', current_user);
    END IF;
END
$$;
GRANT SELECT, INSERT ON canal.codigo_verificacion TO hlf_asistente_ia;
GRANT UPDATE (intentos, usado_en) ON canal.codigo_verificacion TO hlf_asistente_ia;
GRANT INSERT ON canal.mensaje_paciente, canal.evidencia_externa TO hlf_asistente_ia;
GRANT SELECT (id_conversacion, n_turno, emisor, texto, fecha) ON canal.turno TO hlf_asistente_ia;
GRANT SELECT (es_principal) ON canal.contacto_paciente TO hlf_asistente_ia;   -- elegir el contacto principal
-- Las herramientas registran mensajes y exámenes con la fecha de corte de los datos
GRANT USAGE ON SCHEMA priorizacion TO hlf_asistente_ia;
GRANT EXECUTE ON FUNCTION priorizacion.fecha_corte() TO hlf_asistente_ia;
-- Exámenes externos (F0012): la lectura de la IA la registra la API (hlf_app); el asistente solo crea la evidencia
GRANT SELECT, INSERT ON canal.lectura_examen TO hlf_app;
