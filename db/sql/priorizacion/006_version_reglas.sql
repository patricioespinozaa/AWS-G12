-- Versiones de los parámetros de las reglas (F0014). Idempotente.
--
-- Cada fila es un conjunto completo de parámetros que la Administradora guardó desde la vista Reglas, con los
-- cambios respecto de la versión anterior, el motivo y la autora. Solo inserción: volver a una versión anterior crea
-- una versión nueva con sus valores. La vigente es la de número mayor; sin filas rigen los valores de fábrica
-- (priorizacion/reglas.py). El número viaja en version_reglas de cada evaluación y propuesta ("reglas-v0.1+c<n>").
CREATE TABLE IF NOT EXISTS priorizacion.version_reglas (
    numero      integer PRIMARY KEY CHECK (numero > 0),
    version     text NOT NULL UNIQUE,
    valores     jsonb NOT NULL,
    cambios     jsonb NOT NULL,
    motivo      text NOT NULL CHECK (length(trim(motivo)) >= 5),
    creada_por  text NOT NULL REFERENCES priorizacion.usuario (id_usuario),
    creada_en   timestamptz NOT NULL DEFAULT now(),
    restaura    integer REFERENCES priorizacion.version_reglas (numero),
    CONSTRAINT version_reglas_con_cambios CHECK (cambios <> '{}'::jsonb)
);
COMMENT ON TABLE priorizacion.version_reglas IS
    'Parámetros de las reglas guardados por la Administradora; la vigente es la de número mayor (F0014)';

DROP TRIGGER IF EXISTS version_reglas_solo_insercion ON priorizacion.version_reglas;
CREATE TRIGGER version_reglas_solo_insercion BEFORE UPDATE OR DELETE ON priorizacion.version_reglas
    FOR EACH ROW EXECUTE FUNCTION priorizacion.solo_insercion();

-- Un cambio de reglas recalcula la historia completa con la versión nueva: la corrida queda con origen 'reglas'
ALTER TABLE priorizacion.corrida_nocturna DROP CONSTRAINT IF EXISTS corrida_origen_valido;
ALTER TABLE priorizacion.corrida_nocturna ADD CONSTRAINT corrida_origen_valido
    CHECK (origen IN ('completo', 'carga', 'nocturno', 'solicitud', 'reglas'));
