# Plan de Functional Design — U2 Copiloto (modo barrido)

Base: sección 8 de `docs/contexto-tecnico.md` (8.2 barrido, 8.4 esquema `analisis-v1`, 8.5 validación, 8.6 seguridad) y la definición de U2 en `aidlc-docs/inception/application-design/unit-of-work.md`. El contrato `AnalisisIA` ya existe en `src/hlf_priorizacion/modelos.py` (U1).

## Hechos verificados

- Bedrock funciona en la cuenta del workshop (`us-east-1`) con `toolChoice` forzado: Claude Sonnet 5 (~2,2 s), Haiku 4.5 (~0,7 s), Nova Pro (~0,9 s). Sonnet 5.5 y otros modelos están bloqueados por la política del workshop.
- Volumen por corte con el dataset real: 86 `priorizacion` al 2026-07-20 y 125 al 2026-10-13; 39 y 91 `exclusion`.
- U1 ya guarda, por solicitud, la evaluación, el contexto citado (huella) y las cohortes de las `priorizacion`.

## Checklist

- [x] Responder las preguntas
- [x] Generar `aidlc-docs/construction/u2-copiloto/functional-design/domain-entities.md` (PaqueteBarrido, AnalisisIA, ResultadoValidacion, eventos de auditoría)
- [x] Generar `aidlc-docs/construction/u2-copiloto/functional-design/business-rules.md` (selección, armado del paquete, minimización, validación, reintentos, degradación)
- [x] Generar `aidlc-docs/construction/u2-copiloto/functional-design/business-logic-model.md` (flujo, prompt versionado, propiedades testeables PBT-01)

---

## Preguntas

Responde con la letra después de `[Answer]:` y avisa con "listo".

### Pregunta G-1 — ¿Sobre qué solicitudes corre el copiloto?

A) Solo `priorizacion` (cambios de nivel y banderas rojas): 86 a 125 llamadas por corte

B) `priorizacion` + `exclusion`, como dice el diseño (8.2): 125 a 216 llamadas

C) Solo las que quedan en `crítica` o `alta`

X) Other (describe después de `[Answer]:`)

[Answer]: A, sin embargo, notar que deja registro de cada cambio para la trazabilidad.

> Recomendación: **A**. Las exclusiones (fallecido, atendido) son administrativas y el motor ya las explica; un análisis narrativo aporta poco y cuesta llamadas. Es una desviación menor del diseño, que dejaría documentada.

### Pregunta G-2 — ¿Cómo se ejecuta?

A) Comando aparte: `hlf-copiloto --fecha-corte AAAA-MM-DD`, que lee las propuestas que ya dejó `hlf-lote`

B) Integrado en el lote: `hlf-lote --fecha-corte … --copiloto`

X) Other (describe después de `[Answer]:`)

[Answer]: A, y podrá aceptar otro parámetro alternativo (otra posible fecha) para crear una revisión en un periodo en caso de que entrega dicha fecha? (Incluya revisión estándar de fecha: formato, si es más reciente en comparación con la fecha anterior)

> Recomendación: **A**. El motor sigue funcionando sin red ni credenciales, se puede re-ejecutar el copiloto solo (por ejemplo, con otro modelo) y para la demo se precalculan los análisis. Idempotente por `(id_solicitud, fecha_corte, version_reglas, version_prompt, model_id)`.

### Pregunta G-3 — Llamadas en paralelo

A) Secuencial (una a la vez): ~5 min para 125 solicitudes con Sonnet 5

B) Paralelo con 4 llamadas simultáneas y reintento con espera exponencial ante limitación (`ThrottlingException`)

X) Other (describe después de `[Answer]:`)

[Answer]: Si es que podrá lograr los mismos resultados, entonces B.

> Recomendación: **B**. No conocemos la cuota de la cuenta del workshop; 4 es conservador y el reintento cubre la limitación. Configurable por variable de entorno.

### Pregunta G-4 — Bedrock Guardrails (filtro de ataques de prompt)

El diseño (8.6) usa Guardrails. Activarlo requiere **crear un recurso en la cuenta AWS del workshop**.

A) No crear Guardrails en el MVP: la defensa queda en el prompt (datos delimitados y marcados como datos), en que el modo barrido no tiene herramientas de consulta, y en la validación de salida. Se documenta como pendiente

B) Crear un guardrail con el filtro de ataques de prompt en `us-east-1` y usarlo en cada llamada

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. El dataset no tiene texto libre (`detalle` es plantilla), así que no hay por dónde inyectar instrucciones hoy; y crear recursos en una cuenta compartida del evento es un cambio que prefiero no hacer sin necesidad. Pasa a ser obligatorio cuando entre texto clínico real.

### Pregunta G-5 — ¿Qué parte del historial se envía al modelo?

A) Todo el contexto hasta la fecha de corte (eventos, mediciones, citas) con sus IDs. Con este dataset son pocos registros por paciente

B) Solo los registros que el motor citó en sus factores, banderas y alertas

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. El copiloto tiene que poder reconstruir la historia y encontrar cosas que el motor no usó (tarea 1 y 2 de la sección 12.6 del negocio). Siempre sin `comuna`, `prevision`, NSE ni nombre: `ContextoPaciente` ya no los tiene.
