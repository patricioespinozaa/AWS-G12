# CLAUDE.md

Contexto para agentes de código que trabajen en este repositorio.

## Qué es este proyecto

Prototipo para el desafío **"Evaluación dinámica del riesgo y priorización asistencial"** del Hospital Clínico Dra. Eloísa Díaz La Florida (HLF, SSMSO), en el Hackatón de IA Generativa AWS Breaking Barriers Chile 2026 (14 al 16 de octubre, Universidad de Chile).

**Problema:** la prioridad de un paciente en la lista de espera de especialidad se asigna una sola vez y queda congelada, aunque su salud cambie mientras espera.

**Objetivo:** detectar eventos clínicos durante la espera (urgencias, hospitalizaciones, cambios de tratamiento, descompensaciones) y proponer una **prioridad actualizada, explicable y trazable**, que el equipo clínico valida.

**Alcance inicial:** oftalmología del HLF, con listas separadas de **consultas nuevas** y de **controles**.

## Principio rector (no negociable)

> La herramienta **propone y explica**; el equipo clínico **decide**.
> La posición en la lista no equivale a una fecha garantizada de atención.

Consecuencias para el código:
- Toda prioridad propuesta debe venir con su **explicación**: qué eventos o factores la cambiaron y cuánto aportó cada uno.
- Todo cambio de prioridad debe quedar **registrado**: valor anterior, valor nuevo, motivo, fecha y versión del modelo o las reglas.
- Nunca sobrescribir la prioridad clínica asignada por una persona. La propuesta del sistema se guarda en un campo aparte.
- Preferir reglas y puntajes interpretables por sobre modelos de caja negra. Si se usa un LLM, debe citar el fragmento de texto del que sacó cada hallazgo.

## Datos y privacidad

- El HLF entrega una base **acotada y anonimizada** de usuarios de oftalmología. Ver `docs/datos.md`.
- **Nunca** subir datos del hospital al repositorio. Van en `data/raw/`, que debe estar en `.gitignore`.
- No enviar datos de pacientes a servicios externos fuera del entorno autorizado del hackatón.
- Para tests y demos, usar datos sintéticos (`data/synthetic/`).
- No intentar reidentificar personas ni cruzar los datos con fuentes externas para ese fin.

## Documentación

| Archivo | Contenido |
|---|---|
| `docs/contexto.md` | El desafío, el problema, la ruta del paciente y el caso de don Manuel |
| `docs/datos.md` | Esquema del dataset entregado por el HLF (sintético, 7 especialidades, agenda de box) y advertencias de calidad |
| `docs/casos-ejemplo.md` | Seis pacientes de referencia, uno por patrón de evolución, para tests y demo |
| `docs/eda.md` | Hallazgos del análisis exploratorio (notebooks en `notebooks/`) |
| `docs/kpis.md` | Métricas de éxito y cómo calcularlas |
| `docs/enfoque.md` | Propuesta de arquitectura y del puntaje de priorización |
| `docs/arquitectura.md` | Diagramas: linaje de variables, modelo de datos y trazabilidad, niveles de priorización, flujo y vistas |
| `docs/mvp.md` | El MVP: cómo correrlo, vistas, procesos de backend, puntaje implementado y mapeo a servicios AWS |
| `docs/datasets-externos.md` | Datasets públicos de síntomas, enfermedades y severidad |
| `docs/glosario.md` | Siglas y términos del sistema de salud chileno |
| `docs/feature/F0002-modelo-datos-canales.md` | Modelo de datos de los esquemas `priorizacion` y `canal` (WhatsApp y voz con IA): llaves, vistas del asistente, roles y retención |
| `docs/feature/F0003-flujos-aws-datos.md` | Estructura de datos de los flujos AWS (`docs/diagramas/flujos-aws.pdf`): reloj de la demo, esquema `consulta` (Knowledge Base y preguntas del equipo clínico) y capa S3 + Athena |
| `docs/feature/README.md` | **Hoja de ruta**: estado de cada feature, orden de implementación (F0004 a F0013), estructura de carpetas objetivo y plantilla de los planes. Implementar los planes de a uno, en ese orden |

Leer `docs/contexto.md` y `docs/datos.md` antes de escribir código que toque datos.

## Convenciones

- Idioma: documentación, nombres de dominio y mensajes visibles al usuario en **español**. Código e identificadores pueden ir en inglés, pero los conceptos de dominio conservan su nombre (`interconsulta`, `lista_espera`, `causal_egreso`).
- Diagnósticos en **CIE-10** (catálogo DEIS/MINSAL). Normalizar los códigos antes de compararlos (mayúsculas, con punto: `E11.3`).
- Fechas en ISO 8601. Calcular los días de espera desde la fecha de ingreso a la lista, no desde la derivación, salvo que se indique otra cosa.

## Estado

Stack del MVP (detalle en `docs/mvp.md`):
- `priorizacion/`: motor de dominio en Python (pandas). Las reglas y pesos están en `priorizacion/reglas.py`; todo cambio sube `VERSION_REGLAS`.
- `api/`: FastAPI. `main.py` solo arma la app; rutas por dominio en `api/rutas/`; estado compartido (repositorio, registro, caché) en `api/estado.py`, que las rutas leen como `E.repo` / `E.registro` (nunca copias: una carga lo reemplaza). `web/`: React + TypeScript + Vite + Recharts.
- Dos modos (F0005), elegidos por variables de entorno:
  - **Local** (sin variables de base): lee los CSV de `HLF_DATA_DIR` y guarda en SQLite (`data/processed/priorizacion.sqlite`, ignorado por git). Respaldo de la demo.
  - **RDS** (`HLF_DATABASE_URL` o `HLF_DB_SECRET_ID` + `HLF_DB_HOST`): lee `raw` y guarda en `priorizacion` y `canal`. La API aplica las migraciones al arrancar. Varias tareas se sincronizan por `priorizacion.estado_app`.
  - El registro es un `Protocol` (`priorizacion/registro.py`) con dos implementaciones (`RegistroSQLite`, `RegistroPostgres`) que devuelven DataFrames con las mismas columnas y tipos. Un cambio a una debe hacerse también en la otra (lo verifica `tests/test_persistencia_rds.py`).
- **Única usuaria: la Administradora** (definido por el HLF). Revisa propuestas, valida el canal y sube cargas. La API no recibe el autor en el cuerpo: usa `config.USUARIA` (hasta F0007).
- **Datos por periodo:** cada actualización es una exportación de un periodo nuevo que se **suma** a `raw` (vista Cargas o `python -m db cargar --incremental`). `restaurar` y `--reemplazar` RECONSTRUYEN desde la historia completa y borran lo que no venga: no usarlos con exportaciones parciales.
- `db/`: base PostgreSQL en AWS RDS. DDL versionado en `db/sql/<esquema>/` (idempotente), carga de los CSV al esquema `raw` y verificación. Detalle en `docs/feature/F0001-subida-datos-aws.md` y `F0005-persistencia-app-rds.md`.

Comandos:
- Instalar: `pip install -r requirements.txt` y `cd web && npm install`. Grupos en `requirements/`: `base.txt` (ejecución; lo único que instala la imagen Docker), `dev.txt` (+ tests), `notebooks.txt` (+ EDA). Una dependencia nueva del backend va en `base.txt`
- Ejecutar: `cd web && npm run build`, luego `uvicorn api.main:app --port 8000` (sirve la app en http://127.0.0.1:8000)
- Desarrollo: `uvicorn api.main:app --reload --port 8000` + `cd web && npm run dev` (http://localhost:5173)
- Tests: `python -m pytest` (usa una base temporal). Con PostgreSQL de prueba (`HLF_TEST_DATABASE_URL=…`) corren también las de integración, cargas incrementales y persistencia. Las que necesitan el dataset llevan el marcador `datos` y se saltan sin él (CI). La API contra RDS: `HLF_DATABASE_URL=… python -m pytest tests/test_api.py`
- Consolidación nocturna: `python -m priorizacion.nocturno`
- Base en AWS: `bash db/infra/crear_rds.sh` (crea la instancia RDS si no existe) y `python -m db restaurar` (crea los esquemas `raw`, `priorizacion`, `canal` y `consulta`, carga o sincroniza los CSV en `raw` y verifica todo). Conexión por `HLF_DATABASE_URL` o `HLF_DB_SECRET_ID` + `HLF_DB_HOST`; nunca credenciales en el repo
- Esquemas: `raw` (F0001), `priorizacion` y `canal` (F0002), `consulta` (F0003). Roles: `python -m db permisos`. Borrar: `python -m db borrar --esquema <raw|priorizacion|canal|consulta|todos> --confirmar` (nunca `DROP SCHEMA raw CASCADE` a mano: elimina en silencio las FKs de los otros esquemas)
- Reloj de la demo: `python -m db reloj --demo AAAA-MM-DD`, `--avanzar`, `--real`. Las vistas del asistente usan `priorizacion.fecha_corte()`: nunca `current_date` directo
- S3 + Athena (consultas exactas y agregados): `bash db/infra/crear_s3_athena.sh`, luego `python -m db athena publicar`, `exportar`, `verificar` y `consultar "SELECT …" -p valor`. Requiere `HLF_S3_BUCKET`
- Imagen del backend: `docker build -f docker/backend/Dockerfile -t hlf-backend .` (el dataset se monta como volumen o se descarga de S3 al arrancar: nunca va dentro de la imagen)
- Despliegue en AWS (CDK, F0004): ver `infra/README.md`. Resumen: `cd infra && npx aws-cdk@2 deploy --all -c entorno=demo` con Docker corriendo, después de `python -m db athena publicar`. Pruebas de infraestructura: `cd infra && python -m pytest tests -q`
- Tests de la base contra PostgreSQL: `HLF_TEST_DATABASE_URL=postgresql://… python -m pytest tests/test_db.py` (usar una base desechable)
- EDA: notebooks en `notebooks/`; `notebooks/carga.py` carga el dataset desde `data/dataset_hlf_ambulatorio/dataset_hlf_ambulatorio/`.
