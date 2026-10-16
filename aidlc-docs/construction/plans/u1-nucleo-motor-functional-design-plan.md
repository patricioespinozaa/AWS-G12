# Plan de Functional Design — U1 Núcleo de datos y motor de reglas

Base: secciones 4–7 de `docs/contexto-tecnico.md` y la definición de U1 en `aidlc-docs/inception/application-design/unit-of-work.md`. La mayoría de las reglas ya están fijadas en el diseño; aquí solo pregunto lo que el diseño deja abierto o lo que los datos contradicen.

## Hechos verificados en el dataset

- En `perfiles.json`, `lista_espera` es **un objeto** por paciente, no una lista como en el ejemplo de la sección 4.1 del contexto técnico. El contrato v1.0.0 aceptará el objeto (una solicitud por paciente) y lo normalizará a lista internamente, para permitir varias solicitudes en el futuro.
- Las mediciones no traen ID (confirmado); se usa el ID determinista de la sección 4.4.
- Los **76 pacientes `atendido`** tienen al menos una cita `asistio` en su especialidad. PAC-HLF-00032 tiene una sola: 2026-06-30, que es la fecha que cita `docs/casos-ejemplo.md`. Pero también hay **76 citas `asistio` de pacientes que siguen `en_espera`** (`docs/datos.md`), así que asistir no implica egreso.

## Supuestos que tomo sin preguntar (corrígelos si no te sirven)

- Fecha de extracción del dataset = **2026-10-13** (la "hoy" del README). Es la fecha de corte por defecto.
- Las señales de alarma de especialidad por texto (6.6) no aplican: el dataset no trae texto clínico (`detalle` es plantilla). Queda N/A en el MVP.
- Parámetros iniciales = los valores referenciales de las secciones 6 y 7 del contexto técnico, en `reglas-v0.1.0.yaml`.

## Checklist

- [x] Responder las preguntas
- [x] Generar `aidlc-docs/construction/u1-nucleo-motor/functional-design/domain-entities.md`
- [x] Generar `aidlc-docs/construction/u1-nucleo-motor/functional-design/business-rules.md`
- [x] Generar `aidlc-docs/construction/u1-nucleo-motor/functional-design/business-logic-model.md`
- [x] Incluir sección "Propiedades testeables" (PBT-01)
- [x] Validar contra los 6 casos de `docs/casos-ejemplo.md`

---

## Preguntas

Responde con la letra después de `[Answer]:` y avisa con "listo".

### Pregunta F-1 — Pacientes `atendido` con fecha de corte pasada

En la fecha de extracción, un `atendido` se excluye. Para un corte anterior no sabemos cuándo egresó, porque no hay fecha de egreso.

A) **Inferir la fecha de egreso** como la última cita `asistio` en su especialidad, solo para quienes están `atendido` en la extracción. Antes de esa fecha se evalúan; desde esa fecha, `exclusion`. Se marca como `inferido` en la explicación.

B) **Mantener la regla del diseño:** en cortes pasados, `estado = desconocido_a_la_fecha` y no se excluye a nadie por atención (solo por defunción).

C) Excluir a los `atendido` en todos los cortes.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. Reproduce lo que dice `casos-ejemplo.md` para PAC-HLF-00032 y es honesto porque queda marcado como inferido. No afecta a los 76 `en_espera` con citas `asistio`, porque solo se aplica a quien ya figura como `atendido`. C usaría información futura en cortes pasados, que es justo lo que el diseño prohíbe.

### Pregunta F-2 — Cómo limitar una bajada de prioridad

El diseño dice "baja como máximo un nivel por ciclo". En el MVP cada fecha de corte se evalúa por separado, sin memoria del ciclo anterior.

A) **Sin memoria:** el nivel propuesto nunca queda más de un nivel por debajo de `prioridad_inicial` (alta → media como mínimo; media → baja). Igual para cualquier corte.

B) **Con memoria:** comparar con la propuesta del corte anterior guardada en `salidas/`; bajar como máximo un nivel respecto de ella.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. Mantiene `evaluar()` como función pura (misma entrada, misma salida), que es la base de las pruebas de idempotencia y de fecha de corte. B hace que el resultado dependa del orden en que se corrieron los cortes.

### Pregunta F-3 — Duración de la bandera roja por evento grave

La bandera "urgencia u hospitalización grave en los últimos 30 días" fuerza `crítica`. Al día 31 la bandera desaparece y el nivel vuelve al calculado (por ejemplo, `alta`).

A) **Expira a los 30 días**, como dice el diseño. Si el médico no la revisó a tiempo, la alerta "crítica sin revisar > 24 h" ya habrá avisado.

B) Se mantiene hasta que un médico la revise. Requiere memoria de decisiones (como F-2 B).

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A** para el MVP, por la misma razón que F-2 A. El aporte del evento al puntaje sigue presente con su decaimiento, así que el paciente no vuelve a la cola baja.

### Pregunta F-4 — Cohortes en el MVP

A) Calcularlas en memoria con pandas (clave CIE-10 + edad + origen, IC95 Wilson, seguimiento de 90 días), según la sección 5.3.

B) Dejarlas fuera del MVP; el copiloto declara "riesgo poblacional no disponible" en `datos_faltantes`.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A** si U1 avanza bien, porque le da al copiloto cifras deterministas que citar. Con 500 pacientes y 17 diagnósticos, muchas cohortes van a tener n < 10; el diseño ya prevé la relajación y la advertencia.

### Pregunta F-5 — Si un caso de ejemplo falla con los parámetros referenciales

A) **Ajustar los parámetros** (nueva versión `reglas-v0.1.x`, con el cambio y el motivo en la bitácora) hasta que pasen los 6 casos.

B) **Ajustar el criterio del caso**, si el resultado del motor es defendible clínicamente, y documentar por qué.

C) Decidir caso por caso, preguntando al equipo.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A** por defecto, documentando cada ajuste. Los parámetros son referenciales y los 6 casos son la mejor referencia que tenemos sin validación clínica. Si un ajuste rompe otro caso, se escala (C).
