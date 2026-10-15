-- Rol de la aplicación (API de la bandeja clínica): lee raw y escribe priorizacion. Requiere CREATEROLE.
--   CREATE ROLE hlf_api LOGIN PASSWORD '...';  GRANT hlf_lectura_raw, hlf_app TO hlf_api;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hlf_app') THEN
        CREATE ROLE hlf_app NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA priorizacion TO hlf_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA priorizacion TO hlf_app;
-- El proceso nocturno reemplaza su serie y sus propuestas; decision_clinica sigue protegida por trigger
GRANT DELETE ON priorizacion.serie_nocturna, priorizacion.propuesta_prioridad, priorizacion.factor_propuesta TO hlf_app;
