# Presupuesto de invocaciones, motivos de falla, exit 4 y negación por cláusula en C6.5 (U2, tercera pasada)

Tercera revisión de las cinco correcciones aprobadas para U2, tras aplicar los hallazgos de la segunda pasada. `--max-llamadas` es ahora un presupuesto compartido de invocaciones reales (`ClienteConPresupuesto`, con candado), `max_tokens` 8192 está ratificado y documentado, `contexto_no_disponible` se separa de `huella_distinta`, un modelo fuera de la lista local sale con 4 y C6.5 limita la negación a su cláusula, exige un verbo de uso cuando lo negado es el atributo y ya no trata "solo/solamente/únicamente" como puente. Los cinco hallazgos de la segunda pasada están resueltos. Las cuatro herramientas salen limpias y no se llamó a Bedrock.

Watch for: C6.5 sigue abierto (fail-open) en las construcciones contrastivas y de excepción. Si la bajada está negada y el atributo prohibido aparece después de "sino" o "salvo", la frase se acepta aunque afirme el atributo como motivo: "No se debe bajar por la clínica, sino por su comuna." y "No corresponde bajarla, salvo por su previsión." pasan la validación (confirmed). Además, "baja" y "bajamos" no son verbos de bajada para el patrón (confirmed, probablemente anterior a estos cambios).

**Verdict**: NEEDS_CHANGES

## High-level view

El presupuesto es correcto y seguro entre hilos. `ClienteConPresupuesto.converse` comprueba y descuenta bajo el mismo candado antes de invocar. Como envuelve al cliente que recibe `con_reintentos`, cada reintento de servicio y de validación consume una unidad. Las invocaciones en curso terminan y ninguna nueva empieza al agotarse. P15 lo comprueba con cualquier concurrencia y la prueba con `threading.Barrier` lo comprueba con tres llamadas abiertas a la vez. Solo se aborta antes de llamar si las solicitudes pendientes superan el presupuesto. Lo que no cabe queda `analisis_omitido(limite_llamadas)` con exit 1, y la re-ejecución completa el resto.

`max_tokens` 8192 (C4.2 con el motivo 33/173, desviación 6 ratificada), `contexto_no_disponible` (con prueba) y exit 4 para un modelo fuera de la lista (con prueba, ayuda de la CLI, README y C4.4) cumplen sus criterios. El resto de los errores de configuración sigue en exit 2.

En C6.5, la regla nueva cierra las dos aperturas de la pasada anterior y los casos del brief. Queda una tercera: una bajada negada exime toda la oración, aunque una cláusula posterior con "sino" o "salvo" retome esa bajada con un atributo prohibido como motivo. Es la misma clase de fallo que los dos hallazgos bloqueantes anteriores, en una construcción que un modelo puede escribir.

<details>
<summary>Issues (2)</summary>

1. **C6.5 abierto con "sino" / "salvo" tras una bajada negada** (bloqueante, confirmed): "No se debe bajar por la clínica, sino por su comuna.", "No hay que bajarla por la clínica sino por su comuna.", "No corresponde bajarla, salvo por su previsión." y "Conviene no bajarla salvo por su comuna." se aceptan. Cuando la oración tiene una bajada y un atributo afirmado después de un marcador contrastivo o de excepción (sino, salvo, excepto, menos, "más que"), rechazar aunque la bajada esté negada. Agregar esas frases a la prueba de ejemplo y a `frase_con_motivo_prohibido` (P16), y volver a correr la revisión de solo lectura sobre los 95 análisis.
2. **Formas de "bajar" sin detectar** (no bloqueante, confirmed; probablemente anterior a estos cambios): `_RE_BAJAR` no reconoce "baja", "bajan", "bajó", "bajamos" ni "bajando", así que "Se baja la prioridad por su comuna." y "Bajamos la prioridad por su previsión." se aceptan. Ampliar el patrón a la conjugación de "bajar" y agregar dos frases de ejemplo.

</details>

<details>
<summary>Details</summary>

### Herramientas (ejecutadas por el revisor desde la raíz, tras `. .\scripts\entorno-demo.ps1`)

| Comando | Resultado |
|---|---|
| `uv run ruff check` | All checks passed (exit 0) |
| `uv run mypy src` | Success: no issues found in 39 source files (exit 0) |
| `uv run pytest` | 194 passed, 1 deselected (`bedrock`) en 46,1 s (exit 0); coincide con `resumen.md` |
| `uv run pip-audit` | No known vulnerabilities found (exit 0); solo se salta el paquete local |

No se ejecutó ningún comando contra Bedrock real. Las pruebas de C6.5 de abajo llaman localmente a `_usa_atributo_para_bajar` con frases literales.

### C6.5: una bajada negada exime las cláusulas posteriores con "sino" / "salvo"

`_usa_atributo_para_bajar` rechaza solo si `bajada_afirmada and atributo_afirmado`. En "No se debe bajar por la clínica, sino por su comuna" el único verbo de bajada es "bajar". Entre "No" y "bajar" solo hay puentes ("se debe"), así que el verbo cuenta como negado. "sino" abre otra cláusula donde el atributo queda afirmado, pero ninguna bajada está afirmada, y la frase se acepta. En español, "no X por A, sino por B" niega el motivo A y mantiene X con el motivo B: la frase afirma la comuna como motivo para bajar. "salvo" y "excepto" tienen la misma estructura elíptica ("no corresponde bajarla, salvo por su previsión"). "excepto" solo se rechazó porque "recomienda" no es puente.

```
ACEPTA  No hay que bajarla por la clínica sino por su comuna.
ACEPTA  No se debe bajar por la clínica, sino por su comuna.
ACEPTA  No hay que bajarla por motivos clínicos: es por su comuna.
ACEPTA  Conviene no bajarla salvo por su comuna.
ACEPTA  No corresponde bajarla, salvo por su previsión.
ACEPTA  No hay que bajarla solo por la clínica sino también por la comuna.
RECHAZA No se recomienda bajarla excepto por su comuna.
RECHAZA No hay que bajarla por la comuna, hay que bajarla por la previsión.
```

Exigir que el atributo esté en la misma cláusula que la bajada negada lo arreglaría, pero rompería el caso aceptado "Paciente sin previsión; no corresponde postergar.". Una regla más acotada, también fail-closed, conserva ese caso: si la oración tiene algún verbo de bajada y un atributo afirmado después de un marcador contrastivo o de excepción (sino, salvo, excepto, menos, "más que"), se rechaza aunque la bajada esté negada. El caso con dos puntos ("…: es por su comuna") tiene la misma forma sin marcador. Se puede cubrir rechazando un atributo afirmado en una cláusula posterior a una bajada negada, siempre que los dos falsos positivos reales sigan aceptados. P16 no genera ninguna de estas formas. La desviación 7 de `resumen.md` dice que "no por la comuna sino por …" se rechaza. Esa es la construcción inversa, donde el atributo es el motivo negado, y no cubre esta.

### Regla de bajada: conjugaciones faltantes

`_RE_BAJAR` reconoce `bajar\w*` y `baje[ns]?`, pero no "baja", "bajan", "bajó", "bajamos" ni "bajando". "Se baja la prioridad por su comuna" y "Bajamos la prioridad por su previsión" se aceptan sin que intervenga ninguna negación. `src/` no tiene historial en git (el árbol está sin seguimiento), así que no se puede confirmar si el patrón cambió en esta pasada. La revisión original no lo marcó, y probablemente es anterior. Como afecta la misma regla de equidad, queda como acción no bloqueante.

### `--max-llamadas` como presupuesto vivo y seguro entre hilos

```
analizar ── con_reintentos ── ClienteConPresupuesto.converse ── ClienteModelo.converse
                                   │ candado: invocaciones >= maximo → LimiteLlamadas
                                   │          si no, invocaciones += 1
```

Si el presupuesto se agota en el reintento de validación, la E/S y el evento `llamada_modelo` del primer intento se guardan igual. La invocación real queda auditada y la solicitud termina como `omitida`, sin crear un fallido ni alimentar el corte de circuito. `ResultadoTarea.estado` lanza si un resultado tiene más de un desenlace. P15 afirma `len(falso.llamadas) == invocaciones <= B`, un solo estado por solicitud y que solo queda alguna sin procesar cuando el presupuesto se usó entero. Los ejemplos cubren estos casos:

- aborto con B = 1 y 2 pendientes: sin llamadas, dos eventos `limite_llamadas`, exit 2;
- peor caso sobre el presupuesto sin abortar: B = 2, exit 0;
- agotamiento a mitad con un reintento de servicio: B = 3, un `limite_llamadas`, ningún fallido, exit 1;
- re-ejecución que completa el resto: exit 0.

Con concurrencia > 1, qué solicitudes reciben las últimas unidades depende del orden de los hilos. Es una excepción documentada en C2.5/C4.3 y en la desviación 10. La escritura sigue en orden `(fecha_corte, id_solicitud)`.

### Logs y alcance

Los logs nuevos llevan solo IDs, conteos y códigos. La ruta de modelo no permitido registra solo `codigo`, y `_CAMPOS_LOG_LLAMADA` excluye el texto del modelo. Los archivos de U1 (`lote.py`, motor, `auditoria/registro.py`, `logs.py`) tienen fechas de modificación anteriores a esta pasada. No hay dependencias nuevas. `audit.md` tiene una entrada nueva con fecha `2026-10-16T01:59:32Z`.

</details>

<details>
<summary>Archivos</summary>

- `src/hlf_priorizacion/copiloto/barrido.py`: `ClienteConPresupuesto`, `LimiteLlamadas`, `ResultadoTarea.estado`, persistencia de `limite_llamadas`, `contexto_no_disponible`, comentario de `cargar_repositorio`
- `src/hlf_priorizacion/copiloto/seleccion.py`: `verificar_tope` solo con solicitudes pendientes, mensaje de `ErrorTope`
- `src/hlf_priorizacion/copiloto/config.py`: `MAX_TOKENS = 8192` con el motivo, `ErrorModeloNoPermitido`
- `src/hlf_priorizacion/copiloto/cli.py`: exit 4 para un modelo fuera de la lista, ayuda y líneas de resumen del presupuesto
- `src/hlf_priorizacion/copiloto/validacion.py`: negación por cláusula, puentes, verbo de uso obligatorio
- `tests/ejemplos/test_copiloto.py`: presupuesto, Barrier, `contexto_no_disponible`, exit 4, tabla de frases de C6.5
- `tests/propiedades/test_prop_copiloto.py`, `tests/estrategias/copiloto.py`: P15, P16, P16b y generadores
- `business-rules.md`, `resumen.md`, `README.md`, `audit.md`: documentación

Diff completo: `src/` y `tests/` no tienen historial en git (sin seguimiento). Revisado contra los archivos actuales y los `review.json` / `review-fixes.json` anteriores.

</details>
