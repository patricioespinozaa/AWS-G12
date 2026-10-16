# U3 — Bandeja y vistas: resumen de código

Plan: `aidlc-docs/construction/plans/u3-bandeja-code-generation-plan.md` (todos los pasos marcados). Diseño: `aidlc-docs/construction/u3-bandeja/functional-design/`.

## Archivos

| Archivo | Contenido |
|---|---|
| `pyproject.toml`, `uv.lock` | `streamlit==1.66.0` (versión exacta) |
| `src/hlf_priorizacion/bandeja/__init__.py` | Paquete U3 (no importa ni llama a Bedrock) |
| `src/hlf_priorizacion/bandeja/datos.py` | `rutas()` (`HLF_SALIDAS` / `HLF_DATOS` con valores por defecto del repositorio), `cortes_disponibles()`, `cargar_corte()` → `DatosCorte` (propuestas con especialidad, análisis, fallidos, DQ, cohortes, resumen), `CorteSinPropuestas` con el comando exacto, `comando_lote()` / `comando_copiloto()`, `marcas_equidad()`, `cargar_repositorio()` y `reconstruir_contexto()` (huella verificada; `huella_distinta` o `contexto_no_disponible` sin línea de tiempo), `cobertura()` (B6), textos fijos (rótulo del copiloto, advertencia de equidad, aviso de demo) |
| `src/hlf_priorizacion/bandeja/filas.py` | `FilaBandeja`, `construir_filas()`, `clave_orden()` / `ordenar()` (B2.2), `Filtros` / `filtrar()` (B2.1, B2.3), `contador()` |
| `src/hlf_priorizacion/bandeja/cambios.py` | `CambioEntreCortes`, `ComparacionCortes`, `comparar()` (cambios, ingresos nuevos, pasaron a exclusión; registros nuevos con fecha en (A, B]), `validar_cortes()` (A < B) |
| `src/hlf_priorizacion/bandeja/decisiones.py` | `crear_decision()` (valida con `Decision`; motivo ≤ 1000; errores legibles en `ErrorDecision`), `guardar_decision()` (solo agregar a `salidas/decisiones/decisiones.jsonl` + evento `decision_medica` en `salidas/auditoria/eventos.jsonl` con actor `medico:<id>`, sin motivo; log sin motivo), `leer_decisiones()`, `vigentes()`, `historial()`, `estados_del_corte()`, `niveles_ajuste()` |
| `app/bandeja.py` | Streamlit: barra lateral (médico, corte, versión de reglas, aviso) y pestañas Bandeja, Detalle, ¿Qué cambió?, Cobertura. Solo presenta |
| `app/config_demo.py` | `MED-DEMO-01` "Dra. Demo Uno", `MED-DEMO-02` "Dr. Demo Dos", `MED-DEMO-03` "Dra. Demo Tres" |
| `app/.streamlit/config.toml` | `server.address = "127.0.0.1"`, `server.headless = true`, `browser.gatherUsageStats = false`, `client.toolbarMode = "minimal"` |
| `tests/estrategias/bandeja.py` | Generadores (evaluaciones, filas, filtros, cortes con líneas de tiempo, decisiones) y ayudantes de lote sintético en temporales |
| `tests/propiedades/test_prop_bandeja.py` | Las 11 propiedades de `business-logic-model.md` (P11 con `RuleBasedStateMachine`) |
| `tests/ejemplos/test_bandeja.py` | Recorrido de la demo con datos reales (solo lectura, se salta si faltan), cada error del formulario, corte sin propuestas, sin análisis, fallido, huella distinta, auditoría y logs sin motivo |
| `tests/interfaz/test_app_bandeja.py` | `AppTest`: carga, médico y corte, Detalle de IC-TST-00001 / IC-HLF-00002, guardar en temporales, errores del formulario, advertencia de equidad antes del análisis, ¿Qué cambió?, Cobertura, sin propuestas, huella distinta |

Claves de widgets (`{vista}-{elemento}`): `lateral-medico`, `lateral-corte`, `app-pestana`, `bandeja-filtro-especialidad`, `bandeja-filtro-nivel`, `bandeja-filtro-tipo`, `bandeja-filtro-decision`, `bandeja-filtro-analisis`, `bandeja-filtro-equidad`, `bandeja-filtro-sin-alerta`, `bandeja-tabla`, `detalle-solicitud`, `detalle-resaltar`, `detalle-decision-radio`, `detalle-decision-prioridad`, `detalle-decision-motivo`, `detalle-decision-guardar`, `cambios-corte-a`, `cambios-corte-b`, `cambios-tabla`.

## Cómo ejecutar

```powershell
. .\scripts\entorno-demo.ps1
uv run streamlit run app/bandeja.py
```

Abre en `http://127.0.0.1:8501`. `HLF_SALIDAS` y `HLF_DATOS` cambian las carpetas (por defecto `salidas/` y `data/dataset_hlf_ambulatorio/`).

## Verificación (2026-10-16, desde la raíz, tras `. .\scripts\entorno-demo.ps1`)

| Comando | Resultado |
|---|---|
| `uv add streamlit==1.66.0`, `uv lock`, `uv sync` | 90 paquetes resueltos; `streamlit==1.66.0` en `pyproject.toml` |
| `uv run ruff check` | All checks passed |
| `uv run mypy src` (strict) | Success: no issues found in 44 source files |
| `uv run pytest` (marcadores por defecto) | **271 passed, 1 deselected** (bedrock) en 72,4 s. 230 anteriores + 41 nuevas: 11 propiedades, 19 de ejemplo, 11 de interfaz. Ninguna se saltó (dataset y salidas reales presentes) |
| `uv run pytest tests/interfaz` (AppTest) | 11 passed en 12,0 s |
| `uv run pip-audit` | No known vulnerabilities found (solo se omite el propio `hlf-priorizacion`, que no está en PyPI) |
| App en segundo plano: `uv run streamlit run app/bandeja.py --server.port 49353` con `HLF_SALIDAS` en una copia temporal | `GET /_stcore/health` → **200** `ok`; `GET /` → **200** (6467 bytes); escucha solo en `127.0.0.1:49353`. Proceso detenido después (0 sockets en escucha) |
| Bedrock / boto3 | No se llamó. Al cargar la app con `AppTest`, `boto3`, `botocore` y `hlf_priorizacion.copiloto.cliente` no quedan en `sys.modules` |
| `salidas/` real | `salidas/decisiones/decisiones.jsonl` no existía antes y sigue sin existir. `salidas/auditoria/eventos.jsonl`: 12529 líneas y SHA-256 `9605A208…E126F` antes y después. `analisis.jsonl` 07-19/20/21 `58EC8D7A…`, `D4EA6404…`, `4D20AEAB…` y `fallidos.jsonl` `161EA84D…`, `7E5C005C…`, iguales a los de U2. Las pruebas y la verificación escribieron solo en carpetas temporales (ya borradas) |
| Navegador (Chrome DevTools MCP) | No fue posible: el MCP no está configurado en esta sesión (`mcp.json` está en la raíz, no en `.kiro/settings/`). Se usó `AppTest` y el chequeo HTTP |

El recorrido de la demo queda cubierto por `test_demo_00002_…`, `test_demo_00349_…`, `test_real_00002_en_detalle_y_decision_aceptada`, `test_real_que_cambio_0719_0720` y `test_real_00349_advertencia_de_equidad`.

## Desviaciones

| # | Qué | Motivo |
|---|---|---|
| D-1 | La advertencia de equidad usa `RegistroAnalisis.revision_equidad` y, si viene vacía, aplica al leer `frases_revision_equidad()` de U2 (C6.5 regla 2, determinista, sin modelo) | Los 95 análisis guardados son anteriores a la marca y no la traen (`revision-equidad-guardados.md`); son solo agregar y no se reescriben. Así IC-HLF-00349 (07-19) muestra la advertencia (campo `resumen`), como pide el recorrido. No se tocó `analisis.jsonl` |
| D-2 | El radio aceptar/ajustar/rechazar está fuera del `st.form`, en el mismo recuadro; prioridad final, motivo y Guardar sí están en el formulario | Dentro de un `st.form` los widgets no reaccionan hasta enviar, y el selector de prioridad final solo debe aparecer al elegir "ajustar". El usuario ve lo mismo: nada se guarda hasta "Guardar decisión" |
| D-3 | Las exclusiones no tienen formulario de decisión ("Las exclusiones no tienen prioridad propuesta que decidir") y no cuentan como pendientes en Cobertura | `Decision.prioridad_propuesta` es obligatoria en el contrato de U1 y una exclusión no tiene nivel propuesto |
| D-4 | Sin análisis: en `priorizacion` se muestra "Análisis IA pendiente" con `uv run hlf-copiloto --fecha-corte …`; en otros tipos, "Análisis IA pendiente: el copiloto analiza solo las solicitudes en priorización" sin comando | El copiloto solo analiza `priorizacion`; el comando no generaría nada para esas solicitudes |
| D-5 | Pestañas con `st.tabs(key="app-pestana", on_change="rerun")`: solo se calcula la pestaña abierta y elegir una fila (Bandeja o ¿Qué cambió?) cambia a Detalle | Evita reconstruir contextos de todas las vistas en cada interacción y permite "elegir una fila abre el Detalle". El clic en una fila no se pudo probar: `AppTest` no simula la selección de `st.dataframe` y no hubo navegador; las pruebas cambian de pestaña con `app-pestana` y eligen la solicitud con `detalle-solicitud` |
| D-6 | Además de la selección de fila, el Detalle tiene un selector `detalle-solicitud` | `AppTest` no puede hacer clic en filas de `st.dataframe`; también sirve para ir directo a una solicitud |
| D-7 | Sin script `hlf-bandeja`; se usa `uv run streamlit run app/bandeja.py` | El plan permitía cualquiera de las dos; `streamlit run` no necesita un punto de entrada extra |
| D-8 | La línea de tiempo resalta por defecto el primer ID de la primera bandera (EV-000004 en IC-HLF-00002 el 07-20); el selector `detalle-resaltar` lo cambia | Paso 3 del recorrido ("EV-000004 resaltado"). El resaltado va con fondo y con el texto "▶ elegido" (no solo color) |
