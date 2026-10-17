# AWS-G12 · Priorización dinámica de la lista de espera (HLF)

Prototipo para el desafío "Evaluación dinámica del riesgo y priorización asistencial" del Hospital Clínico Dra. Eloísa Díaz La Florida, en el Hackatón de IA Generativa AWS Breaking Barriers Chile 2026.

> La herramienta propone y explica; el equipo clínico decide.

## Ejecutar en local

Todo el flujo de priorización corre en tu computador, sin AWS ni credenciales: la app lee los CSV del dataset y guarda
sus decisiones en una base local. No hay inicio de sesión; lo que se registra queda a nombre de `administradora`
(variable `HLF_USUARIA`).

**Requisitos:** Python 3.11, Node 20 o superior y el dataset del HLF en
`data/dataset_hlf_ambulatorio/dataset_hlf_ambulatorio/` (los 6 CSV: `pacientes`, `lista_espera`, `eventos_clinicos`,
`mediciones`, `citaciones` y `agenda_box`). El dataset no se versiona: se pide al equipo. Para la carga de datos por
periodo hace falta además Docker.

### 1. Modo local (SQLite): todas las vistas de consulta y decisión

```bash
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
uvicorn api.main:app --port 8000            # http://127.0.0.1:8000
```

El primer arranque calcula la serie nocturna completa (unos segundos). Las decisiones, ajustes y validaciones se guardan
en `data/processed/priorizacion.sqlite` (no se versiona); para empezar de cero, borra ese archivo.

### 2. Modo base de datos (PostgreSQL en Docker): agrega la vista Cargas

La carga de exportaciones por periodo usa la misma base que en AWS (PostgreSQL), así que se levanta una local:

```bash
docker run -d --name hlf-pg -e POSTGRES_PASSWORD=local -p 55432:5432 postgres:16
export HLF_DATABASE_URL=postgresql://postgres:local@127.0.0.1:55432/postgres
python -m db --url "$HLF_DATABASE_URL" restaurar     # esquemas + los 6 CSV + verificación
uvicorn api.main:app --port 8000                    # la app aplica las migraciones al arrancar
```

En PowerShell, la variable va con `$env:HLF_DATABASE_URL = "postgresql://…"`. Para volver a los datos originales repite
`restaurar` (reconstruye desde los CSV y borra lo cargado después).

**Exportaciones de prueba para la vista Cargas:** `python scripts/eventos_demo.py --simular` escribe en
`data/eventos_demo/` tres exportaciones de eventos clínicos (`prueba`, `demo` y `demo2`, cada una con su
`periodo.json`) y muestra cómo cambia la cola. En **Cargas de datos** se indica el periodo, se sube el CSV, se revisa la
vista previa y se confirma; las prioridades se recalculan solas.

### 3. Lo que necesita AWS (opcional)

Estas funciones usan servicios de AWS y se activan con variables de entorno y tus propias credenciales (perfil de AWS
CLI o variables `AWS_*`). Las credenciales **nunca** van en el repositorio: si usas un archivo `.env`, está en
`.gitignore`.

| Función | Variables |
|---|---|
| Explicaciones redactadas con IA (Bedrock) | `LLM_PROVEEDOR=bedrock`, `BEDROCK_MODEL_ID`, opcional `BEDROCK_GUARDRAIL_ID` y `BEDROCK_GUARDRAIL_VERSION` |
| Consulta en lenguaje natural (con el modo base de datos) | `HLF_KB_ID`, `HLF_KB_DATA_SOURCE_ID`, `HLF_S3_BUCKET`, `HLF_ATHENA_WORKGROUP` |
| Asistente del paciente (WhatsApp, voz) y lectura de exámenes | Solo desplegado: ver `infra/README.md` |

Sin esas variables la app funciona igual: las explicaciones salen de una plantilla determinista y las vistas que
dependen de AWS lo indican.

### 4. Desplegar en tu propia cuenta de AWS

`infra/README.md` describe el despliegue con CDK (`cd infra && npx aws-cdk@2 deploy --all -c entorno=demo`). Cada
persona que use la app desplegada tiene su propia cuenta en Cognito: `bash infra/scripts/crear_cuenta.sh <usuario>
"<Nombre>" [correo]`. No se comparten contraseñas ni se escriben en el repositorio.

### Pruebas

```bash
pip install -r requirements/dev.txt
python -m pytest                                    # usa una base temporal; sin dataset se saltan las que lo necesitan
```

## Documentación

- `docs/mvp.md`: el MVP (vistas, backend, puntaje y servicios AWS)
- `docs/contexto.md`, `docs/datos.md`, `docs/eda.md`: el problema, los datos y el análisis exploratorio
- `docs/arquitectura.md`, `docs/enfoque.md`, `docs/propuestas-solucion.md`: diseño de la solución
- `docs/kpis.md`, `docs/casos-ejemplo.md`, `docs/glosario.md`
