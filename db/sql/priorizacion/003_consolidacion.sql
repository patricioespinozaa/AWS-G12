-- F0006: bitácora de la consolidación y particiones anuales de la simulación histórica. Idempotente.

-- Cada corrida dice de dónde vino y cómo terminó (las cargas recalculan en segundo plano)
ALTER TABLE priorizacion.corrida_nocturna
    ADD COLUMN IF NOT EXISTS origen   text,
    ADD COLUMN IF NOT EXISTS estado   text,
    ADD COLUMN IF NOT EXISTS id_carga bigint REFERENCES raw.carga_lote (id_carga),
    ADD COLUMN IF NOT EXISTS detalle  jsonb,
    ADD COLUMN IF NOT EXISTS error    text;
UPDATE priorizacion.corrida_nocturna SET origen = 'completo' WHERE origen IS NULL AND alcance = 'historia completa';
UPDATE priorizacion.corrida_nocturna SET origen = 'solicitud' WHERE origen IS NULL;
UPDATE priorizacion.corrida_nocturna SET estado = 'completa' WHERE estado IS NULL;
ALTER TABLE priorizacion.corrida_nocturna ALTER COLUMN origen SET NOT NULL;
ALTER TABLE priorizacion.corrida_nocturna ALTER COLUMN estado SET NOT NULL;
ALTER TABLE priorizacion.corrida_nocturna ALTER COLUMN estado SET DEFAULT 'completa';
ALTER TABLE priorizacion.corrida_nocturna DROP CONSTRAINT IF EXISTS corrida_origen_valido;
ALTER TABLE priorizacion.corrida_nocturna ADD CONSTRAINT corrida_origen_valido
    CHECK (origen IN ('completo', 'carga', 'nocturno', 'solicitud'));
ALTER TABLE priorizacion.corrida_nocturna DROP CONSTRAINT IF EXISTS corrida_estado_valido;
ALTER TABLE priorizacion.corrida_nocturna ADD CONSTRAINT corrida_estado_valido
    CHECK (estado IN ('en_curso', 'completa', 'fallida'));
ALTER TABLE priorizacion.corrida_nocturna DROP CONSTRAINT IF EXISTS corrida_terminada_con_fin;
ALTER TABLE priorizacion.corrida_nocturna ADD CONSTRAINT corrida_terminada_con_fin
    CHECK ((estado = 'en_curso') = (fin IS NULL)) NOT VALID;
CREATE INDEX IF NOT EXISTS corrida_estado_idx ON priorizacion.corrida_nocturna (estado, id_corrida DESC);

-- Particiones anuales de serie_nocturna. Si la partición DEFAULT ya tiene filas de ese año, se mueven:
-- PostgreSQL no permite crear la partición mientras DEFAULT tenga filas que le corresponderían.
CREATE OR REPLACE FUNCTION priorizacion.asegurar_particion_serie(p_anio integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_nombre text := format('serie_nocturna_%s', p_anio);
    v_desde date := make_date(p_anio, 1, 1);
    v_hasta date := make_date(p_anio + 1, 1, 1);
BEGIN
    IF to_regclass(format('priorizacion.%I', v_nombre)) IS NOT NULL THEN
        RETURN;
    END IF;
    CREATE TEMP TABLE IF NOT EXISTS _serie_movida (LIKE priorizacion.serie_nocturna) ON COMMIT DROP;
    DELETE FROM _serie_movida;
    WITH movidas AS (
        DELETE FROM priorizacion.serie_nocturna_default WHERE fecha >= v_desde AND fecha < v_hasta RETURNING *
    )
    INSERT INTO _serie_movida SELECT * FROM movidas;
    EXECUTE format('CREATE TABLE priorizacion.%I PARTITION OF priorizacion.serie_nocturna FOR VALUES FROM (%L) TO (%L)',
                   v_nombre, v_desde, v_hasta);
    INSERT INTO priorizacion.serie_nocturna SELECT * FROM _serie_movida;
END
$$;
COMMENT ON FUNCTION priorizacion.asegurar_particion_serie(integer) IS
    'Crea la partición anual de la serie nocturna si falta (moviendo las filas que estén en DEFAULT)';

SELECT priorizacion.asegurar_particion_serie(a) FROM generate_series(2025, 2027) AS a;
