# Persistencia incremental y Ctrl+C ordenado en el barrido del copiloto (defecto 13)

El barrido del copiloto esperaba a todas las solicitudes con `pool.map` y escribía todo al final, así que un Ctrl+C tras ~15 min sobre el corte 2026-10-13 perdió todos los análisis y no dejó registro de las llamadas a Bedrock. Con el cambio, `ejecutar_tareas` recoge cada futuro apenas termina (`wait(FIRST_COMPLETED)` en tramos de 0,5 s) y se lo entrega a `_Persistidor.guardar` en el hilo principal, bajo un solo candado y con SIGINT aplazado durante la escritura. Ctrl+C marca `detener`/`interrupcion`, cancela lo no empezado, espera hasta 70 s a lo que está en curso, registra el resto como `analisis_omitido(interrumpido)` y el CLI sale con 130. El presupuesto, el corte de circuito, los prompts, la validación y U1/U3 no cambian; la única API compartida que se tocó (`agregar_jsonl`) recibe un parámetro opcional y sin él se comporta igual.

Watch for: hay una ventana corta (likely) en la que un Ctrl+C pierde una solicitud ya terminada, porque se saca de `sin_recoger` antes de escribirla. Además, un Ctrl+C que llega fuera de la espera protegida sale con 130 pero sin `os._exit`, y puede quedarse esperando a los hilos que siguen en curso (possible). Ninguna de las dos corrompe los archivos y la re-ejecución las recupera.

**Verdict**: APPROVED

## High-level view

Toda la persistencia vive ahora en `_Persistidor`. Por cada solicitud escribe, en este orden: E/S del modelo, eventos `llamada_modelo`, análisis o fallido, omisión (`limite_llamadas` / `interrumpido`) y `analisis_ia` / `error_proceso`. Todo pasa en el hilo principal y bajo un `threading.Lock`, con un caché de claves por ruta para no releer el JSONL en cada escritura. Los fallidos por `huella_distinta` o `contexto_no_disponible` se escriben mientras se arman las tareas. El conjunto `_terminadas` asegura que cada solicitud tenga un solo estado por ejecución, aunque se intente guardar dos veces.

El Ctrl+C se atiende en dos lugares. Si llega durante la espera de las llamadas, `_interrumpir` corta, espera de forma acotada y guarda lo que vaya terminando; un segundo Ctrl+C corta esa espera. Las tareas que siguen en curso quedan como `interrumpida` + `abandonada`, y el CLI sale con `os._exit(130)` tras vaciar stdout/stderr. Si llega fuera de esa espera (al armar las tareas), `ejecutar_barrido` marca todas las pendientes como `interrumpido` y el CLI devuelve 130. Lo protegido de verdad es la espera de las llamadas. Los bordes alrededor tienen huecos chicos, descritos abajo.

El presupuesto (`ClienteConPresupuesto`) y el corte de circuito no se tocaron y no dependen del orden en que terminan las solicitudes. P13 (secuencial = paralelo como conjunto), P14 y P15 siguen verdes. P17 agrega lo que faltaba: cada línea de los tres JSONL se puede parsear, analizadas ∪ fallidas ∪ interrumpidas = plan sin solapes, y el resumen coincide con lo escrito.

Verificación independiente (Windows PowerShell, desde la raíz, tras `. .\scripts\entorno-demo.ps1`): `uv run ruff check` → All checks passed! (exit 0); `uv run mypy src` → Success: no issues found in 44 source files (exit 0); `uv run pytest` (marcadores por defecto) → 280 passed, 1 deselected en 77,0 s (exit 0); `uv run pip-audit` → No known vulnerabilities found (exit 0; solo se salta el paquete local). Coincide con `resumen.md`. No se llamó a Bedrock.

<details>
<summary>Issues (4)</summary>

1. **Solicitud terminada perdida entre `discard` y la escritura** (likely, no bloqueante) — en `ejecutar_tareas` y en `_interrumpir`, `sin_recoger.discard(f)` va antes de `recoger(r)`. Un Ctrl+C justo entre las dos deja esa solicitud sin análisis, sin `llamada_modelo` y sin `interrumpido`. Hay que descartar después de `recoger`; `_Persistidor.guardar` ya ignora la segunda escritura.
2. **Ctrl+C fuera de la espera protegida no corta los hilos** (possible, no bloqueante) — un `KeyboardInterrupt` durante el bucle de `pool.submit` o durante el bucle final de `_interrumpir` sube a `ejecutar_barrido` sin pasar `detener`/`shutdown(cancel_futures=True)`. El CLI devuelve 130 sin `os._exit`, el intérprete espera a los hilos y, en el caso de `submit`, las tareas ya enviadas siguen llamando al modelo y su resultado se descarta. Hay que poner `detener.set()` y `shutdown(wait=False, cancel_futures=True)` en ese `except` y llamar a `os._exit` si quedan hilos vivos.
3. **Reintentos de servicio tras Ctrl+C** (likely, no bloqueante) — `con_reintentos` no mira `detener`. Una solicitud en curso con limitación del servicio puede hacer hasta 3 invocaciones más, con espera exponencial, después del Ctrl+C. Eso consume presupuesto y alarga la espera, aunque nunca más allá de 70 s. Conviene pasarle `detener` o comprobarlo entre reintentos.
4. **Faltan pruebas del segundo Ctrl+C y de una señal real** — ninguna prueba ejercita el segundo Ctrl+C durante la espera, ni `_sigint_diferido` con un SIGINT real a mitad de una escritura. Falta agregar al menos una prueba del segundo Ctrl+C con `vigia` que lance dos veces, y la comprobación manual con el comando real que `resumen.md` deja pendiente.

</details>

<details>
<summary>Details</summary>

### Recolección incremental y el hueco antes de escribir

```
hilos: analizar() ──► Future ──┐
                               ▼
principal: wait(FIRST_COMPLETED, 0.5 s) ─► discard(f) ─► recoger(r) ─► _sigint_diferido ─► _Persistidor.guardar (Lock)
```

`analizar` no escribe nada: solo llama al modelo y valida. Todo lo escribe el hilo principal, así que el candado de `_Persistidor` es una garantía extra y los JSONL no pueden quedar con líneas mezcladas. `agregar_jsonl` hace un solo `write` por escritura y agrega la clave al caché solo después de escribir. La escritura en sí está protegida porque `_sigint_diferido` cambia el manejador de SIGINT y relanza el Ctrl+C al terminar. Lo que queda afuera es el tramo `discard(f)` → `resultados.append(r)` → entrar a `_sigint_diferido` (confirmed por la lectura del código; likely que ocurra solo de forma ocasional). Un Ctrl+C ahí sale del bucle con `f` fuera de `sin_recoger`, `_interrumpir` ya no lo ve y la solicitud termina la ejecución sin estado. No se escribe nada a medias. La re-ejecución vuelve a llamar por ella, porque no tiene análisis guardado, pero los tokens de esa llamada quedan sin `llamada_modelo`. El mismo orden se repite en el bucle de `_interrumpir`. Bastaría con descartar después de `recoger`: si el Ctrl+C llega tras escribir, el duplicado lo absorbe `_terminadas`.

### Ctrl+C acotado y los bordes sin cubrir

Dentro de la espera, una solicitud que alcanzó a hacer una llamada y luego queda interrumpida (su segundo intento de validación ve `detener` + `interrupcion`) guarda su E/S y su `llamada_modelo` junto con la omisión `interrumpido`. Así la llamada queda trazada y la solicitud tiene un solo estado final.

Fuera de esa espera hay dos caminos sin cubrir (possible). Si llega un `KeyboardInterrupt` mientras se envían los futuros (antes del `try`), o un tercer Ctrl+C en el bucle final de `_interrumpir`, el error sube a `ejecutar_barrido`. Ahí `interrumpir_restantes` marca las pendientes como `interrumpido`, pero nadie fija `detener` ni cancela el pool. El `except KeyboardInterrupt` del CLI devuelve 130 de forma normal, y la limpieza de `concurrent.futures` al salir espera a los hilos de trabajo. En el caso de `submit`, esos hilos completan todas las tareas enviadas, con llamadas reales cuyo resultado nunca se escribe. Las ventanas son de microsegundos y los archivos quedan consistentes, pero se contradice "un segundo Ctrl+C sale de inmediato" y pueden gastarse tokens sin traza. En ese camino tampoco se imprime el resumen parcial, solo el mensaje para volver a ejecutar; antes de las llamadas no hay nada calculado que mostrar.

`con_reintentos` sigue reintentando errores de servicio después del Ctrl+C, porque no recibe `detener` (likely). No rompe el tope de 70 s ni el presupuesto, pero una solicitud limitada puede gastar hasta 3 invocaciones más después de que el usuario pidió parar.

### Re-ejecución sin duplicados

`ya_analizadas` lee solo `analisis.jsonl`, así que las `interrumpido` y las `limite_llamadas` vuelven a quedar pendientes y las guardadas pasan a `ya_analizada`. La prueba de ejemplo con k = 1 y 3 lo cubre de punta a punta vía `cli.main`: la segunda ejecución llama solo por las interrumpidas y al final cada solicitud tiene exactamente un análisis. La prueba de caída con `BaseException` cubre el mismo comportamiento tras una falla. El registro de eventos acumula un `interrumpido` de la primera ejecución y un `analisis_ia` de la segunda para la misma solicitud. Es lo esperado (son dos ejecuciones), pero U3 o cualquier lector de auditoría tiene que tomar el último evento por ejecución.

### Cobertura de pruebas

Las 7 pruebas de ejemplo y P17 (25 ejemplos, concurrencia 1..8, punto de corte 1..N+1, mezcla de respuestas válidas, mal formadas, errores del modelo y errores inesperados) cubren la persistencia incremental, el Ctrl+C desde el hilo principal y desde un hilo de trabajo, la espera acotada con una llamada colgada (`_salir_ya` sustituido), el Ctrl+C antes de las llamadas y que cada línea JSONL se pueda parsear. El Ctrl+C se simula sin señales (`vigia`), lo que es determinista en Windows. Sin probar: el segundo Ctrl+C durante la espera, una señal real durante una escritura (el aplazamiento de `_sigint_diferido`), y el comando real con Bedrock, que `resumen.md` declara pendiente.

### Requisitos no funcionales y documentación

Los logs nuevos (`copiloto interrumpido`, `análisis fallido`, `llamada al modelo`) llevan solo IDs, conteos, códigos y tipos de error, nunca texto clínico ni del modelo (C7.2). `barrido.py` usa solo módulos estándar nuevos (`signal`, `contextlib`), sin dependencias nuevas. `MotivoOmision` agrega `interrumpido` y U3 no lee omisiones. `business-rules.md` tiene C1.2, C4.7, C4.8 (con 130) y C5.4. `resumen.md` tiene la desviación 13 y su verificación. README.md y CLAUDE.md tienen su línea, y `audit.md` se agregó al final (428 líneas, con las entradas anteriores intactas).

</details>

<details>
<summary>File map</summary>

- `src/hlf_priorizacion/copiloto/barrido.py`: `ejecutar_tareas` con `wait(FIRST_COMPLETED)` y `al_terminar`; `_interrumpir`, `_sigint_diferido`, `_Persistidor`; resumen a partir de los conteos persistidos.
- `src/hlf_priorizacion/copiloto/cli.py`: `SALIDA_INTERRUMPIDA = 130`, línea de interrumpidas, `os._exit` cuando quedan llamadas abandonadas.
- `src/hlf_priorizacion/copiloto/modelos.py`: motivo de omisión `interrumpido`.
- `src/hlf_priorizacion/copiloto/persistencia.py`, `src/hlf_priorizacion/persistencia/salidas.py`: `vistos_por_ruta` opcional.
- `tests/ejemplos/test_copiloto_interrupcion.py`: 7 pruebas nuevas.
- `tests/propiedades/test_prop_copiloto.py`: P17.
- `aidlc-docs/.../business-rules.md`, `code/resumen.md`, `README.md`, `CLAUDE.md`, `aidlc-docs/audit.md`: documentación.

El código de U2 no está en git (sin seguimiento); la revisión se hizo sobre los archivos actuales y la evidencia de `resumen.md`.

</details>
