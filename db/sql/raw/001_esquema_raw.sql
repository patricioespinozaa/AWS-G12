-- Esquema raw: datos crudos del HLF, inmutables y de solo lectura.
-- Modelo verificado en docs/modelo-datos-raw.md. Idempotente: se puede ejecutar varias veces.

CREATE SCHEMA IF NOT EXISTS raw;
COMMENT ON SCHEMA raw IS 'Datos crudos del dataset HLF. Solo lectura para la aplicación; se cargan con python -m db';

CREATE TABLE IF NOT EXISTS raw.pacientes (
    id_paciente          text PRIMARY KEY,
    nombre_fantasia      text NOT NULL,
    edad                 integer NOT NULL CHECK (edad BETWEEN 0 AND 120),
    sexo                 text NOT NULL CHECK (sexo IN ('F', 'M')),
    comuna               text NOT NULL,
    prevision            text NOT NULL,
    nivel_socioeconomico text NOT NULL,
    fallecido            boolean NOT NULL,
    fecha_defuncion      date,
    CONSTRAINT pacientes_defuncion_coherente CHECK (fallecido = (fecha_defuncion IS NOT NULL))
);
COMMENT ON TABLE raw.pacientes IS 'Tabla maestra: un paciente (pacientes.csv)';

-- En el dataset la relación es 1:1, pero no se fuerza UNIQUE(id_paciente):
-- en la lista real un paciente puede tener varias interconsultas.
CREATE TABLE IF NOT EXISTS raw.lista_espera (
    id_solicitud        text PRIMARY KEY,
    id_paciente         text NOT NULL REFERENCES raw.pacientes (id_paciente),
    especialidad        text NOT NULL,
    sub_especialidad    text NOT NULL,
    diagnostico_cie10   text NOT NULL,
    diagnostico_texto   text NOT NULL,
    prioridad_inicial   text NOT NULL CHECK (prioridad_inicial IN ('alta', 'media', 'baja')),
    fecha_ingreso_lista date NOT NULL,
    origen_derivacion   text NOT NULL,
    estado              text NOT NULL CHECK (estado IN ('en_espera', 'citado', 'atendido', 'egresado', 'fallecido'))
);
COMMENT ON TABLE raw.lista_espera IS 'Una solicitud en lista de espera (lista_espera.csv). prioridad_inicial nunca se modifica';
CREATE INDEX IF NOT EXISTS lista_espera_id_paciente_idx ON raw.lista_espera (id_paciente);

CREATE TABLE IF NOT EXISTS raw.eventos_clinicos (
    id_evento    text PRIMARY KEY,
    id_paciente  text NOT NULL REFERENCES raw.pacientes (id_paciente),
    fecha_evento date NOT NULL,
    tipo_evento  text NOT NULL CHECK (tipo_evento IN
                   ('cambio_farmaco', 'control_aps', 'examen_alterado', 'hospitalizacion', 'visita_urgencia')),
    subtipo      text NOT NULL,
    severidad    text NOT NULL CHECK (severidad IN ('leve', 'moderada', 'grave')),
    detalle      text
);
COMMENT ON TABLE raw.eventos_clinicos IS 'Un evento clínico fechado (eventos_clinicos.csv). detalle es una plantilla, no texto libre';
CREATE INDEX IF NOT EXISTS eventos_clinicos_paciente_fecha_idx ON raw.eventos_clinicos (id_paciente, fecha_evento);

CREATE TABLE IF NOT EXISTS raw.mediciones (
    id_paciente    text NOT NULL REFERENCES raw.pacientes (id_paciente),
    fecha_medicion date NOT NULL,
    tipo_medicion  text NOT NULL CHECK (tipo_medicion IN
                     ('HbA1c', 'PHQ9', 'escala_dolor_eva', 'glicemia', 'peak_flow',
                      'presion_diastolica', 'presion_sistolica', 'saturacion_o2')),
    valor          numeric NOT NULL,
    unidad         text NOT NULL,
    fuera_de_rango boolean NOT NULL,
    PRIMARY KEY (id_paciente, fecha_medicion, tipo_medicion)
);
COMMENT ON TABLE raw.mediciones IS 'Una medición fechada (mediciones.csv). Llave natural compuesta';

CREATE TABLE IF NOT EXISTS raw.box (
    id_box text PRIMARY KEY
);
COMMENT ON TABLE raw.box IS 'Dimensión derivada: un box del hospital (id_box distintos de agenda_box.csv)';

CREATE TABLE IF NOT EXISTS raw.agenda_box (
    id_box              text NOT NULL REFERENCES raw.box (id_box),
    fecha               date NOT NULL,
    especialidad        text NOT NULL,
    bloque_inicio       time NOT NULL,
    bloque_fin          time NOT NULL,
    capacidad_cupos     integer NOT NULL CHECK (capacidad_cupos > 0),
    cupos_usados        integer NOT NULL,
    minutos_sobretiempo integer NOT NULL CHECK (minutos_sobretiempo >= 0),
    PRIMARY KEY (id_box, fecha),
    CONSTRAINT agenda_box_bloque_valido CHECK (bloque_fin > bloque_inicio),
    CONSTRAINT agenda_box_cupos_validos CHECK (cupos_usados BETWEEN 0 AND capacidad_cupos)
);
COMMENT ON TABLE raw.agenda_box IS 'El bloque de un box en un día hábil (agenda_box.csv)';

-- Sin FK por (id_box, fecha_cita): 118 de 257 citas no tienen bloque ese día (docs/modelo-datos-raw.md)
CREATE TABLE IF NOT EXISTS raw.citaciones (
    id_cita               text PRIMARY KEY,
    id_paciente           text NOT NULL REFERENCES raw.pacientes (id_paciente),
    id_box                text NOT NULL REFERENCES raw.box (id_box),
    fecha_cita            date NOT NULL,
    especialidad          text NOT NULL,
    estado_cita           text NOT NULL CHECK (estado_cita IN ('asistio', 'no_asistio', 'reprogramo', 'cancelo')),
    minutos_atencion_real integer CHECK (minutos_atencion_real > 0),
    CONSTRAINT citaciones_minutos_solo_si_asistio CHECK ((estado_cita = 'asistio') = (minutos_atencion_real IS NOT NULL))
);
COMMENT ON TABLE raw.citaciones IS 'Una cita ofrecida a un paciente (citaciones.csv)';
CREATE INDEX IF NOT EXISTS citaciones_id_paciente_idx ON raw.citaciones (id_paciente);

-- Bitácora de cargas: qué archivos se cargaron, cuándo y con qué huella
CREATE TABLE IF NOT EXISTS raw.carga_lote (
    id_carga   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inicio     timestamptz NOT NULL,
    fin        timestamptz NOT NULL DEFAULT now(),
    origen     text NOT NULL,
    filas      jsonb NOT NULL,
    archivos   jsonb NOT NULL,
    usuario_db text NOT NULL DEFAULT current_user
);
COMMENT ON TABLE raw.carga_lote IS 'Una carga del esquema raw: filas por tabla y sha256 de cada CSV';
