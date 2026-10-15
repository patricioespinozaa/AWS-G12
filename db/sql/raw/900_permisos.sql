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

-- F0005: cargas incrementales. Agregan y actualizan filas de raw, pero nunca borran (no hay DELETE).
--   GRANT hlf_cargas TO hlf_api;   (el usuario de la API, que atiende la vista Cargas)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hlf_cargas') THEN
        CREATE ROLE hlf_cargas NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA raw TO hlf_cargas;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA raw TO hlf_cargas;
REVOKE DELETE, TRUNCATE ON ALL TABLES IN SCHEMA raw FROM hlf_cargas;
