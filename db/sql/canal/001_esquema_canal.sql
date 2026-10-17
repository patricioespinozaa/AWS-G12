-- Esquema canal: comunicación con el paciente por WhatsApp y por teléfono con asistente de IA (voz).
-- Ambos canales comparten el mismo modelo: conversación → turnos → lo que se informó (divulgación).
-- Requiere raw y priorizacion. Idempotente. Modelo y reglas en docs/feature/F0002-modelo-datos-canales.md.
--
-- Datos personales:
--   * Teléfonos cifrados en la aplicación (KMS) + HMAC para buscarlos; nunca en texto plano.
--   * Transcripciones y audios con fecha de retención (retener_hasta).
--   * Todo lo que el asistente informa queda en canal.divulgacion (solo inserciones).

CREATE SCHEMA IF NOT EXISTS canal;
COMMENT ON SCHEMA canal IS 'Canal del paciente: WhatsApp, voz con IA, mensajes, evidencia externa y notificaciones';

-- Catálogo de intenciones -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canal.intencion (
    codigo                text PRIMARY KEY,
    descripcion           text NOT NULL,
    verificacion_minima   text NOT NULL CHECK (verificacion_minima IN ('ninguna', 'basica', 'reforzada')),
    la_resuelve_ia        boolean NOT NULL,             -- false = siempre deriva a una persona
    vista_fuente          text                          -- vista v_ia_* de la que sale la respuesta
);
COMMENT ON TABLE canal.intencion IS 'Qué puede pedir el paciente y qué nivel de identidad exige cada cosa';
INSERT INTO canal.intencion VALUES
    ('consultar_prioridad',      'Prioridad vigente y posición en la lista',            'reforzada', true,  'canal.v_ia_estado_solicitud'),
    ('consultar_tiempo_espera',  'Rango estimado de días hasta la atención',            'reforzada', true,  'canal.v_ia_estado_solicitud'),
    ('consultar_citas',          'Citas agendadas próximas y pasadas',                  'basica',    true,  'canal.v_ia_citas'),
    ('consultar_registros',      'Qué registros clínicos tiene el hospital',            'reforzada', true,  'canal.v_ia_registros'),
    ('confirmar_asistencia',     'Confirma que asistirá a su cita',                     'basica',    true,  NULL),
    ('no_puede_asistir',         'Avisa que no puede asistir',                          'basica',    true,  NULL),
    ('reportar_sintoma',         'Reporta un síntoma nuevo',                            'basica',    true,  NULL),
    ('enviar_examen',            'Envía un examen hecho fuera del hospital',            'basica',    true,  NULL),
    ('pregunta_clinica',         'Pide interpretación o consejo clínico',               'ninguna',   false, NULL),
    ('hablar_con_persona',       'Pide hablar con una persona',                         'ninguna',   false, NULL)
ON CONFLICT (codigo) DO NOTHING;

-- Contacto y consentimiento -----------------------------------------------------------------------
-- Un mismo número puede ser de varios pacientes (p. ej. una hija que gestiona a sus padres):
-- por eso valor_hash NO es único global, y el asistente pregunta por quién llama.
CREATE TABLE IF NOT EXISTS canal.contacto_paciente (
    id_contacto               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_paciente               text NOT NULL REFERENCES raw.pacientes (id_paciente),
    tipo                      text NOT NULL CHECK (tipo IN ('movil', 'fijo', 'whatsapp')),
    valor_cifrado             bytea NOT NULL,           -- E.164 cifrado con KMS (envelope encryption)
    valor_hash                text NOT NULL,            -- HMAC-SHA256(E.164, pepper en Secrets Manager)
    ultimos_digitos           char(4) NOT NULL,         -- para mostrar '*** 4567'
    relacion                  text NOT NULL DEFAULT 'titular' CHECK (relacion IN ('titular', 'cuidador', 'familiar')),
    nombre_contacto           text,                     -- solo si no es el titular
    autorizado_informacion    boolean NOT NULL DEFAULT false, -- un tercero recibe datos clínicos solo si es true
    es_principal              boolean NOT NULL DEFAULT false,
    verificado_en             timestamptz,
    vigente                   boolean NOT NULL DEFAULT true,
    creado_en                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT contacto_uq UNIQUE (id_paciente, tipo, valor_hash),
    CONSTRAINT contacto_titular_sin_nombre CHECK (relacion = 'titular' OR nombre_contacto IS NOT NULL)
);
COMMENT ON TABLE canal.contacto_paciente IS 'Un medio de contacto de un paciente. El número va cifrado; se busca por HMAC';
CREATE INDEX IF NOT EXISTS contacto_hash_idx ON canal.contacto_paciente (valor_hash) WHERE vigente;
CREATE UNIQUE INDEX IF NOT EXISTS contacto_un_principal_por_tipo_uq ON canal.contacto_paciente (id_paciente, tipo)
    WHERE es_principal AND vigente;

-- Solo inserciones: revocar = insertar una fila con otorgado = false. Rige la última por (paciente, canal, finalidad).
CREATE TABLE IF NOT EXISTS canal.consentimiento (
    id_consentimiento bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_paciente       text NOT NULL REFERENCES raw.pacientes (id_paciente),
    canal             text NOT NULL CHECK (canal IN ('whatsapp', 'voz', 'sms')),
    finalidad         text NOT NULL CHECK (finalidad IN
                        ('recordatorios', 'consulta_estado', 'envio_examenes', 'grabacion_llamada', 'asistente_ia')),
    otorgado          boolean NOT NULL,
    fecha             timestamptz NOT NULL DEFAULT now(),
    medio_registro    text NOT NULL CHECK (medio_registro IN ('presencial', 'whatsapp', 'voz', 'web')),
    id_conversacion   bigint,                           -- FK agregada más abajo (la tabla aún no existe)
    registrado_por    text NOT NULL REFERENCES priorizacion.usuario (id_usuario)
);
COMMENT ON TABLE canal.consentimiento IS 'Historial de consentimientos por canal y finalidad (Ley 19.628 / 21.719)';
CREATE INDEX IF NOT EXISTS consentimiento_vigente_idx ON canal.consentimiento (id_paciente, canal, finalidad, fecha DESC);
DROP TRIGGER IF EXISTS consentimiento_solo_insercion ON canal.consentimiento;
CREATE TRIGGER consentimiento_solo_insercion BEFORE UPDATE OR DELETE ON canal.consentimiento
    FOR EACH ROW EXECUTE FUNCTION priorizacion.solo_insercion();

CREATE OR REPLACE VIEW canal.v_consentimiento_vigente AS
SELECT DISTINCT ON (id_paciente, canal, finalidad) id_paciente, canal, finalidad, otorgado, fecha
FROM canal.consentimiento
ORDER BY id_paciente, canal, finalidad, fecha DESC, id_consentimiento DESC;

-- Conversaciones (WhatsApp y voz) -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canal.conversacion (
    id_conversacion     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canal               text NOT NULL CHECK (canal IN ('whatsapp', 'voz')),
    direccion           text NOT NULL CHECK (direccion IN ('entrante', 'saliente')),
    id_externo          text NOT NULL,                  -- ContactId de Amazon Connect o id de conversación de WhatsApp
    id_contacto         bigint REFERENCES canal.contacto_paciente (id_contacto),
    id_paciente         text REFERENCES raw.pacientes (id_paciente), -- NULL hasta identificar
    nivel_verificacion  text NOT NULL DEFAULT 'ninguna' CHECK (nivel_verificacion IN ('ninguna', 'basica', 'reforzada')),
    inicio              timestamptz NOT NULL DEFAULT now(),
    fin                 timestamptz,
    estado              text NOT NULL DEFAULT 'en_curso' CHECK (estado IN
                          ('en_curso', 'finalizada', 'abandonada', 'derivada')),
    idioma              text NOT NULL DEFAULT 'es-CL',
    modelo_ia           text,                           -- p. ej. ID del modelo en Bedrock
    version_prompt      text,
    uri_grabacion       text,                           -- s3://… solo si hay consentimiento de grabación
    retener_hasta       date NOT NULL DEFAULT (current_date + 365),
    CONSTRAINT conversacion_externo_uq UNIQUE (canal, id_externo),
    CONSTRAINT conversacion_fin_valido CHECK (fin IS NULL OR fin >= inicio),
    CONSTRAINT conversacion_cerrada_con_fin CHECK ((estado = 'en_curso') = (fin IS NULL)),
    CONSTRAINT conversacion_verificada_identificada CHECK (nivel_verificacion = 'ninguna' OR id_paciente IS NOT NULL),
    CONSTRAINT conversacion_grabacion_solo_voz CHECK (uri_grabacion IS NULL OR canal = 'voz')
);
COMMENT ON TABLE canal.conversacion IS 'Una conversación por WhatsApp o una llamada telefónica con el asistente';
CREATE INDEX IF NOT EXISTS conversacion_paciente_idx ON canal.conversacion (id_paciente, inicio DESC);
CREATE INDEX IF NOT EXISTS conversacion_retencion_idx ON canal.conversacion (retener_hasta);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'consentimiento_conversacion_fk') THEN
        ALTER TABLE canal.consentimiento ADD CONSTRAINT consentimiento_conversacion_fk
            FOREIGN KEY (id_conversacion) REFERENCES canal.conversacion (id_conversacion);
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS canal.verificacion_identidad (
    id_verificacion bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_conversacion bigint NOT NULL REFERENCES canal.conversacion (id_conversacion),
    metodo          text NOT NULL CHECK (metodo IN
                      ('numero_registrado', 'fecha_nacimiento', 'digitos_rut', 'codigo_sms', 'agente_humano')),
    resultado       text NOT NULL CHECK (resultado IN ('exitosa', 'fallida', 'bloqueada')),
    nivel_otorgado  text NOT NULL CHECK (nivel_otorgado IN ('ninguna', 'basica', 'reforzada')),
    fecha           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT verificacion_fallida_sin_nivel CHECK (resultado = 'exitosa' OR nivel_otorgado = 'ninguna')
);
COMMENT ON TABLE canal.verificacion_identidad IS 'Cada intento de verificar identidad. Nunca guarda el dato respondido';
CREATE INDEX IF NOT EXISTS verificacion_conversacion_idx ON canal.verificacion_identidad (id_conversacion);

-- Turnos: lo que dijo cada parte. Llave natural (conversación, número de turno). Solo inserciones.
CREATE TABLE IF NOT EXISTS canal.turno (
    id_conversacion bigint NOT NULL REFERENCES canal.conversacion (id_conversacion),
    n_turno         integer NOT NULL CHECK (n_turno > 0),
    emisor          text NOT NULL CHECK (emisor IN ('paciente', 'asistente_ia', 'funcionario')),
    id_usuario      text REFERENCES priorizacion.usuario (id_usuario), -- quién, si emisor = funcionario
    texto           text NOT NULL,                      -- mensaje o transcripción (Amazon Transcribe)
    confianza_asr   numeric(4, 3) CHECK (confianza_asr BETWEEN 0 AND 1), -- solo voz
    intencion       text REFERENCES canal.intencion (codigo),
    confianza_nlu   numeric(4, 3) CHECK (confianza_nlu BETWEEN 0 AND 1),
    fecha           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id_conversacion, n_turno),
    CONSTRAINT turno_funcionario_identificado CHECK ((emisor = 'funcionario') = (id_usuario IS NOT NULL))
);
COMMENT ON TABLE canal.turno IS 'Un mensaje o una intervención hablada dentro de una conversación';
DROP TRIGGER IF EXISTS turno_solo_insercion ON canal.turno;
CREATE TRIGGER turno_solo_insercion BEFORE UPDATE ON canal.turno
    FOR EACH ROW EXECUTE FUNCTION priorizacion.solo_insercion();  -- DELETE permitido solo al proceso de retención

-- Divulgación: auditoría de cada dato que el asistente informó y de qué fila salió. Solo inserciones.
CREATE TABLE IF NOT EXISTS canal.divulgacion (
    id_divulgacion  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_conversacion bigint NOT NULL,
    n_turno         integer NOT NULL,
    id_paciente     text NOT NULL REFERENCES raw.pacientes (id_paciente),
    tipo_dato       text NOT NULL CHECK (tipo_dato IN
                      ('prioridad', 'posicion', 'tiempo_estimado', 'cita_proxima', 'cita_pasada',
                       'registro_clinico', 'estado_solicitud', 'examen_pendiente')),
    vista_fuente    text NOT NULL,                      -- canal.v_ia_…
    ref_fuente      text NOT NULL,                      -- id_solicitud/fecha_calculo, CT-…, EV-…, etc.
    valor_informado text NOT NULL,
    fecha           timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (id_conversacion, n_turno) REFERENCES canal.turno (id_conversacion, n_turno)
);
COMMENT ON TABLE canal.divulgacion IS 'Qué dato se informó a quién, en qué turno y desde qué fila fuente';
CREATE INDEX IF NOT EXISTS divulgacion_paciente_idx ON canal.divulgacion (id_paciente, fecha DESC);
DROP TRIGGER IF EXISTS divulgacion_solo_insercion ON canal.divulgacion;
CREATE TRIGGER divulgacion_solo_insercion BEFORE UPDATE OR DELETE ON canal.divulgacion
    FOR EACH ROW EXECUTE FUNCTION priorizacion.solo_insercion();

CREATE TABLE IF NOT EXISTS canal.derivacion_humana (
    id_derivacion   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_conversacion bigint NOT NULL REFERENCES canal.conversacion (id_conversacion),
    motivo          text NOT NULL CHECK (motivo IN
                      ('pregunta_clinica', 'sintoma_alarma', 'verificacion_fallida', 'pide_persona',
                       'baja_confianza', 'dato_sensible', 'reclamo')),
    urgencia        text NOT NULL CHECK (urgencia IN ('inmediata', 'mismo_dia', 'normal')),
    estado          text NOT NULL DEFAULT 'pendiente' CHECK (estado IN
                      ('pendiente', 'en_gestion', 'resuelta', 'sin_contacto')),
    asignado_a      text REFERENCES priorizacion.usuario (id_usuario),
    creada_en       timestamptz NOT NULL DEFAULT now(),
    resuelta_en     timestamptz,
    nota            text,
    CONSTRAINT derivacion_resuelta_con_fecha CHECK ((estado IN ('resuelta', 'sin_contacto')) = (resuelta_en IS NOT NULL)),
    CONSTRAINT derivacion_fechas_validas CHECK (resuelta_en IS NULL OR resuelta_en >= creada_en)
);
COMMENT ON TABLE canal.derivacion_humana IS 'Caso que el asistente pasa a una persona (TENS, enfermería, call center)';
CREATE INDEX IF NOT EXISTS derivacion_pendiente_idx ON canal.derivacion_humana (urgencia, creada_en)
    WHERE estado IN ('pendiente', 'en_gestion');

-- Lo que aporta el paciente (hoy en registro.py) --------------------------------------------------
CREATE TABLE IF NOT EXISTS canal.mensaje_paciente (
    id_mensaje      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_paciente     text NOT NULL REFERENCES raw.pacientes (id_paciente),
    id_conversacion bigint REFERENCES canal.conversacion (id_conversacion), -- NULL si vino por la web
    canal_origen    text NOT NULL CHECK (canal_origen IN ('whatsapp', 'voz', 'web', 'presencial')),
    fecha           date NOT NULL,                       -- fecha a la que se refiere el mensaje
    recibido_en     timestamptz NOT NULL DEFAULT now(),
    tipo            text NOT NULL CHECK (tipo IN
                      ('confirma_asistencia', 'no_puede_asistir', 'sintoma_alarma', 'sintoma_sin_alarma', 'sin_respuesta')),
    detalle         text NOT NULL DEFAULT '',
    estado          text NOT NULL CHECK (estado IN ('pendiente', 'registrado', 'validada', 'rechazada')),
    revisado_por    text REFERENCES priorizacion.usuario (id_usuario),
    fecha_revision  timestamptz,
    CONSTRAINT mensaje_alarma_requiere_revision CHECK (tipo <> 'sintoma_alarma' OR estado <> 'registrado'),
    CONSTRAINT mensaje_revision_completa CHECK (
        (estado IN ('validada', 'rechazada')) = (revisado_por IS NOT NULL AND fecha_revision IS NOT NULL))
);
COMMENT ON TABLE canal.mensaje_paciente IS 'Confirmaciones y síntomas que informa el paciente. Las alarmas requieren revisión';
CREATE INDEX IF NOT EXISTS mensaje_paciente_idx ON canal.mensaje_paciente (id_paciente, fecha);
CREATE INDEX IF NOT EXISTS mensaje_pendiente_idx ON canal.mensaje_paciente (recibido_en) WHERE estado = 'pendiente';

CREATE TABLE IF NOT EXISTS canal.evidencia_externa (
    id_evidencia    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_paciente     text NOT NULL REFERENCES raw.pacientes (id_paciente),
    id_conversacion bigint REFERENCES canal.conversacion (id_conversacion),
    canal_origen    text NOT NULL CHECK (canal_origen IN ('whatsapp', 'web', 'presencial')),
    fecha_examen    date NOT NULL,
    tipo_medicion   text NOT NULL CHECK (tipo_medicion IN
                      ('HbA1c', 'PHQ9', 'escala_dolor_eva', 'glicemia', 'peak_flow',
                       'presion_diastolica', 'presion_sistolica', 'saturacion_o2')),
    valor           numeric NOT NULL,
    lugar           text NOT NULL DEFAULT '',
    uri_archivo     text,                                -- s3://…/evidencia_externa/… (cifrado SSE-KMS)
    sha256_archivo  char(64),
    tipo_mime       text CHECK (tipo_mime IN ('application/pdf', 'image/jpeg', 'image/png')),
    fecha_recepcion date NOT NULL,
    estado          text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'validada', 'rechazada')),
    revisado_por    text REFERENCES priorizacion.usuario (id_usuario),
    fecha_revision  timestamptz,
    nota            text,
    CONSTRAINT evidencia_fechas_validas CHECK (fecha_examen <= fecha_recepcion),
    CONSTRAINT evidencia_archivo_completo CHECK ((uri_archivo IS NULL) = (sha256_archivo IS NULL)),
    CONSTRAINT evidencia_revision_completa CHECK (
        (estado <> 'pendiente') = (revisado_por IS NOT NULL AND fecha_revision IS NOT NULL))
);
COMMENT ON TABLE canal.evidencia_externa IS 'Examen hecho fuera del hospital. Solo la validada entra al puntaje';
CREATE INDEX IF NOT EXISTS evidencia_paciente_idx ON canal.evidencia_externa (id_paciente, fecha_examen);
CREATE INDEX IF NOT EXISTS evidencia_pendiente_idx ON canal.evidencia_externa (fecha_recepcion) WHERE estado = 'pendiente';

-- Notificaciones salientes (recordatorios, rescate, pedir exámenes) -------------------------------
CREATE TABLE IF NOT EXISTS canal.notificacion (
    id_notificacion  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_paciente      text NOT NULL REFERENCES raw.pacientes (id_paciente),
    id_contacto      bigint NOT NULL REFERENCES canal.contacto_paciente (id_contacto),
    canal            text NOT NULL CHECK (canal IN ('whatsapp', 'voz', 'sms')),
    tipo             text NOT NULL CHECK (tipo IN
                       ('recordatorio_cita', 'confirmacion_asistencia', 'solicitud_examen', 'rescate_contacto', 'cambio_cita')),
    id_cita_agendada bigint REFERENCES priorizacion.cita_agendada (id_cita_agendada),
    plantilla        text NOT NULL,                      -- plantilla aprobada (WhatsApp exige plantillas)
    programada_para  timestamptz NOT NULL,
    enviada_en       timestamptz,
    estado           text NOT NULL DEFAULT 'programada' CHECK (estado IN
                       ('programada', 'enviada', 'entregada', 'leida', 'respondida', 'fallida', 'cancelada')),
    intentos         smallint NOT NULL DEFAULT 0 CHECK (intentos >= 0),
    id_conversacion  bigint REFERENCES canal.conversacion (id_conversacion), -- si el paciente respondió
    error            text,
    creada_por       text NOT NULL REFERENCES priorizacion.usuario (id_usuario),
    CONSTRAINT notificacion_cita_requerida CHECK (
        tipo NOT IN ('recordatorio_cita', 'confirmacion_asistencia', 'cambio_cita') OR id_cita_agendada IS NOT NULL),
    CONSTRAINT notificacion_enviada_con_fecha CHECK (
        estado IN ('programada', 'cancelada', 'fallida') OR enviada_en IS NOT NULL)
);
COMMENT ON TABLE canal.notificacion IS 'Mensaje o llamada saliente. Solo se programa si hay consentimiento vigente';
CREATE INDEX IF NOT EXISTS notificacion_por_enviar_idx ON canal.notificacion (programada_para) WHERE estado = 'programada';

-- Vistas que lee el asistente de IA ---------------------------------------------------------------
-- Solo devuelven filas del paciente de una conversación EN CURSO cuya identidad se verificó al nivel
-- que exige la intención. El backend del asistente, por cada transacción, hace:
--     SET LOCAL canal.id_conversacion = '123';
-- Sin conversación verificada no hay filas. El rol del asistente no lee raw ni priorizacion directamente.
CREATE OR REPLACE FUNCTION canal.paciente_verificado(nivel_minimo text) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT c.id_paciente
    FROM canal.conversacion c
    WHERE c.id_conversacion = nullif(current_setting('canal.id_conversacion', true), '')::bigint
      AND c.estado = 'en_curso'
      AND array_position(ARRAY['ninguna', 'basica', 'reforzada'], c.nivel_verificacion)
          >= array_position(ARRAY['ninguna', 'basica', 'reforzada'], nivel_minimo)
$$;
COMMENT ON FUNCTION canal.paciente_verificado(text) IS
    'id_paciente de la conversación de la sesión si está en curso y verificada al nivel pedido; si no, NULL';


-- Todas respetan priorizacion.fecha_corte(): no se informa nada posterior a la fecha de los datos (o la fijada).

CREATE OR REPLACE VIEW canal.v_ia_estado_solicitud WITH (security_barrier = true) AS
SELECT vp.id_solicitud,
       vp.id_paciente,
       vp.especialidad,
       le.sub_especialidad,
       vp.estado,
       vp.prioridad_vigente,                         -- la decidida por personas, nunca la propuesta del motor
       vp.fecha_ingreso_lista,
       priorizacion.fecha_corte() - vp.fecha_ingreso_lista AS dias_en_espera,
       ee.posicion_vigente,
       ee.total_cola,
       ee.dias_estimados_min,
       ee.dias_estimados_max,
       ee.confianza       AS confianza_estimacion,
       ee.fecha_calculo   AS fecha_estimacion,
       priorizacion.fecha_corte() AS fecha_corte
FROM priorizacion.v_prioridad_vigente vp
JOIN raw.lista_espera le USING (id_solicitud)
LEFT JOIN LATERAL (
    SELECT e.*
    FROM priorizacion.estimacion_espera e
    WHERE e.id_solicitud = vp.id_solicitud AND e.publicable AND e.fecha_calculo <= priorizacion.fecha_corte()
    ORDER BY e.fecha_calculo DESC
    LIMIT 1
) ee ON true
WHERE vp.id_paciente = canal.paciente_verificado('reforzada')
  AND vp.fecha_ingreso_lista <= priorizacion.fecha_corte();
COMMENT ON VIEW canal.v_ia_estado_solicitud IS
    'Prioridad vigente, posición y rango estimado del paciente verificado, a la fecha de corte';

-- Una cita de raw.citaciones posterior a la fecha de corte se informa como próxima y 'programada':
-- su resultado (asistió, no asistió…) todavía no se conoce a esa fecha.
CREATE OR REPLACE VIEW canal.v_ia_citas WITH (security_barrier = true) AS
SELECT 'agenda'::text                     AS origen,
       ca.id_cita_agendada::text          AS ref_fuente,
       le.id_paciente,
       le.especialidad,
       ca.id_box,
       ca.fecha,
       ca.hora_inicio,
       ca.estado,
       CASE WHEN ca.fecha >= priorizacion.fecha_corte() AND ca.estado IN ('programada', 'confirmada')
            THEN 'proxima' ELSE 'pasada' END AS temporalidad
FROM priorizacion.cita_agendada ca
JOIN raw.lista_espera le USING (id_solicitud)
WHERE le.id_paciente = canal.paciente_verificado('basica')
UNION ALL
SELECT 'historico', c.id_cita, c.id_paciente, c.especialidad, c.id_box, c.fecha_cita, NULL::time,
       CASE WHEN c.fecha_cita > priorizacion.fecha_corte() THEN 'programada' ELSE c.estado_cita END,
       CASE WHEN c.fecha_cita > priorizacion.fecha_corte() THEN 'proxima' ELSE 'pasada' END
FROM raw.citaciones c
WHERE c.id_paciente = canal.paciente_verificado('basica');
COMMENT ON VIEW canal.v_ia_citas IS 'Citas próximas y pasadas del paciente verificado, a la fecha de corte';

-- "sensible" = el asistente no lo lee en voz alta: ofrece derivar a una persona
CREATE OR REPLACE VIEW canal.v_ia_registros WITH (security_barrier = true) AS
SELECT 'evento'::text AS tipo_registro, e.id_evento AS ref_fuente, e.id_paciente, e.fecha_evento AS fecha,
       e.tipo_evento AS categoria, e.subtipo AS descripcion, NULL::numeric AS valor, NULL::text AS unidad,
       (e.tipo_evento = 'hospitalizacion' OR e.severidad = 'grave') AS sensible
FROM raw.eventos_clinicos e
WHERE e.id_paciente = canal.paciente_verificado('reforzada') AND e.fecha_evento <= priorizacion.fecha_corte()
UNION ALL
SELECT 'medicion', m.id_paciente || '/' || m.fecha_medicion || '/' || m.tipo_medicion, m.id_paciente,
       m.fecha_medicion, m.tipo_medicion, m.tipo_medicion, m.valor, m.unidad,
       (m.tipo_medicion = 'PHQ9')
FROM raw.mediciones m
WHERE m.id_paciente = canal.paciente_verificado('reforzada') AND m.fecha_medicion <= priorizacion.fecha_corte()
UNION ALL
SELECT 'examen_externo', x.id_evidencia::text, x.id_paciente, x.fecha_examen, x.tipo_medicion,
       x.tipo_medicion || coalesce(' (' || nullif(x.lugar, '') || ')', ''), x.valor, NULL, (x.tipo_medicion = 'PHQ9')
FROM canal.evidencia_externa x
WHERE x.estado = 'validada' AND x.id_paciente = canal.paciente_verificado('reforzada')
  AND x.fecha_recepcion <= priorizacion.fecha_corte();
COMMENT ON VIEW canal.v_ia_registros IS
    'Registros clínicos del paciente verificado hasta la fecha de corte. Informar qué hay, nunca interpretarlo';
