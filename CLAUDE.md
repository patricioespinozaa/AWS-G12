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
| `docs/kpis.md` | Métricas de éxito y cómo calcularlas |
| `docs/enfoque.md` | Propuesta de arquitectura y del puntaje de priorización |
| `docs/contexto-tecnico.md` | Diseño técnico detallado: servicios AWS por capa, contrato de datos, motor de reglas, copiloto IA, auditoría y FHIR, seguridad, resiliencia, pruebas y temas abiertos |
| `docs/datasets-externos.md` | Datasets públicos de síntomas, enfermedades y severidad |
| `docs/glosario.md` | Siglas y términos del sistema de salud chileno |

Leer `docs/contexto.md` y `docs/datos.md` antes de escribir código que toque datos.

## Convenciones

- Idioma: documentación, nombres de dominio y mensajes visibles al usuario en **español**. Código e identificadores pueden ir en inglés, pero los conceptos de dominio conservan su nombre (`interconsulta`, `lista_espera`, `causal_egreso`).
- Diagnósticos en **CIE-10** (catálogo DEIS/MINSAL). Normalizar los códigos antes de compararlos (mayúsculas, con punto: `E11.3`).
- Fechas en ISO 8601. Calcular los días de espera desde la fecha de ingreso a la lista, no desde la derivación, salvo que se indique otra cosa.

## Estado

- **Stack de referencia:** definido en la sección 0 de `docs/contexto-tecnico.md` (Python 3.12, AWS SAM, Step Functions + Lambda + Glue, S3 + Athena + DynamoDB, Bedrock, API Gateway + Cognito, React). Para el MVP solo está implementada U1 (local, sin AWS).
- **Región AWS:** abierta (tema T1 de `docs/contexto-tecnico.md`); condiciona la capa FHIR y los modelos de Bedrock.
- **Código implementado:** U1 (núcleo de datos y motor de reglas), U2 (copiloto IA en modo barrido, `src/hlf_priorizacion/copiloto/`) y U3 (bandeja local, `src/hlf_priorizacion/bandeja/` y `app/`) en `src/hlf_priorizacion/`, con pruebas en `tests/`. Resumen en `aidlc-docs/construction/u1-nucleo-motor/code/resumen.md`.
- **Instalación:** `uv sync` (Python 3.12; versiones exactas en `pyproject.toml` y `uv.lock`).
- **Ejecución del lote:** `uv run hlf-lote --fecha-corte AAAA-MM-DD [--datos data/dataset_hlf_ambulatorio] [--salidas salidas] [--reglas RUTA]`. Las salidas van a `salidas/` (ignorado por git).
- **Copiloto IA (U2, modo barrido):** `uv run hlf-copiloto (--fecha-corte AAAA-MM-DD | --desde AAAA-MM-DD --hasta AAAA-MM-DD) [--forzar] [--max-llamadas N]`. Usa Bedrock (`us.anthropic.claude-sonnet-5` por defecto, `HLF_BEDROCK_MODEL_ID` para cambiarlo) con la cadena estándar de credenciales; requiere las salidas de `hlf-lote` de cada fecha. Resultados en `salidas/analisis/`. Ctrl+C es seguro (exit 130): cada solicitud se guarda apenas termina y volver a ejecutar el mismo comando sigue con el resto. Resumen en `aidlc-docs/construction/u2-copiloto/code/resumen.md`. La prueba real se corre con `uv run pytest -m bedrock -s` (excluida por defecto).
- **Bandeja (U3, demo local en Streamlit):** `. .\scripts\entorno-demo.ps1` y `uv run streamlit run app/bandeja.py` (solo `127.0.0.1`, sin login, sin telemetría). Lógica en `src/hlf_priorizacion/bandeja/` (`datos`, `filas`, `cambios`, `decisiones`); `app/bandeja.py` solo presenta. Solo lectura sobre `salidas/` (nunca corre el lote ni el copiloto ni llama a Bedrock); escribe únicamente `salidas/decisiones/decisiones.jsonl` (solo agregar) y el evento `decision_medica`. Rutas configurables con `HLF_SALIDAS` y `HLF_DATOS`. Recorrido de la demo: IC-HLF-00002 baja el 2026-07-19 → crítica el 2026-07-20 con EV-000004 y BR_EVENTO_GRAVE_30D en "¿Qué cambió?", detalle con análisis, decisión "aceptar" con "Dra. Demo Uno"; IC-HLF-00349 (2026-07-19) con advertencia de equidad. Resumen en `aidlc-docs/construction/u3-bandeja/code/resumen.md`.
- **Pruebas y controles:** `uv run pytest` (perfil Hypothesis `ci` por defecto; `HYPOTHESIS_PROFILE=dev` para explorar), `uv run ruff check`, `uv run mypy src`, `uv run pip-audit`.
