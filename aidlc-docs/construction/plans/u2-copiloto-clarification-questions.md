# Aclaraciones — U2 Copiloto

Tus respuestas G-4 = A y G-5 = A quedan tal cual. Tres respuestas agregan condiciones que cambian el diseño, y necesito confirmar cómo las entendí antes de seguir.

---

## Aclaración 1 — Registro de cada cambio (G-1)

Respondiste: "A, sin embargo, notar que deja registro de cada cambio para la trazabilidad."

Lo entendí así: el copiloto analiza solo las `priorizacion`, pero **todas** las solicitudes del corte quedan registradas en la auditoría. Las analizadas, con su análisis. Las omitidas (`exclusion`, `gestion`, `sin_alerta`), con un evento `analisis_omitido` y el motivo. Así nadie puede preguntar "¿por qué este paciente no tiene análisis?" sin encontrar la respuesta.

A) Sí, es eso

B) No: me refería a otra cosa (descríbela después de `[Answer]:`)

[Answer]: A

---

## Aclaración 2 — Segunda fecha para revisar un período (G-2)

Respondiste: "A, y podrá aceptar otro parámetro alternativo (otra posible fecha) para crear una revisión en un periodo…". Veo dos lecturas distintas:

A) **Comparar dos cortes:** `hlf-copiloto --fecha-corte 2026-10-13 --fecha-anterior 2026-07-19`. El copiloto analiza solo las solicitudes cuyo nivel **cambió entre esas dos fechas** y recibe ambas evaluaciones, para explicar qué pasó en ese período ("subió de baja a alta por la urgencia del 20 de julio y la hospitalización del 6 de agosto"). Requiere que `hlf-lote` ya haya corrido en las dos fechas.

B) **Recorrer un rango:** `hlf-copiloto --desde 2026-07-19 --hasta 2026-07-25`. Corre el copiloto en cada corte del rango, uno por uno, como si fueran varias noches seguidas. Multiplica las llamadas a Bedrock (por ejemplo, 7 días × ~90 = ~630).

X) Other (describe después de `[Answer]:`)

[Answer]: B

> Recomendación: **A**. Responde mejor a "¿quién empeoró mientras esperaba?", gasta pocas llamadas y se luce en la demo.

En ambos casos aplico la validación que pediste: formato ISO `AAAA-MM-DD`; la fecha anterior (o `--desde`) tiene que ser **estrictamente anterior** a la otra; ninguna puede ser posterior a la extracción (2026-10-13); y tienen que existir las propuestas del lote para esas fechas. Si algo falla, el comando termina con un mensaje claro sin llamar a Bedrock.

---

## Aclaración 3 — "Los mismos resultados" (G-3)

Respondiste: "Si es que podrá lograr los mismos resultados, entonces B."

Hay que separar dos cosas:

- **Paralelo frente a secuencial no cambia los resultados.** Cada solicitud se analiza en una llamada independiente que no comparte nada con las otras, así que el orden no importa. El motor, las cifras y las citas son deterministas, y el copiloto las recibe ya calculadas.
- **Lo que sí puede variar es el texto del modelo** (el resumen, la justificación, la nota de pre-consulta). Pasa aunque las llamadas sean secuenciales: un LLM no garantiza la misma redacción dos veces, ni siquiera con temperatura 0.

Cómo se controla: temperatura 0; las cifras del análisis se validan contra las del motor y la cohorte (si no coinciden, se reemplazan); y cada análisis se guarda la primera vez y **no se recalcula** si ya existe para la misma solicitud, corte, versión de prompt y modelo. Así la demo muestra siempre lo mismo.

A) Con eso me basta: B (paralelo)

B) Necesito que el texto también sea idéntico entre ejecuciones (describe para qué después de `[Answer]:`)

X) Other (describe después de `[Answer]:`)

[Answer]: A
