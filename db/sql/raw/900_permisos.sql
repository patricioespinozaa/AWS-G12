-- Rol de solo lectura sobre raw para la aplicación. Requiere CREATEROLE (el usuario maestro de RDS lo tiene).
-- Uso: crear el usuario de login de la API y darle este rol:
--   CREATE ROLE hlf_api LOGIN PASSWORD '...';  GRANT hlf_lectura_raw TO hlf_api;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hlf_lectura_raw') THEN
        CREATE ROLE hlf_lectura_raw NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA raw TO hlf_lectura_raw;
GRANT SELECT ON ALL TABLES IN SCHEMA raw TO hlf_lectura_raw;
ALTER DEFAULT PRIVILEGES IN SCHEMA raw GRANT SELECT ON TABLES TO hlf_lectura_raw;
