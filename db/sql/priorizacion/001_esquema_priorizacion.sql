-- Esquema priorizacion: lo que genera el sistema (motor, bandeja clínica, agenda).
-- Reemplaza las tablas SQLite de priorizacion/registro.py. Requiere el esquema raw. Idempotente.
-- Modelo y decisiones en docs/feature/F0002-modelo-datos-canales.md.
--
-- Convenciones de llaves:
--   * Datos fuente (raw): llave natural del HLF (text).
--   * Entidades del sistema: bigint GENERATED ALWAYS AS IDENTITY (nunca COUNT(*)+1).
--   * Series por fecha: llave natural compuesta (entidad, fecha).
--   * Catálogos y usuarios: código text estable.

CREATE SCHEMA IF NOT EXISTS priorizacion;
COMMENT ON SCHEMA priorizacion IS 'Datos que genera el sistema: propuestas, decisiones, serie nocturna, agenda y estimaciones';

-- Bloquea UPDATE y DELETE en tablas de auditoría (solo inserciones)
CREATE OR REPLACE FUNCTION priorizacion.solo_insercion() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'La tabla %.% es de solo inserción (auditoría): % no permitido',
        TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP;
END
$$;

-- Usuarios ----------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS priorizacion.usuario (
    id_usuario   text PRIMARY KEY,                      -- login institucional, o 'sistema' / 'asistente_ia'
    nombre       text NOT NULL,
    rol          text NOT NULL CHECK (rol IN
                   ('medico', 'enfermeria', 'tens', 'gestor_lista', 'administrativo', 'sistema')),
    especialidad text,                                   -- NULL = todas
    activo       boolean NOT NULL DEFAULT true,
    creado_en    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE priorizacion.usuario IS 'Quién decide o revisa. Las columnas *_por de todo el modelo apuntan aquí';
INSERT INTO priorizacion.usuario (id_usuario, nombre, rol) VALUES
    ('sistema', 'Proceso automático', 'sistema'),
    ('asistente_ia', 'Asistente virtual (WhatsApp y voz)', 'sistema')
ON CONFLICT (id_usuario) DO NOTHING;

-- Reloj: la fecha de corte que usa toda la base -------------------------------------------------------
-- La fecha de corte es la de los DATOS (F0006): el fin del periodo de la última carga aplicada. Evaluar al día real
-- con datos de un mes atrás haría crecer la espera y vencer ventanas de eventos sin saber qué pasó.
--   modo 'datos' (por defecto): la mayor fecha de corte entre las versiones aplicadas (raw.carga_lote.fecha_corte).
--   modo 'manual': una fecha fija, para ensayos y pruebas (python -m db reloj --fijar AAAA-MM-DD).
-- Una sola fila (id = 1).
CREATE TABLE IF NOT EXISTS priorizacion.reloj (
    id              smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    modo            text NOT NULL,
    fecha_manual    date,
    actualizado_en  timestamptz NOT NULL DEFAULT now(),
    actualizado_por text NOT NULL REFERENCES priorizacion.usuario (id_usuario)
);
COMMENT ON TABLE priorizacion.reloj IS 'Cómo se obtiene la fecha de corte: de los datos (por defecto) o fija (ensayos). Una sola fila';

-- Bases creadas con el reloj de F0003 (modos real/demo que avanzaban solos): se convierten al modelo nuevo
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'priorizacion'
               AND table_name = 'reloj' AND column_name = 'fecha_demo') THEN
        ALTER TABLE priorizacion.reloj RENAME COLUMN fecha_demo TO fecha_manual;
    END IF;
    ALTER TABLE priorizacion.reloj DROP COLUMN IF EXISTS dias_por_tick;
    ALTER TABLE priorizacion.reloj DROP CONSTRAINT IF EXISTS reloj_modo_check;
    ALTER TABLE priorizacion.reloj DROP CONSTRAINT IF EXISTS reloj_demo_con_fecha;
    UPDATE priorizacion.reloj SET modo = CASE modo WHEN 'demo' THEN 'manual' WHEN 'real' THEN 'datos' ELSE modo END
    WHERE modo IN ('real', 'demo');
    ALTER TABLE priorizacion.reloj DROP CONSTRAINT IF EXISTS reloj_modo_valido;
    ALTER TABLE priorizacion.reloj ADD CONSTRAINT reloj_modo_valido CHECK (modo IN ('datos', 'manual'));
    ALTER TABLE priorizacion.reloj DROP CONSTRAINT IF EXISTS reloj_manual_con_fecha;
    ALTER TABLE priorizacion.reloj ADD CONSTRAINT reloj_manual_con_fecha CHECK (modo = 'datos' OR fecha_manual IS NOT NULL);
END
$$;
INSERT INTO priorizacion.reloj (id, modo, actualizado_por) VALUES (1, 'datos', 'sistema') ON CONFLICT (id) DO NOTHING;
DROP FUNCTION IF EXISTS priorizacion.avanzar_reloj(integer, text);

-- SECURITY DEFINER: las vistas del asistente la usan sin que su rol pueda leer priorizacion ni raw.
-- plpgsql (no sql): no exige que raw.carga_lote.fecha_corte exista al crear la función.
CREATE OR REPLACE FUNCTION priorizacion.fecha_corte() RETURNS date
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_modo text;
    v_manual date;
    v_datos date;
BEGIN
    SELECT modo, fecha_manual INTO v_modo, v_manual FROM priorizacion.reloj WHERE id = 1;
    IF v_modo = 'manual' THEN
        RETURN v_manual;
    END IF;
    BEGIN
        SELECT max(fecha_corte) INTO v_datos FROM raw.carga_lote WHERE estado = 'aplicada';
    EXCEPTION WHEN undefined_column OR undefined_table THEN
        v_datos := NULL;
    END;
    RETURN coalesce(v_datos, current_date);
END
$$;
COMMENT ON FUNCTION priorizacion.fecha_corte() IS
    'Fecha de corte: la de los datos (fin del periodo de la última carga aplicada) o la fija del modo manual';

-- Proceso nocturno --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS priorizacion.corrida_nocturna (
    id_corrida     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inicio         timestamptz NOT NULL,
    fin            timestamptz,
    desde          date NOT NULL,
    hasta          date NOT NULL,
    alcance        text NOT NULL,                        -- 'completa' o una especialidad
    version_reglas text NOT NULL,
    n_evaluaciones integer CHECK (n_evaluaciones >= 0),
    n_propuestas   integer CHECK (n_propuestas >= 0),
    segundos       numeric(10, 2) CHECK (segundos >= 0),
    CONSTRAINT corrida_rango_valido CHECK (hasta >= desde),
    CONSTRAINT corrida_fin_valido CHECK (fin IS NULL OR fin >= inicio)
);
COMMENT ON TABLE priorizacion.corrida_nocturna IS 'Bitácora: una ejecución del proceso nocturno';

-- Una fila por solicitud activa y noche. Crece ~9,5 M filas/año a escala HLF: particionada por fecha.
-- La especialidad y la prioridad_inicial no se copian: se obtienen de raw.lista_espera.
CREATE TABLE IF NOT EXISTS priorizacion.serie_nocturna (
    id_solicitud      text NOT NULL REFERENCES raw.lista_espera (id_solicitud),
    fecha             date NOT NULL,
    id_corrida        bigint REFERENCES priorizacion.corrida_nocturna (id_corrida),
    puntaje           numeric(8, 3) NOT NULL,
    puntaje_nivel     numeric(8, 3) NOT NULL,
    nivel_propuesto   text NOT NULL CHECK (nivel_propuesto IN ('alta', 'media', 'baja')),
    prioridad_vigente text NOT NULL CHECK (prioridad_vigente IN ('alta', 'media', 'baja')),
    cambio            text NOT NULL CHECK (cambio IN ('sube', 'baja', 'igual')),
    alerta            boolean NOT NULL,
    motivo_principal  text,
    posicion_dinamica integer NOT NULL CHECK (posicion_dinamica > 0),
    posicion_estatica integer NOT NULL CHECK (posicion_estatica > 0),
    total_cola        integer NOT NULL CHECK (total_cola > 0),
    PRIMARY KEY (id_solicitud, fecha),
    CONSTRAINT serie_posiciones_en_cola CHECK (posicion_dinamica <= total_cola AND posicion_estatica <= total_cola)
) PARTITION BY RANGE (fecha);
COMMENT ON TABLE priorizacion.serie_nocturna IS 'Puntaje y posición de cada solicitud activa en cada noche. Particionar por año o mes';
CREATE TABLE IF NOT EXISTS priorizacion.serie_nocturna_default PARTITION OF priorizacion.serie_nocturna DEFAULT;
CREATE INDEX IF NOT EXISTS serie_nocturna_fecha_idx ON priorizacion.serie_nocturna (fecha);

-- Propuestas y su explicación ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS priorizacion.propuesta_prioridad (
    id_propuesta        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_solicitud        text NOT NULL REFERENCES raw.lista_espera (id_solicitud),
    id_corrida          bigint REFERENCES priorizacion.corrida_nocturna (id_corrida),
    origen              text NOT NULL CHECK (origen IN ('nocturno', 'validacion')),
    fecha_corte         date NOT NULL,
    fecha_calculo       timestamptz NOT NULL DEFAULT now(),
    puntaje             numeric(8, 3) NOT NULL,
    puntaje_nivel       numeric(8, 3) NOT NULL,
    prioridad_propuesta text NOT NULL CHECK (prioridad_propuesta IN ('alta', 'media', 'baja')),
    prioridad_vigente   text NOT NULL CHECK (prioridad_vigente IN ('alta', 'media', 'baja')),
    cambio              text NOT NULL CHECK (cambio IN ('sube', 'baja', 'igual')),
    alerta              boolean NOT NULL,
    motivos_alerta      jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(motivos_alerta) = 'array'),
    resguardo_aplicado  boolean NOT NULL DEFAULT false,
    version_reglas      text NOT NULL,
    huella_datos        text NOT NULL,                   -- hash de las filas fuente usadas: reproducibilidad
    explicacion_texto   text NOT NULL,
    fuente_explicacion  text NOT NULL CHECK (fuente_explicacion IN ('plantilla', 'llm')),
    -- Destino de la FK compuesta de decision_clinica (garantiza que decisión y propuesta sean de la misma solicitud)
    CONSTRAINT propuesta_id_solicitud_uq UNIQUE (id_propuesta, id_solicitud)
);
COMMENT ON TABLE priorizacion.propuesta_prioridad IS
    'Prioridad propuesta por el motor con su explicación. Nunca modifica raw.lista_espera.prioridad_inicial';
CREATE INDEX IF NOT EXISTS propuesta_solicitud_corte_idx ON priorizacion.propuesta_prioridad (id_solicitud, fecha_corte);

CREATE TABLE IF NOT EXISTS priorizacion.factor_propuesta (
    id_propuesta bigint NOT NULL REFERENCES priorizacion.propuesta_prioridad (id_propuesta) ON DELETE CASCADE,
    orden        smallint NOT NULL CHECK (orden >= 0),
    codigo       text NOT NULL,
    descripcion  text NOT NULL,
    aporte       numeric(8, 3) NOT NULL,
    categoria    text NOT NULL,                          -- base, contexto, ajuste, regla_dura, tendencia...
    tipo_fuente  text NOT NULL CHECK (tipo_fuente IN
                   ('lista', 'paciente', 'evento', 'medicion', 'cita', 'externa', 'mensaje')),
    ref_fuente   text,                                   -- EV-…, CT-…, IC-…, o id_paciente/fecha/tipo para mediciones
    fecha_dato   date,
    PRIMARY KEY (id_propuesta, orden)
);
COMMENT ON TABLE priorizacion.factor_propuesta IS 'Un factor que explica una propuesta, con la fila fuente exacta';

-- Decisión clínica: auditoría, solo inserciones. Una nueva decisión reemplaza a la anterior por fecha.
CREATE TABLE IF NOT EXISTS priorizacion.decision_clinica (
    id_decision         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_propuesta        bigint NOT NULL,
    id_solicitud        text NOT NULL,
    fecha_corte         date NOT NULL,
    prioridad_anterior  text NOT NULL CHECK (prioridad_anterior IN ('alta', 'media', 'baja')),
    prioridad_propuesta text NOT NULL CHECK (prioridad_propuesta IN ('alta', 'media', 'baja')),
    decision            text NOT NULL CHECK (decision IN ('acepta', 'ajusta', 'rechaza')),
    prioridad_final     text NOT NULL CHECK (prioridad_final IN ('alta', 'media', 'baja')),
    motivo              text NOT NULL,
    id_usuario          text NOT NULL REFERENCES priorizacion.usuario (id_usuario),
    fecha_registro      timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (id_propuesta, id_solicitud)
        REFERENCES priorizacion.propuesta_prioridad (id_propuesta, id_solicitud),
    CONSTRAINT decision_coherente CHECK (
        (decision = 'acepta'  AND prioridad_final = prioridad_propuesta) OR
        (decision = 'rechaza' AND prioridad_final = prioridad_anterior) OR
         decision = 'ajusta'),
    CONSTRAINT decision_motivo_no_vacio CHECK (length(trim(motivo)) > 0)
);
COMMENT ON TABLE priorizacion.decision_clinica IS 'Lo que decidió el equipo clínico. Solo inserciones; la vigente es la última por fecha';
CREATE INDEX IF NOT EXISTS decision_solicitud_idx ON priorizacion.decision_clinica (id_solicitud, fecha_corte, id_decision);
DROP TRIGGER IF EXISTS decision_clinica_solo_insercion ON priorizacion.decision_clinica;
CREATE TRIGGER decision_clinica_solo_insercion BEFORE UPDATE OR DELETE ON priorizacion.decision_clinica
    FOR EACH ROW EXECUTE FUNCTION priorizacion.solo_insercion();

-- Prioridad vigente a la fecha de corte: última decisión clínica hasta esa fecha o, si no hay, la inicial del HLF
CREATE OR REPLACE VIEW priorizacion.v_prioridad_vigente AS
SELECT le.id_solicitud,
       le.id_paciente,
       le.especialidad,
       le.prioridad_inicial,
       COALESCE(d.prioridad_final, le.prioridad_inicial) AS prioridad_vigente,
       d.fecha_corte                                     AS fecha_ultima_decision,
       le.fecha_ingreso_lista,
       le.estado
FROM raw.lista_espera le
LEFT JOIN LATERAL (
    SELECT dc.prioridad_final, dc.fecha_corte
    FROM priorizacion.decision_clinica dc
    WHERE dc.id_solicitud = le.id_solicitud AND dc.fecha_corte <= priorizacion.fecha_corte()
    ORDER BY dc.fecha_corte DESC, dc.id_decision DESC
    LIMIT 1
) d ON true;
COMMENT ON VIEW priorizacion.v_prioridad_vigente IS 'Prioridad que rige hoy: decidida por una persona, nunca la propuesta del motor';

-- Agenda futura -----------------------------------------------------------------------------------
-- raw.citaciones es histórico (ya ocurrió). Las citas que se agendan desde la app viven aquí.
CREATE TABLE IF NOT EXISTS priorizacion.cita_agendada (
    id_cita_agendada bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_solicitud     text NOT NULL REFERENCES raw.lista_espera (id_solicitud),
    id_box           text NOT NULL REFERENCES raw.box (id_box),
    fecha            date NOT NULL,
    hora_inicio      time,
    duracion_min     smallint CHECK (duracion_min > 0),
    estado           text NOT NULL DEFAULT 'programada' CHECK (estado IN
                       ('programada', 'confirmada', 'reprogramada', 'cancelada', 'asistio', 'no_asistio')),
    origen           text NOT NULL CHECK (origen IN ('agenda_propuesta', 'manual', 'reemplazo_cupo')),
    id_cita_anterior bigint REFERENCES priorizacion.cita_agendada (id_cita_agendada), -- si es reprogramación
    agendado_por     text NOT NULL REFERENCES priorizacion.usuario (id_usuario),
    creado_en        timestamptz NOT NULL DEFAULT now(),
    actualizado_en   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cita_no_se_reprograma_a_si_misma CHECK (id_cita_anterior <> id_cita_agendada)
);
COMMENT ON TABLE priorizacion.cita_agendada IS 'Cita futura o reciente agendada desde la app (raw.citaciones es solo histórico)';
CREATE INDEX IF NOT EXISTS cita_agendada_solicitud_idx ON priorizacion.cita_agendada (id_solicitud, fecha);
-- Un box no se agenda dos veces a la misma hora (citas activas)
CREATE UNIQUE INDEX IF NOT EXISTS cita_agendada_box_hora_uq ON priorizacion.cita_agendada (id_box, fecha, hora_inicio)
    WHERE estado IN ('programada', 'confirmada') AND hora_inicio IS NOT NULL;

-- Estimación de espera ----------------------------------------------------------------------------
-- Lo que se puede informar al paciente. Se basa en la prioridad VIGENTE (decidida por personas),
-- no en la propuesta del motor, y siempre es un rango: la posición no es una fecha garantizada.
CREATE TABLE IF NOT EXISTS priorizacion.estimacion_espera (
    id_solicitud       text NOT NULL REFERENCES raw.lista_espera (id_solicitud),
    fecha_calculo      date NOT NULL,
    id_corrida         bigint REFERENCES priorizacion.corrida_nocturna (id_corrida),
    prioridad_vigente  text NOT NULL CHECK (prioridad_vigente IN ('alta', 'media', 'baja')),
    posicion_vigente   integer NOT NULL CHECK (posicion_vigente > 0),
    total_cola         integer NOT NULL CHECK (total_cola > 0),
    dias_estimados_min integer NOT NULL CHECK (dias_estimados_min >= 0),
    dias_estimados_max integer NOT NULL,
    confianza          text NOT NULL CHECK (confianza IN ('alta', 'media', 'baja')),
    metodo             text NOT NULL,                    -- p. ej. 'throughput_8_semanas'
    version_metodo     text NOT NULL,
    publicable         boolean NOT NULL DEFAULT false,   -- false = el asistente no la informa
    PRIMARY KEY (id_solicitud, fecha_calculo),
    CONSTRAINT estimacion_posicion_en_cola CHECK (posicion_vigente <= total_cola),
    CONSTRAINT estimacion_rango_valido CHECK (dias_estimados_max >= dias_estimados_min)
);
COMMENT ON TABLE priorizacion.estimacion_espera IS
    'Rango de días estimado para ser atendido, por solicitud y día. Solo las publicables llegan al paciente';
