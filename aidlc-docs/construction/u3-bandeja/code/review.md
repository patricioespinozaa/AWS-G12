# Bandeja local en Streamlit para el médico contralor (U3)

U3 agrega una app Streamlit de solo lectura sobre `salidas/`: bandeja ordenada, Detalle de cada solicitud con el análisis del copiloto, "¿Qué cambió?" entre dos cortes, Cobertura, y un formulario donde el médico registra su decisión. Lo único que escribe es una línea en `salidas/decisiones/decisiones.jsonl` más un evento `decision_medica`. La lógica está en `src/hlf_priorizacion/bandeja/` (`datos`, `filas`, `cambios`, `decisiones`), con funciones puras o con E/S inyectable. `app/bandeja.py` arma los widgets y llama a esas funciones. Las restricciones duras se cumplen y las verifiqué de nuevo en el árbol: no hay Bedrock, no hay HTML, las decisiones solo se agregan, la auditoría no lleva el motivo y `salidas/` real quedó intacta.

Watch for: si falla la escritura de la auditoría, la decisión ya quedó guardada pero la interfaz dice "No se pudo guardar" (confirmed). El radio de decisión parte en "Aceptar", así que basta un clic en Guardar para aceptar (confirmed). El clic en una fila de tabla para abrir el Detalle nunca se probó (confirmed, el coder lo declara).

**Verdict**: APPROVED

## High-level view

La bandeja lee lo que dejaron U1 y U2 y no corre nada. Si falta un corte, muestra `uv run hlf-lote --fecha-corte …`. Si falta un análisis, muestra "Análisis IA pendiente" y `uv run hlf-copiloto --fecha-corte …`. Un análisis fallido se muestra con su motivo. En el árbol no aparecen `boto3`, `bedrock`, `invoke_model`, `subprocess` ni `unsafe_allow_html`. Después de cargar la app con `AppTest`, `boto3`, `botocore` y `copiloto.cliente` no quedan en `sys.modules`.

El orden B2.2 es una clave de tupla pura (`clave_orden`), y "¿Qué cambió?" la reutiliza con el nivel del corte B. El contexto se reconstruye con `contexto_a_fecha` y se compara su huella con la de la evaluación. Si no coincide, se muestra una advertencia y no hay línea de tiempo. La advertencia de equidad usa el texto exacto de B3.5 y aparece antes del rótulo "Sugerencia del copiloto — no es una decisión". Hay una prueba que comprueba ese orden en la página.

Las decisiones pasan por `crear_decision`, que arma una `Decision` y deja que el modelo Pydantic valide. Los errores se muestran con `st.error` y no se guarda nada. Las decisiones se agregan con `agregar_jsonl` (modo `"a"`), con ULID y timestamp UTC. La vigente es la de mayor `(timestamp, id_decision)`. El evento `decision_medica` lleva solo IDs, la decisión y `prioridad_final`, y el log tampoco lleva el motivo. El punto débil es el orden de escritura: primero la decisión, después la auditoría, y un fallo en la segunda se presenta como un fallo de la primera.

La app escucha solo en 127.0.0.1, sin telemetría y en modo headless. Las claves de widgets siguen `{vista}-{elemento}`, y los colores de nivel, decisión y resaltado siempre van con texto o ícono.

<details>
<summary>Issues (5)</summary>

1. **Fallo de auditoría informado como fallo de guardado** — `guardar_decision` agrega primero la decisión y después registra la auditoría. Si la auditoría falla, la UI muestra "No se pudo guardar la decisión" aunque la decisión ya está en el archivo. Hay que distinguir el mensaje (guardada pero sin auditoría) o evitar que un reintento cree un duplicado. No bloqueante.
2. **Radio de decisión preseleccionado en "Aceptar"** — `st.radio` sin `index=None` deja "aceptar" elegido, y un solo clic en Guardar acepta la propuesta. Conviene usar `index=None` y exigir una elección explícita, en línea con "el sistema propone; el médico decide". No bloqueante.
3. **Reglas pequeñas en la capa de presentación** — `app/bandeja.py` compara `a >= b` por su cuenta en vez de llamar a `validar_cortes`, que no se usa en la app, y decide en la UI qué solicitudes muestran el comando del copiloto (D-4). Conviene moverlo a `bandeja/` para que `app/` solo presente. No bloqueante.
4. **Clic en fila → Detalle sin probar** — `AppTest` no simula la selección en `st.dataframe` y no hubo recorrido en navegador. El callback `_abrir`, incluido el cambio de corte desde "¿Qué cambió?", no tiene cobertura. Hay que probarlo a mano antes de la demo. No bloqueante.
5. **Mensajes de validación con nombres de campo** — los errores de `Decision` llegan como "ajustar exige prioridad_final". Al médico le serviría un texto como "elija la prioridad final". Cosmético.

</details>

<details>
<summary>Details</summary>

### Verificación ejecutada en esta revisión

Todo se corrió desde la raíz después de `. .\scripts\entorno-demo.ps1`:

- `uv run ruff check`: All checks passed.
- `uv run mypy src` (estricto): sin problemas en 44 archivos.
- `uv run pytest` con los marcadores por defecto: **271 passed, 1 deselected** en 72,3 s. Son las 230 anteriores más 41 nuevas: 11 de propiedades, 19 de ejemplo y 11 de interfaz. No corrí `-m bedrock`.
- `uv run pytest tests/interfaz` (AppTest): 11 passed.
- `uv run pip-audit`: No known vulnerabilities found. Solo se omite el paquete propio, que no está en PyPI.
- App: `python -m streamlit run app/bandeja.py --server.port 52149` con `HLF_SALIDAS` en una carpeta temporal. `GET /_stcore/health` dio 200 `ok` y `GET /` dio 200 (6467 bytes). Escuchaba solo en `127.0.0.1:52149`. Detuve el proceso y quedaron 0 sockets en escucha.

La salida real no cambió. `salidas/decisiones/decisiones.jsonl` sigue sin existir, igual que antes según el coder. `salidas/auditoria/eventos.jsonl` tiene 12529 líneas y SHA-256 `9605A208…E126F`, idénticos al valor de antes y de después que registró el coder, y 0 eventos `decision_medica`. Las pruebas de ejemplo y de interfaz apuntan `HLF_SALIDAS`/`HLF_DATOS` a `tmp_path`, y las que usan datos reales copian `salidas/` a una carpeta temporal antes de abrir la app. No hice llamadas a Bedrock ni corrí `hlf-copiloto`. El plan tiene todos los pasos en `- [x]`.

### Orden de escritura decisión → auditoría

```
guardar_decision
  agregar_jsonl(decisiones.jsonl)  ← ya persistida
  RegistroAuditoria.registrar(...) ← OSError → ErrorPersistencia
app/_formulario
  except Exception → "No se pudo guardar la decisión"
```

Confirmed. Si la segunda escritura falla, `decisiones.jsonl` ya tiene la línea, la auditoría no tiene su evento (no se cumple B5.5 para ese registro) y el médico ve un error que lo invita a reintentar. El reintento genera un `id_decision` nuevo y deja dos decisiones idénticas en el historial. Como todo es solo agregar, no se pierde ni se corrompe nada. Pero el mensaje es falso y la auditoría queda incompleta sin que nada lo indique. En disco local es raro, así que no bloquea. La salida más simple es un mensaje distinto, algo como "Decisión guardada; no se pudo registrar la auditoría", y registrar `id_decision` en el log de error para poder conciliar después.

### Formulario de decisión (D-2) y valor por defecto

El radio quedó fuera del `st.form` (D-2) para que el selector de prioridad final aparezca solo al elegir "ajustar". Ese radio no tiene `index=None`, así que parte en "aceptar" (confirmed). Para una herramienta cuyo mensaje es que el médico decide, un aceptar implícito de un clic empuja hacia la propuesta del sistema. Pedir una elección explícita cuesta una línea.

### Lógica en `app/bandeja.py`

La separación se cumple en lo importante: orden, filtros, comparación, vigencia y validación están en `bandeja/`. Quedan dos reglas chicas en la UI (confirmed). La validación A < B de "¿Qué cambió?" se reimplementa como comparación de cadenas ISO (`if a >= b`) y `validar_cortes` no se usa. La rama de D-4, que decide si mostrar el comando del copiloto según `tipo_resultado == "priorizacion"`, también vive en `_analisis`. Las dos son correctas hoy, pero quedan sin pruebas unitarias y pueden desalinearse de `bandeja/` si cambia la regla.

### Navegación por selección de fila (D-5)

"Elegir una fila abre el Detalle" depende del callback `_abrir`. Ese callback lee `selection.rows`, cambia `lateral-corte` cuando viene de "¿Qué cambió?", fija `detalle-solicitud` y cambia la pestaña con `app-pestana`. `AppTest` no simula la selección en `st.dataframe` y en esta sesión no hubo navegador, así que ese camino nunca se ejecutó en una prueba (confirmed por el resumen del coder y por las pruebas, que eligen la solicitud con `detalle-solicitud`). Si la API de `st.tabs(key=…, on_change="rerun")` o de la selección se comporta distinto en el navegador, la demo pierde el paso 2 → 3. Hay que probarlo a mano antes de presentar.

### Cobertura de pruebas

Las 11 propiedades, el recorrido real de la demo, cada error del formulario y la auditoría sin motivo tienen pruebas. Not tested: la selección de fila en las tablas, el camino de fallo de la auditoría después de guardar la decisión y la lectura de un `decisiones.jsonl` corrupto desde la UI (que debería terminar en el mensaje genérico de `_seguro`).

</details>

<details>
<summary>File map</summary>

- `src/hlf_priorizacion/bandeja/datos.py` — rutas por entorno, cortes disponibles, `cargar_corte`, comandos B1, marcas de equidad (con la regla de U2 aplicada al leer), reconstrucción con huella, cobertura B6.
- `src/hlf_priorizacion/bandeja/filas.py` — `FilaBandeja`, `clave_orden`/`ordenar` (B2.2), `Filtros`, contador.
- `src/hlf_priorizacion/bandeja/cambios.py` — `comparar` (cambios, ingresos, a exclusión, registros en (A, B]), `validar_cortes`.
- `src/hlf_priorizacion/bandeja/decisiones.py` — `crear_decision`, `guardar_decision` (solo agregar más auditoría), vigentes, historial.
- `app/bandeja.py` — UI Streamlit con cuatro pestañas, caché y formulario.
- `app/config_demo.py` — tres médicos ficticios fijos.
- `app/.streamlit/config.toml` — 127.0.0.1, headless, sin telemetría.
- `tests/estrategias/bandeja.py`, `tests/propiedades/test_prop_bandeja.py`, `tests/ejemplos/test_bandeja.py`, `tests/interfaz/test_app_bandeja.py` — generadores, propiedades, ejemplos y AppTest.
- `pyproject.toml`, `uv.lock` — `streamlit==1.66.0`.
- `README.md`, `CLAUDE.md`, `aidlc-docs/audit.md`, `aidlc-docs/construction/u3-bandeja/code/resumen.md` — documentación.

El árbol no está versionado (todo sin seguimiento en git), así que no hay un `git diff`. Revisé los archivos completos.

</details>
