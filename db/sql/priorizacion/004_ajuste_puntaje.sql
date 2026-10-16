-- Ajuste del puntaje por la Administradora (F0007). Idempotente.
--
-- La Administradora puede corregir el PUNTAJE DE ORDEN de una solicitud (su lugar dentro de la cola de su nivel),
-- además del nivel. No sobrescribe lo que calculó el motor: la decisión guarda el puntaje que calculó el motor ese
-- día y el ajuste (puntaje que fijó la Administradora − puntaje del motor). Desde esa fecha, el puntaje vigente es
-- el del motor de cada noche + el ajuste, hasta la siguiente decisión que lo cambie. Así los eventos clínicos
-- nuevos siguen moviendo al paciente.

ALTER TABLE priorizacion.decision_clinica ADD COLUMN IF NOT EXISTS puntaje_calculado numeric(8, 3);
ALTER TABLE priorizacion.decision_clinica ADD COLUMN IF NOT EXISTS ajuste_puntaje numeric(8, 3);
COMMENT ON COLUMN priorizacion.decision_clinica.puntaje_calculado IS
    'Puntaje de orden que calculó el motor a la fecha de la decisión';
COMMENT ON COLUMN priorizacion.decision_clinica.ajuste_puntaje IS
    'Ajuste de la Administradora al puntaje de orden. NULL = mantiene el ajuste anterior; 0 = vuelve al del motor';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'decision_ajuste_con_calculado') THEN
        ALTER TABLE priorizacion.decision_clinica ADD CONSTRAINT decision_ajuste_con_calculado
            CHECK (ajuste_puntaje IS NULL OR puntaje_calculado IS NOT NULL);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'decision_ajuste_acotado') THEN
        ALTER TABLE priorizacion.decision_clinica ADD CONSTRAINT decision_ajuste_acotado
            CHECK (ajuste_puntaje IS NULL OR ajuste_puntaje BETWEEN -100 AND 100);
    END IF;
END
$$;

-- La serie guarda el ajuste vigente de cada noche: el puntaje del motor queda intacto en `puntaje`
ALTER TABLE priorizacion.serie_nocturna ADD COLUMN IF NOT EXISTS ajuste_puntaje numeric(8, 3) NOT NULL DEFAULT 0;
COMMENT ON COLUMN priorizacion.serie_nocturna.ajuste_puntaje IS
    'Ajuste vigente de la Administradora esa noche. Puntaje vigente = puntaje + ajuste_puntaje (ordena la cola)';
