-- F0005 fase B: cargas por periodo que se suman a lo existente, versionadas y con historial de cambios.
-- Idempotente. Detalle en docs/feature/F0005-persistencia-app-rds.md.

-- Cada carga es una versión. Las anteriores a esta migración (cargas completas) quedan como versiones aplicadas.
ALTER TABLE raw.carga_lote
    ADD COLUMN IF NOT EXISTS version       integer,
    ADD COLUMN IF NOT EXISTS modo          text,
    ADD COLUMN IF NOT EXISTS estado        text,
    ADD COLUMN IF NOT EXISTS periodo_desde date,
    ADD COLUMN IF NOT EXISTS periodo_hasta date,
    ADD COLUMN IF NOT EXISTS cargado_por   text,
    ADD COLUMN IF NOT EXISTS uri_archivos  text,
    ADD COLUMN IF NOT EXISTS resumen       jsonb,
    ADD COLUMN IF NOT EXISTS advertencias  jsonb,
    ADD COLUMN IF NOT EXISTS errores       jsonb;

-- La primera carga de la historia es la versión inicial; las siguientes fueron reconstrucciones completas
UPDATE raw.carga_lote SET modo = CASE WHEN id_carga = (SELECT min(id_carga) FROM raw.carga_lote)
                                      THEN 'inicial' ELSE 'reconstruccion' END WHERE modo IS NULL;
UPDATE raw.carga_lote SET estado = 'aplicada' WHERE estado IS NULL;
UPDATE raw.carga_lote SET cargado_por = usuario_db WHERE cargado_por IS NULL;
UPDATE raw.carga_lote c SET version = v.n
FROM (SELECT id_carga, row_number() OVER (ORDER BY id_carga) AS n FROM raw.carga_lote WHERE estado = 'aplicada') v
WHERE c.id_carga = v.id_carga AND c.version IS NULL;

ALTER TABLE raw.carga_lote ALTER COLUMN modo SET NOT NULL;
ALTER TABLE raw.carga_lote ALTER COLUMN estado SET NOT NULL;
ALTER TABLE raw.carga_lote ALTER COLUMN cargado_por SET NOT NULL;
ALTER TABLE raw.carga_lote DROP CONSTRAINT IF EXISTS carga_lote_modo_check;
ALTER TABLE raw.carga_lote ADD CONSTRAINT carga_lote_modo_check
    CHECK (modo IN ('inicial', 'incremental', 'reconstruccion'));
ALTER TABLE raw.carga_lote DROP CONSTRAINT IF EXISTS carga_lote_estado_check;
ALTER TABLE raw.carga_lote ADD CONSTRAINT carga_lote_estado_check
    CHECK (estado IN ('validando', 'lista', 'aplicada', 'descartada', 'fallida'));
ALTER TABLE raw.carga_lote DROP CONSTRAINT IF EXISTS carga_lote_version_aplicada;
ALTER TABLE raw.carga_lote ADD CONSTRAINT carga_lote_version_aplicada
    CHECK ((estado = 'aplicada') = (version IS NOT NULL));
ALTER TABLE raw.carga_lote DROP CONSTRAINT IF EXISTS carga_lote_periodo_valido;
ALTER TABLE raw.carga_lote ADD CONSTRAINT carga_lote_periodo_valido
    CHECK (periodo_hasta IS NULL OR periodo_desde IS NULL OR periodo_hasta >= periodo_desde);
CREATE UNIQUE INDEX IF NOT EXISTS carga_lote_version_uq ON raw.carga_lote (version) WHERE version IS NOT NULL;
COMMENT ON TABLE raw.carga_lote IS
    'Una carga de raw. Las aplicadas son versiones numeradas; las de modo incremental suman datos y nunca borran';

-- Procedencia por fila: qué carga trajo cada fila y cuál la cambió por última vez
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['pacientes', 'lista_espera', 'eventos_clinicos', 'mediciones', 'box', 'agenda_box',
                             'citaciones'] LOOP
        EXECUTE format('ALTER TABLE raw.%I ADD COLUMN IF NOT EXISTS id_carga_alta bigint '
                       'REFERENCES raw.carga_lote (id_carga)', t);
        EXECUTE format('ALTER TABLE raw.%I ADD COLUMN IF NOT EXISTS id_carga_modificacion bigint '
                       'REFERENCES raw.carga_lote (id_carga)', t);
        -- Filas cargadas antes de esta migración: vienen de la primera versión
        EXECUTE format('UPDATE raw.%I SET id_carga_alta = (SELECT min(id_carga) FROM raw.carga_lote '
                       'WHERE estado = ''aplicada'') WHERE id_carga_alta IS NULL', t);
    END LOOP;
END
$$;

-- Historial: el valor anterior de cada fila que una carga modificó. Solo inserciones.
CREATE TABLE IF NOT EXISTS raw.cambio_fila (
    id_cambio bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_carga  bigint NOT NULL REFERENCES raw.carga_lote (id_carga),
    tabla     text NOT NULL CHECK (tabla IN ('pacientes', 'lista_espera', 'eventos_clinicos', 'mediciones', 'box',
                                            'agenda_box', 'citaciones')),
    llave     jsonb NOT NULL,
    antes     jsonb NOT NULL,
    despues   jsonb NOT NULL
);
COMMENT ON TABLE raw.cambio_fila IS 'Valor anterior y nuevo de cada fila de raw que modificó una carga incremental';
CREATE INDEX IF NOT EXISTS cambio_fila_carga_idx ON raw.cambio_fila (id_carga, tabla);

CREATE OR REPLACE FUNCTION raw.cambio_fila_solo_insercion() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'raw.cambio_fila es de solo inserción: % no permitido', TG_OP;
END
$$;
DROP TRIGGER IF EXISTS cambio_fila_solo_insercion ON raw.cambio_fila;
CREATE TRIGGER cambio_fila_solo_insercion BEFORE UPDATE OR DELETE ON raw.cambio_fila
    FOR EACH ROW EXECUTE FUNCTION raw.cambio_fila_solo_insercion();
