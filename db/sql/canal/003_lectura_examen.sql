-- Exámenes externos con lectura asistida (F0012). Idempotente.
--
-- * Un examen subido como archivo llega sin tipo ni valor: los propone la lectura con IA y los confirma una persona.
--   Por eso tipo_medicion, valor y fecha_examen pasan a ser opcionales MIENTRAS la evidencia está pendiente; validarla
--   exige los tres (los confirma la Administradora).
-- * La propuesta de la IA va aparte (canal.lectura_examen), con la cita literal del documento de cada campo. Nunca se
--   confunde con el valor validado de canal.evidencia_externa.
-- * El archivo se lee solo si el escaneo de malware (GuardDuty) lo declaró limpio.

ALTER TABLE canal.evidencia_externa ALTER COLUMN tipo_medicion DROP NOT NULL;
ALTER TABLE canal.evidencia_externa ALTER COLUMN valor DROP NOT NULL;
ALTER TABLE canal.evidencia_externa ALTER COLUMN fecha_examen DROP NOT NULL;
ALTER TABLE canal.evidencia_externa ADD COLUMN IF NOT EXISTS escaneo_malware text NOT NULL DEFAULT 'no_aplica';
ALTER TABLE canal.evidencia_externa ADD COLUMN IF NOT EXISTS estado_lectura text NOT NULL DEFAULT 'no_aplica';
ALTER TABLE canal.evidencia_externa ADD COLUMN IF NOT EXISTS tamano_bytes integer CHECK (tamano_bytes > 0);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'evidencia_validada_completa') THEN
        ALTER TABLE canal.evidencia_externa ADD CONSTRAINT evidencia_validada_completa CHECK (
            estado <> 'validada' OR (tipo_medicion IS NOT NULL AND valor IS NOT NULL AND fecha_examen IS NOT NULL));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'evidencia_escaneo_valido') THEN
        ALTER TABLE canal.evidencia_externa ADD CONSTRAINT evidencia_escaneo_valido CHECK (escaneo_malware IN
            ('no_aplica', 'pendiente', 'limpio', 'infectado', 'sin_escaneo'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'evidencia_lectura_valida') THEN
        ALTER TABLE canal.evidencia_externa ADD CONSTRAINT evidencia_lectura_valida CHECK (estado_lectura IN
            ('no_aplica', 'esperando_escaneo', 'leyendo', 'leida', 'fallida', 'bloqueada'));
    END IF;
    -- Un archivo infectado nunca se valida ni se lee
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'evidencia_infectada_bloqueada') THEN
        ALTER TABLE canal.evidencia_externa ADD CONSTRAINT evidencia_infectada_bloqueada CHECK (
            escaneo_malware <> 'infectado' OR (estado <> 'validada' AND estado_lectura = 'bloqueada'));
    END IF;
END
$$;
CREATE UNIQUE INDEX IF NOT EXISTS evidencia_uri_uq ON canal.evidencia_externa (uri_archivo) WHERE uri_archivo IS NOT NULL;

CREATE TABLE IF NOT EXISTS canal.lectura_examen (
    id_lectura      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_evidencia    bigint NOT NULL REFERENCES canal.evidencia_externa (id_evidencia),
    campo           text NOT NULL CHECK (campo IN ('tipo_medicion', 'valor', 'unidad', 'fecha_examen', 'lugar')),
    valor_propuesto text,                              -- NULL = no se pudo leer (nunca se inventa)
    cita            text,                              -- texto literal del documento que respalda el valor
    confianza       numeric(4, 3) CHECK (confianza BETWEEN 0 AND 1),
    nota            text,                              -- p. ej. "unidad mmol/L convertida a mg/dL" o el motivo del descarte
    modelo          text NOT NULL,
    version_prompt  text NOT NULL,
    creada_en       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT lectura_con_cita CHECK (valor_propuesto IS NULL OR cita IS NOT NULL)
);
COMMENT ON TABLE canal.lectura_examen IS
    'Propuesta de lectura de un examen externo (Textract + Claude), con la cita literal de cada campo. Una persona la confirma';
CREATE INDEX IF NOT EXISTS lectura_evidencia_idx ON canal.lectura_examen (id_evidencia, creada_en DESC);
DROP TRIGGER IF EXISTS lectura_solo_insercion ON canal.lectura_examen;
CREATE TRIGGER lectura_solo_insercion BEFORE UPDATE OR DELETE ON canal.lectura_examen
    FOR EACH ROW EXECUTE FUNCTION priorizacion.solo_insercion();
