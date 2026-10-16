-- Asistente del paciente (F0010): simulador en la app y códigos de un solo uso. Idempotente.
--
-- * El simulador de la app usa el mismo núcleo que WhatsApp; sus conversaciones quedan con canal = 'simulador' para
--   no mezclarlas con las reales en la auditoría.
-- * La verificación reforzada usa un código de un solo uso (SMS, o mostrado en el simulador de la demo). Se guarda
--   solo su hash, con vencimiento e intentos: canal.verificacion_identidad sigue sin guardar el dato respondido.

ALTER TABLE canal.conversacion DROP CONSTRAINT IF EXISTS conversacion_canal_check;
ALTER TABLE canal.conversacion ADD CONSTRAINT conversacion_canal_check CHECK (canal IN ('whatsapp', 'voz', 'simulador'));

CREATE TABLE IF NOT EXISTS canal.codigo_verificacion (
    id_codigo       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_conversacion bigint NOT NULL REFERENCES canal.conversacion (id_conversacion),
    hash_codigo     text NOT NULL,                     -- HMAC-SHA256 del código con el pepper; nunca el código
    enviado_por     text NOT NULL CHECK (enviado_por IN ('sms', 'simulador')),
    creado_en       timestamptz NOT NULL DEFAULT now(),
    expira_en       timestamptz NOT NULL,
    intentos        smallint NOT NULL DEFAULT 0 CHECK (intentos >= 0),
    usado_en        timestamptz,
    CONSTRAINT codigo_expira_despues CHECK (expira_en > creado_en)
);
COMMENT ON TABLE canal.codigo_verificacion IS 'Código de un solo uso de la verificación reforzada (solo su hash)';
CREATE INDEX IF NOT EXISTS codigo_conversacion_idx ON canal.codigo_verificacion (id_conversacion, creado_en DESC);
