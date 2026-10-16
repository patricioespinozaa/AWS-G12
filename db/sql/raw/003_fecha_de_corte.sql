-- F0006: fecha de corte de cada versión de los datos. Idempotente.
-- Es el fin del periodo declarado de la carga o, si no lo declaró, la última fecha con datos en raw al aplicarla.
-- priorizacion.fecha_corte() usa la mayor entre las versiones aplicadas: "hoy" para la app es la fecha de los datos.

ALTER TABLE raw.carga_lote ADD COLUMN IF NOT EXISTS fecha_corte date;
COMMENT ON COLUMN raw.carga_lote.fecha_corte IS 'Hasta qué fecha llegan los datos de esta versión (fin del periodo)';

-- Versiones anteriores a esta migración: la última fecha con datos de raw
UPDATE raw.carga_lote
SET fecha_corte = coalesce(periodo_hasta, (SELECT max(f) FROM (
        SELECT max(fecha_evento) AS f FROM raw.eventos_clinicos
        UNION ALL SELECT max(fecha_medicion) FROM raw.mediciones
        UNION ALL SELECT max(fecha_cita) FROM raw.citaciones
        UNION ALL SELECT max(fecha) FROM raw.agenda_box
        UNION ALL SELECT max(fecha_ingreso_lista) FROM raw.lista_espera) fechas))
WHERE estado = 'aplicada' AND fecha_corte IS NULL;

ALTER TABLE raw.carga_lote DROP CONSTRAINT IF EXISTS carga_lote_aplicada_con_corte;
ALTER TABLE raw.carga_lote ADD CONSTRAINT carga_lote_aplicada_con_corte
    CHECK (estado <> 'aplicada' OR fecha_corte IS NOT NULL) NOT VALID;
