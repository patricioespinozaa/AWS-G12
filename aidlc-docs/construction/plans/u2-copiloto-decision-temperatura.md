# Decisión — Modelo por defecto y temperatura (U2, generación en pausa)

La generación de U2 está terminada y probada sin conexión (155 pruebas pasan, incluidas las 107 de U1). Se detuvo antes de las llamadas reales a Bedrock por dos hallazgos.

## Hallazgo 1 — Sonnet 5 no acepta temperatura

Bedrock rechaza `us.anthropic.claude-sonnet-5` si se le envía `temperature` (ValidationException: "temperature is deprecated for this model"). La regla C4.2 dice temperatura 0. Sin ese parámetro, Sonnet 5 funciona (~16 s por llamada). Haiku 4.5 sí acepta temperatura 0 (~5 s).

## Hallazgo 2 — La verificación real cuesta más llamadas de lo que te dije

El rango 2026-07-19 a 2026-07-21 necesita **95 llamadas** (85 + 5 + 5), no "pocas". El primer día de cualquier rango analiza todas las `priorizacion` de ese día, porque no hay día anterior con el cual comparar. Los días siguientes sí se reducen (5 cada uno). Por eso, cualquier rango cuesta al menos lo que cuesta un corte completo.

---

## Pregunta T-1 — Modelo por defecto

A) **Sonnet 5 por defecto, sin enviarle temperatura.** Haiku 4.5 y Nova Pro siguen con temperatura 0. Cada análisis registra si se envió temperatura. La redacción puede variar entre ejecuciones, como ya aceptaste en la Aclaración 3; las cifras y las citas se validan y un análisis guardado no se recalcula.

B) **Haiku 4.5 por defecto, con temperatura 0.** Más rápido (~5 s) y más barato; análisis algo menos elaborados. Sonnet 5 queda disponible con `HLF_BEDROCK_MODEL_ID`, sin temperatura.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. La temperatura no garantizaba texto idéntico de todos modos; lo que da la estabilidad es la validación y no recalcular. Sonnet 5 da mejores análisis para la demo. Las 95 llamadas a ~16 s con 4 en paralelo son unos 6–7 minutos.

## Pregunta T-2 — Verificación real

A) **Correr el rango completo** (95 llamadas). Además deja precalculados los análisis del 19 al 21 de julio para la demo

B) **Verificación mínima:** solo la prueba marcada de IC-HLF-00002 (1 llamada) y el rango ejecutado con el cliente falso. Las llamadas reales grandes se hacen al preparar la demo

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. Es la única forma de probar con Bedrock real la concurrencia, los reintentos ante limitación y la idempotencia, y esos análisis se reutilizan en la demo.
