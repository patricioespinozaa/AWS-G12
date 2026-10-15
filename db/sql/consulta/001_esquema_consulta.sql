-- Esquema consulta: el equipo clínico pregunta en lenguaje natural (flujo A de docs/diagramas/flujos-aws.pdf).
--   * Lambda de preparación: genera los documentos de la Knowledge Base (perfiles, resúmenes, diccionario, FAQ),
--     los sube a S3 kb/ y sincroniza la KB. Aquí queda qué se generó, con qué datos y hasta qué fecha.
--   * Lambda de consulta: responde con RAG (texto) o con SQL en Athena (conteo). Aquí queda cada pregunta,
--     el SQL ejecutado y los documentos citados: toda respuesta del LLM es trazable a su fuente.
-- Requiere raw y priorizacion. Idempotente. Detalle en docs/feature/F0003-flujos-aws-datos.md.

CREATE SCHEMA IF NOT EXISTS consulta;
COMMENT ON SCHEMA consulta IS 'Consulta en lenguaje natural del equipo clínico: documentos de la Knowledge Base y preguntas';

-- Una generación + sincronización de la Knowledge Base -------------------------------------------------
CREATE TABLE IF NOT EXISTS consulta.ingesta_kb (
    id_ingesta        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    knowledge_base_id text NOT NULL,                   -- ID de la KB en Bedrock
    data_source_id    text NOT NULL,                   -- fuente de datos S3 de esa KB
    audiencia         text NOT NULL CHECK (audiencia IN ('equipo_clinico', 'paciente')),
    ingestion_job_id  text UNIQUE,                     -- StartIngestionJob; NULL mientras se preparan los documentos
    fecha_corte       date NOT NULL,                   -- datos usados hasta esta fecha: en la demo no se indexa el futuro
    version_plantilla text NOT NULL,                   -- versión del generador de perfiles y resúmenes
    inicio            timestamptz NOT NULL DEFAULT now(),
    fin               timestamptz,
    estado            text NOT NULL DEFAULT 'preparando' CHECK (estado IN
                        ('preparando', 'sincronizando', 'completa', 'fallida')),
    n_documentos      integer CHECK (n_documentos >= 0),
    n_fallidos        integer CHECK (n_fallidos >= 0),
    error             text,
    CONSTRAINT ingesta_fin_valido CHECK (fin IS NULL OR fin >= inicio),
    CONSTRAINT ingesta_cerrada_con_fin CHECK ((estado IN ('completa', 'fallida')) = (fin IS NOT NULL)),
    CONSTRAINT ingesta_sincronizada_con_job CHECK (estado IN ('preparando', 'fallida') OR ingestion_job_id IS NOT NULL)
);
COMMENT ON TABLE consulta.ingesta_kb IS 'Una generación de documentos y su sincronización con una Knowledge Base de Bedrock';
-- Una sola ingesta en curso por KB
CREATE UNIQUE INDEX IF NOT EXISTS ingesta_en_curso_uq ON consulta.ingesta_kb (knowledge_base_id)
    WHERE estado IN ('preparando', 'sincronizando');

-- Un documento subido a S3 kb/ en una ingesta -----------------------------------------------------------
-- Los perfiles de paciente solo van a la KB del equipo clínico; la del paciente solo tiene textos generales.
CREATE TABLE IF NOT EXISTS consulta.documento_kb (
    id_documento bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_ingesta   bigint NOT NULL REFERENCES consulta.ingesta_kb (id_ingesta),
    tipo         text NOT NULL CHECK (tipo IN
                   ('perfil_paciente', 'resumen_especialidad', 'resumen_box_mes', 'diccionario', 'faq_paciente')),
    clave        text NOT NULL,                        -- id_paciente, especialidad, 'BOX-01/2026-06', etc.
    id_paciente  text REFERENCES raw.pacientes (id_paciente),
    s3_uri       text NOT NULL CHECK (s3_uri LIKE 's3://%'),
    sha256       char(64) NOT NULL,
    metadatos    jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadatos) = 'object'),
                                                      -- metadataAttributes de Bedrock: especialidad, estado, comuna…
    creado_en    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT documento_uq UNIQUE (id_ingesta, tipo, clave),
    CONSTRAINT documento_uri_uq UNIQUE (id_ingesta, s3_uri),
    CONSTRAINT documento_perfil_con_paciente CHECK ((tipo = 'perfil_paciente') = (id_paciente IS NOT NULL))
);
COMMENT ON TABLE consulta.documento_kb IS 'Un documento de la Knowledge Base: qué es, dónde está en S3 y con qué metadatos';
CREATE INDEX IF NOT EXISTS documento_paciente_idx ON consulta.documento_kb (id_paciente) WHERE id_paciente IS NOT NULL;

-- La audiencia del documento es la de su ingesta: un perfil de paciente nunca entra a la KB del paciente
CREATE OR REPLACE FUNCTION consulta.validar_audiencia_documento() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_audiencia text;
BEGIN
    SELECT audiencia INTO v_audiencia FROM consulta.ingesta_kb WHERE id_ingesta = NEW.id_ingesta;
    IF v_audiencia = 'paciente' AND NEW.tipo <> 'faq_paciente' THEN
        RAISE EXCEPTION 'La KB del paciente solo admite faq_paciente (recibió %)', NEW.tipo;
    END IF;
    IF v_audiencia = 'equipo_clinico' AND NEW.tipo = 'faq_paciente' THEN
        RAISE EXCEPTION 'faq_paciente va en la KB del paciente, no en la del equipo clínico';
    END IF;
    RETURN NEW;
END
$$;
DROP TRIGGER IF EXISTS documento_audiencia ON consulta.documento_kb;
CREATE TRIGGER documento_audiencia BEFORE INSERT OR UPDATE ON consulta.documento_kb
    FOR EACH ROW EXECUTE FUNCTION consulta.validar_audiencia_documento();

-- Pregunta del equipo clínico y cómo se respondió. Solo inserciones: la Lambda la registra al terminar. -----
CREATE TABLE IF NOT EXISTS consulta.pregunta (
    id_pregunta         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_usuario          text NOT NULL REFERENCES priorizacion.usuario (id_usuario),
    texto               text NOT NULL CHECK (length(trim(texto)) > 0),
    fecha_corte         date NOT NULL DEFAULT priorizacion.fecha_corte(),
    ruta                text NOT NULL CHECK (ruta IN ('texto', 'conteo', 'rechazada')),
    id_ingesta          bigint REFERENCES consulta.ingesta_kb (id_ingesta), -- KB usada (ruta texto)
    sql_generado        text,                          -- ruta conteo: SQL de solo lectura que generó Claude
    id_consulta_athena  text,                          -- QueryExecutionId, para auditar en Athena
    bytes_escaneados    bigint CHECK (bytes_escaneados >= 0),
    respuesta           text NOT NULL,
    modelo_ia           text NOT NULL,
    version_prompt      text NOT NULL,
    guardrail_intervino boolean NOT NULL DEFAULT false,
    latencia_ms         integer CHECK (latencia_ms >= 0),
    creada_en           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pregunta_texto_con_kb CHECK (ruta <> 'texto' OR id_ingesta IS NOT NULL),
    CONSTRAINT pregunta_conteo_con_sql CHECK ((ruta = 'conteo') = (sql_generado IS NOT NULL AND id_consulta_athena IS NOT NULL))
);
COMMENT ON TABLE consulta.pregunta IS 'Una pregunta del equipo clínico, su ruta (RAG o Athena) y la respuesta entregada';
CREATE INDEX IF NOT EXISTS pregunta_usuario_idx ON consulta.pregunta (id_usuario, creada_en DESC);
DROP TRIGGER IF EXISTS pregunta_solo_insercion ON consulta.pregunta;
CREATE TRIGGER pregunta_solo_insercion BEFORE UPDATE OR DELETE ON consulta.pregunta
    FOR EACH ROW EXECUTE FUNCTION priorizacion.solo_insercion();

-- Documentos que citó una respuesta (ruta texto). Llave natural (pregunta, orden). Solo inserciones.
CREATE TABLE IF NOT EXISTS consulta.fuente_respuesta (
    id_pregunta  bigint NOT NULL REFERENCES consulta.pregunta (id_pregunta),
    orden        smallint NOT NULL CHECK (orden >= 0),
    id_documento bigint NOT NULL REFERENCES consulta.documento_kb (id_documento),
    fragmento    text NOT NULL,                        -- texto recuperado que respalda la respuesta
    puntaje      numeric(6, 5) CHECK (puntaje BETWEEN 0 AND 1),
    PRIMARY KEY (id_pregunta, orden)
);
COMMENT ON TABLE consulta.fuente_respuesta IS 'Fragmento de un documento de la KB citado en una respuesta';
DROP TRIGGER IF EXISTS fuente_solo_insercion ON consulta.fuente_respuesta;
CREATE TRIGGER fuente_solo_insercion BEFORE UPDATE OR DELETE ON consulta.fuente_respuesta
    FOR EACH ROW EXECUTE FUNCTION priorizacion.solo_insercion();

-- KB vigente por audiencia: la última ingesta completa
CREATE OR REPLACE VIEW consulta.v_kb_vigente AS
SELECT DISTINCT ON (knowledge_base_id) knowledge_base_id, audiencia, id_ingesta, fecha_corte, fin AS sincronizada_en,
       n_documentos
FROM consulta.ingesta_kb
WHERE estado = 'completa'
ORDER BY knowledge_base_id, fin DESC, id_ingesta DESC;
COMMENT ON VIEW consulta.v_kb_vigente IS 'Última sincronización completa de cada Knowledge Base';
