-- F0005: una sola usuaria (la Administradora) y el contador de versión compartido entre tareas. Idempotente.
-- Definido por el HLF: la Administradora revisa las propuestas, valida lo que llega por el canal del paciente y
-- sube las cargas de datos. Ni médicos ni otro personal usan la plataforma (docs/feature/F0005).

ALTER TABLE priorizacion.usuario DROP CONSTRAINT IF EXISTS usuario_rol_check;
ALTER TABLE priorizacion.usuario ADD CONSTRAINT usuario_rol_check CHECK (rol IN
    ('administracion', 'medico', 'enfermeria', 'tens', 'gestor_lista', 'administrativo', 'sistema'));

INSERT INTO priorizacion.usuario (id_usuario, nombre, rol) VALUES
    ('administradora', 'Administradora', 'administracion')
ON CONFLICT (id_usuario) DO NOTHING;

-- Contador que sube con cada escritura de la app. Cada tarea del backend lo compara con el que vio la última vez
-- y, si cambió, refresca su caché y lo que tiene en memoria (varias tareas detrás del ALB).
CREATE TABLE IF NOT EXISTS priorizacion.estado_app (
    id             smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version        bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE priorizacion.estado_app IS 'Versión de los datos de la app (una fila). Sube con cada escritura';
INSERT INTO priorizacion.estado_app (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
