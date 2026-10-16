-- Caché de explicaciones redactadas por IA (F0008). Idempotente.
--
-- Guarda solo textos ACEPTADOS por validar_texto_llm, por huella de los datos de la propuesta (huella_datos), modelo
-- y versión del prompt. La misma propuesta con los mismos datos no vuelve a llamar a Bedrock, desde cualquier tarea.
-- No contiene datos clínicos nuevos: el texto solo puede citar factores que ya están en la base.
CREATE TABLE IF NOT EXISTS priorizacion.explicacion_ia (
    huella_datos   text NOT NULL,
    modelo         text NOT NULL,
    version_prompt text NOT NULL,
    id_solicitud   text NOT NULL REFERENCES raw.lista_espera (id_solicitud),
    texto          text NOT NULL CHECK (length(trim(texto)) > 0),
    creado_en      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (huella_datos, modelo, version_prompt)
);
COMMENT ON TABLE priorizacion.explicacion_ia IS
    'Textos de Bedrock ya validados, por huella de los datos, modelo y versión del prompt (F0008)';
CREATE INDEX IF NOT EXISTS explicacion_ia_solicitud_idx ON priorizacion.explicacion_ia (id_solicitud);
