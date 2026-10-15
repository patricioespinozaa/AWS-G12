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

Leer `docs/contexto.md` y `docs/datos.md` antes de escribir código que toque datos.

## Convenciones

- Idioma: documentación, nombres de dominio y mensajes visibles al usuario en **español**. Código e identificadores pueden ir en inglés, pero los conceptos de dominio conservan su nombre (`interconsulta`, `lista_espera`, `causal_egreso`).
- Diagnósticos en **CIE-10** (catálogo DEIS/MINSAL). Normalizar los códigos antes de compararlos (mayúsculas, con punto: `E11.3`).
- Fechas en ISO 8601. Calcular los días de espera desde la fecha de ingreso a la lista, no desde la derivación, salvo que se indique otra cosa.

## Estado

Stack del MVP (detalle en `docs/mvp.md`):
- `priorizacion/`: motor de dominio en Python (pandas). Las reglas y pesos están en `priorizacion/reglas.py`; todo cambio sube `VERSION_REGLAS`.
- `api/`: FastAPI. `web/`: React + TypeScript + Vite + Recharts.
- Registro local en SQLite (`data/processed/priorizacion.sqlite`, ignorado por git; se regenera al iniciar la API si no existe).
- `db/`: base PostgreSQL en AWS RDS. DDL versionado en `db/sql/<esquema>/` (idempotente), carga de los CSV al esquema `raw` y verificación. Detalle en `docs/feature/subida-datos-aws.md`.

Comandos:
- Instalar: `pip install -r requirements.txt` y `cd web && npm install`
- Ejecutar: `cd web && npm run build`, luego `uvicorn api.main:app --port 8000` (sirve la app en http://127.0.0.1:8000)
- Desarrollo: `uvicorn api.main:app --reload --port 8000` + `cd web && npm run dev` (http://localhost:5173)
- Tests: `python -m pytest` (usa una base temporal)
- Consolidación nocturna: `python -m priorizacion.nocturno`
- Base en AWS: `bash db/infra/crear_rds.sh` (crea la instancia RDS si no existe) y `python -m db restaurar` (crea el esquema `raw`, carga los CSV y verifica). Conexión por `HLF_DATABASE_URL` o `HLF_DB_SECRET_ID` + `HLF_DB_HOST`; nunca credenciales en el repo
- Tests de la base contra PostgreSQL: `HLF_TEST_DATABASE_URL=postgresql://… python -m pytest tests/test_db.py` (usar una base desechable)
- EDA: notebooks en `notebooks/`; `notebooks/carga.py` carga el dataset desde `data/dataset_hlf_ambulatorio/dataset_hlf_ambulatorio/`.
