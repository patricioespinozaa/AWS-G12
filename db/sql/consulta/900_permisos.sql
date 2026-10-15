-- Permisos del flujo de consulta del equipo clínico. Requiere CREATEROLE.
--   hlf_preparacion_kb : Lambda de preparación. Lee raw, registra ingestas y documentos.
--   hlf_consulta_ia    : Lambda de consulta. Lee qué KB está vigente y registra preguntas y fuentes.
--   hlf_app            : la app web lee el historial de preguntas.
--   CREATE ROLE hlf_lambda_kb LOGIN PASSWORD '...';  GRANT hlf_preparacion_kb TO hlf_lambda_kb;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hlf_preparacion_kb') THEN
        CREATE ROLE hlf_preparacion_kb NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hlf_consulta_ia') THEN
        CREATE ROLE hlf_consulta_ia NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hlf_app') THEN
        CREATE ROLE hlf_app NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA consulta TO hlf_preparacion_kb, hlf_consulta_ia, hlf_app;
GRANT USAGE ON SCHEMA raw TO hlf_preparacion_kb;
GRANT SELECT ON ALL TABLES IN SCHEMA raw TO hlf_preparacion_kb;
GRANT SELECT, INSERT ON consulta.ingesta_kb, consulta.documento_kb TO hlf_preparacion_kb;
GRANT UPDATE (ingestion_job_id, fin, estado, n_documentos, n_fallidos, error) ON consulta.ingesta_kb TO hlf_preparacion_kb;

GRANT SELECT ON consulta.v_kb_vigente, consulta.documento_kb TO hlf_consulta_ia;
GRANT SELECT, INSERT ON consulta.pregunta, consulta.fuente_respuesta TO hlf_consulta_ia;

GRANT SELECT ON ALL TABLES IN SCHEMA consulta TO hlf_app;
