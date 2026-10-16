# Plan de Code Generation — U3 Bandeja y vistas (Streamlit)

Este plan es la única fuente de verdad para generar U3. Se ejecuta en orden y cada paso se marca `[x]` al terminar.

## Contexto de la unidad

| | |
|---|---|
| Unidad | U3 (componentes C8 bandeja y C11 web, versión demo local) |
| Diseño | `aidlc-docs/construction/u3-bandeja/functional-design/` (entidades, reglas B1–B7, modelo lógico y propiedades, componentes de interfaz) |
| Requisitos | RF-01 (solo el médico cambia el estado), RF-04 (selector de corte), RF-08 y RF-13 (parcial) |
| Depende de | U1 (`leer_propuestas`, `contexto_a_fecha`, `linea_tiempo`, `huella_contexto`, `Decision`, auditoría, logs) y U2 (`leer_analisis`, `leer_fallidos`, `leer_hallazgos_dq`, `leer_cohortes`, `RegistroAnalisis.revision_equidad`) |
| Datos disponibles | Propuestas: 2026-07-19, 07-20, 07-21, 08-10, 10-13. Análisis: 07-19 a 07-21 (95). Marca de equidad: IC-HLF-00349 (07-19) |
| Ubicación | `src/hlf_priorizacion/bandeja/`, `app/` y `tests/`. Nunca en `aidlc-docs/` |

## Restricciones

- **B1 solo lectura:** la interfaz no ejecuta el lote ni el copiloto y **no llama a Bedrock**. Solo escribe `salidas/decisiones/decisiones.jsonl` y su evento de auditoría.
- **Sin texto como HTML:** nada que venga del modelo o de los datos se muestra con `unsafe_allow_html`.
- **Logs:** sin texto clínico, sin texto del modelo y sin el motivo escrito por el médico; solo IDs, decisión y códigos (SECURITY-03).
- **Validación** del formulario con `Decision` (Pydantic estricto); motivo ≤ 1000 caracteres (SECURITY-05). Errores con mensaje genérico y manejo explícito de E/S (SECURITY-15).
- **Dependencias:** `streamlit` con versión exacta; `pip-audit` limpio (SECURITY-10).
- **Servidor:** solo `127.0.0.1` y telemetría desactivada.
- **No romper U1 ni U2:** hoy pasan 230 pruebas + 1 excluida (bedrock).
- **PBT:** generadores en `tests/estrategias/`; perfil `ci` con `derandomize=True`.

## Pasos

### Paso 1 — Dependencias y estructura
- [x] Agregar `streamlit` con versión exacta; `uv lock`, `uv sync`; `pip-audit`
- [x] Carpetas `src/hlf_priorizacion/bandeja/` y `app/`; `app/.streamlit/config.toml` según `frontend-components.md`
- [x] `app/config_demo.py`: lista fija de 3 médicos ficticios (`MED-DEMO-01` "Dra. Demo Uno", etc.)

### Paso 2 — Datos (`bandeja/datos.py`)
- [x] Cortes disponibles desde `salidas/propuestas/`; carga de propuestas (con especialidad), análisis, fallidos, DQ, cohortes, resumen del lote
- [x] Reconstrucción del contexto y línea de tiempo con verificación de huella; resultado `huella_distinta` sin línea de tiempo
- [x] Mensajes con el comando exacto cuando faltan propuestas o análisis (B1.2, B1.3)

### Paso 3 — Bandeja (`bandeja/filas.py`)
- [x] `FilaBandeja`, orden B2.2 determinista, filtros B2.3, indicadores B2.5

### Paso 4 — "¿Qué cambió?" (`bandeja/cambios.py`)
- [x] `CambioEntreCortes` según B4: cambios, ingresos nuevos, pasaron a exclusión; registros nuevos con fecha en (corte_a, corte_b]

### Paso 5 — Decisiones (`bandeja/decisiones.py`)
- [x] Guardar `Decision` (ULID, timestamp UTC, `id_analisis`) solo agregando a `decisiones.jsonl`; evento `decision_medica`; lectura del historial y de la decisión vigente (B5)

### Paso 6 — Interfaz (`app/bandeja.py`)
- [x] Barra lateral y cuatro pestañas según `frontend-components.md`, con `key` estables (`{vista}-{elemento}`)
- [x] Detalle: advertencia de equidad antes del análisis (B3.5), rótulo "Sugerencia del copiloto — no es una decisión", factores con IDs y línea de tiempo resaltada
- [x] Formulario de decisión con validación y mensajes; deshabilitado sin médico
- [x] Caché por `(corte, version_reglas)`; invalidar solo decisiones al guardar
- [x] Script `hlf-bandeja` o instrucción `uv run streamlit run app/bandeja.py`

### Paso 7 — Pruebas
- [x] `tests/propiedades/`: las 11 propiedades de `business-logic-model.md`
- [x] `tests/ejemplos/`: recorrido de la demo con el dataset real (se salta si falta): IC-HLF-00002 baja el 07-19, crítica el 07-20 con EV-000004 como registro nuevo, análisis presente; IC-HLF-00349 con advertencia; cada error del formulario; corte sin propuestas; solicitud sin análisis; huella distinta
- [x] `tests/interfaz/`: `streamlit.testing.v1.AppTest` — carga sin errores, elegir médico y corte, abrir IC-HLF-00002, guardar una decisión en una carpeta temporal y comprobar el archivo

### Paso 8 — Verificación
- [x] `uv run ruff check`, `uv run mypy src`, `uv run pytest`, `uv run pip-audit`: limpios; las 230 anteriores siguen pasando
- [x] Arrancar la app en segundo plano en `127.0.0.1` y comprobar que responde (HTTP 200 en `/` y en `/_stcore/health`). Si Chrome DevTools MCP está disponible, recorrer la demo en el navegador y tomar capturas; si no, dejarlo indicado
- [x] Comprobar que la verificación no escribió decisiones en `salidas/` real (usar carpeta temporal) y que no hubo llamadas a Bedrock
- [x] Detener la app al terminar

### Paso 9 — Documentación
- [x] `aidlc-docs/construction/u3-bandeja/code/resumen.md`: archivos, cómo ejecutar, verificación, desviaciones
- [x] `README.md` y `CLAUDE.md` (Estado): cómo abrir la bandeja y el recorrido de la demo
- [x] Entrada en `aidlc-docs/audit.md` (solo agregar)

## Fuera de este plan

Autenticación real (Cognito), React, despliegue (U4), vista de box (U5), FHIR (U6), precálculo del corte 2026-10-13 con el copiloto (se decide al preparar la demo).
