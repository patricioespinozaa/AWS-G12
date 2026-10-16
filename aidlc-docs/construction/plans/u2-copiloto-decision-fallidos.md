# Decisión — Análisis fallidos en la verificación real (U2, generación en pausa)

## Resultado de las llamadas reales

| Prueba | Resultado |
|---|---|
| `pytest -m bedrock` (IC-HLF-00002 al 2026-08-10) | **Pasa.** Prioridad sugerida `crítica`; cita EV-000004, EV-000005 y las presiones sistólicas; riesgo poblacional igual a la cohorte de U1 (n = 13, k = 0). 6.834 tokens de entrada y 3.426 de salida, 33 s |
| Rango 2026-07-19 a 2026-07-21 | **74 analizadas, 21 fallidas** de 95. 148 llamadas reales contando los reintentos de validación. **1.035.363 tokens de entrada y 539.429 de salida, 22 minutos.** Sin limitación de Bedrock |
| Criterio de aceptación de IC-HLF-00002 en el rango | **Se cumple:** el 19 se omite (`sin_alerta`), el 20 se analiza como `crítica` con la evaluación del 19, el 21 se omite (`sin_cambio_en_rango`) |

Esto costó bastante más que mi estimación de 6–7 minutos: Sonnet 5 sin temperatura escribe análisis largos (~5.700 tokens de salida por análisis) y los reintentos de validación suman llamadas.

## Por qué fallaron 21

| Causa | Cantidad | Estado |
|---|---|---|
| El validador marcó como "motivo prohibido" textos que decían que las inasistencias **no** bajan la prioridad | 2 | Error del validador; ya corregido, con pruebas |
| Falta la nota de pre-consulta o la salida venía malformada | 5 | Fallas reales del modelo |
| Un hallazgo marcado `documentado` sin ningún ID, en los dos intentos | 14 | Requiere decisión (D-1) |

---

## Pregunta D-1 — Hallazgo `documentado` sin IDs

A) **Tratarlo como un ID inválido (regla C6.2):** el hallazgo pasa a `inferido` y se registra la corrección. El análisis se guarda. Es coherente con lo que ya hace C6.2 cuando todos los IDs de un hallazgo son inválidos

B) **Seguir rechazándolo:** esos análisis quedan como fallidos

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. No se pierde trazabilidad: el hallazgo queda marcado como inferido, que es exactamente la regla del diseño para afirmaciones sin respaldo en los registros.

## Pregunta D-2 — ¿Reintentar los fallidos ahora?

Por diseño (C5.1), una segunda ejecución salta lo ya guardado y **reintenta los fallidos**. Por eso la re-ejecución no da 0 llamadas.

A) **Reintentar ahora:** hasta ~42 llamadas (~0,3 millones de tokens, ~8 minutos). Una tercera ejecución, sin costo, confirmaría 0 llamadas nuevas

B) **No reintentar ahora:** dejar los 21 como fallidos. La idempotencia se confirma con una re-ejecución acotada a lo ya guardado y con las pruebas automáticas. Los fallidos se reintentan al preparar la demo

C) **Ajustar el prompt primero** (pedir que todo hallazgo `documentado` traiga IDs y que la nota de pre-consulta sea obligatoria; nueva versión `copiloto-v1.1.0`) y reintentar después. Los análisis ya guardados con `v1.0.0` quedan

X) Other (describe después de `[Answer]:`)

[Answer]: C

> Recomendación: **B** ahora, y **C** al preparar la demo. La verificación ya demostró lo que tenía que demostrar; gastar más tokens hoy no cambia el código. Con A en D-1, el problema principal (14 de 21) desaparece igual.
