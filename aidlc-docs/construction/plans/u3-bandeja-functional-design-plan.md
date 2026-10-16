# Plan de Functional Design — U3 Bandeja y vistas (Streamlit)

Base: secciones 10.3 y 10.4 de `docs/contexto-tecnico.md`, la definición de U3 en `aidlc-docs/inception/application-design/unit-of-work.md` y los contratos que ya existen:
- `leer_propuestas()` (U1)
- `leer_analisis()`, `leer_fallidos()`, `leer_hallazgos_dq()` y `leer_cohortes()` (U2)
- el modelo `Decision` de `modelos.py`, que ya valida: ajustar exige una prioridad distinta y un motivo, y rechazar exige un motivo.

## Hechos verificados

- Hay propuestas del motor para los cortes 2026-07-19, 07-20, 07-21, 08-10 y 10-13.
- Hay análisis del copiloto **solo** para el 19, 20 y 21 de julio (95 en total). Uno de ellos lleva la marca `revision_equidad` (IC-HLF-00349).
- Streamlit todavía no está instalado. Se agrega con versión exacta.

## Checklist

- [x] Responder las preguntas
- [x] Generar `aidlc-docs/construction/u3-bandeja/functional-design/domain-entities.md`
- [x] Generar `aidlc-docs/construction/u3-bandeja/functional-design/business-rules.md`
- [x] Generar `aidlc-docs/construction/u3-bandeja/functional-design/business-logic-model.md` (incluye propiedades testeables)
- [x] Generar `aidlc-docs/construction/u3-bandeja/functional-design/frontend-components.md` (vistas, estado, interacciones, validación de formularios)

---

## Preguntas

Responde con la letra después de `[Answer]:` y avisa con "listo".

### Pregunta H-1 — ¿Qué vistas entran?

A) Las cuatro de la definición de U3:
   1. Bandeja por especialidad, ordenada por magnitud del cambio, con las críticas primero.
   2. Detalle con línea de tiempo citada, factores, banderas, análisis IA y nota de pre-consulta.
   3. Selector de fecha de corte.
   4. Panel de cobertura y alertas de gestión.

B) Las cuatro de A + una vista **"¿Qué cambió?"** que compara dos fechas de corte. Para cada solicitud que cambió de nivel muestra nivel antes → después y los registros nuevos. Aprovecha el modo rango que pediste en U2.

C) Solo bandeja y detalle, para terminar más rápido.

X) Other (describe después de `[Answer]:`)

[Answer]: B

> Recomendación: **B**. La vista de comparación es la que mejor cuenta la historia de la demo ("PAC-HLF-00002 pasó de baja a crítica entre el 19 y el 20 de julio por EV-000004") y casi todo lo que necesita ya está calculado.

### Pregunta H-2 — ¿La interfaz puede ejecutar el lote o el copiloto?

A) **Solo lectura de resultados:** la interfaz muestra lo que dejaron `hlf-lote` y `hlf-copiloto`, y solo escribe decisiones. Si un corte no tiene propuestas o análisis, lo dice y muestra el comando exacto para generarlos.

B) Botones para correr `hlf-lote` y `hlf-copiloto` desde la interfaz.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. Un botón que llama a Bedrock desde la pantalla puede gastar cientos de llamadas con un clic, en una cuenta compartida. Además mezcla el rol del médico con el del operador del lote. Es coherente con el diseño: el lote corre de noche y la bandeja se usa de día.

### Pregunta H-3 — Análisis del copiloto para la demo

Hoy solo hay análisis del 19 al 21 de julio. Para el corte más reciente (2026-10-13) no hay ninguno.

A) Mostrar en la demo los cortes de julio (con análisis). En el de octubre, la bandeja muestra "análisis IA pendiente" junto a la propuesta del motor.

B) Precalcular también el 2026-10-13 con Sonnet 5 antes de la demo: ~125 análisis, ~20–25 minutos, ~1,5–2 millones de tokens. Con `--max-llamadas` como tope.

C) Precalcular el 2026-10-13 con Haiku 4.5: más rápido (~5 s por análisis) y más barato, con análisis menos elaborados.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A** para construir U3 sin gastar nada ahora. B o C se pueden correr después, al preparar la demo, sin cambiar el código. Te lo vuelvo a preguntar en ese momento.

### Pregunta H-4 — Quién decide en la bandeja

A) Campo de texto "médico" al iniciar la sesión, sin autenticación. Solo para la demo local, y declarado así en la presentación (ya definido en U3).

B) Lista fija de 2 o 3 nombres ficticios de médicos para elegir.

X) Other (describe después de `[Answer]:`)

[Answer]: B

> Recomendación: **B**. Evita errores de tipeo en la demo, el registro de decisiones queda limpio y sigue sin haber datos reales de personas. En los dos casos, la autenticación real (Cognito) queda para la versión desplegada.
