# Propuestas de solución

> Documento de trabajo del equipo. Parte de las notas del equipo y del desafío del HLF (ver `docs/contexto.md`).

## 0. El dolor, en una frase

> **La prioridad se asigna una vez y queda congelada, aunque la salud del paciente cambie y aunque la información que lo demuestra ya exista, dispersa en sistemas que no se hablan.**

Eso se traduce en tres dolores concretos:

| # | Dolor | Quién lo sufre | Evidencia |
|---|---|---|---|
| D1 | **El deterioro no se ve.** Urgencias, hospitalizaciones o cambios de tratamiento no mueven la prioridad. | Paciente (daño irreversible, como en el caso de don Manuel) | KPI estrella: hoy no hay detección sistemática |
| D2 | **La información está fragmentada.** Cada sistema guarda lo suyo y no hay una ficha que concentre diagnósticos, exámenes y fármacos. Los exámenes externos solo entran si el paciente consigue otra hora con un médico. | Equipo clínico, gestor de la lista y paciente | Notas del equipo; RCE en texto libre |
| D3 | **Se pierden horas de box.** Pacientes llegan sin los exámenes que requiere la consulta, o no llegan, y los controles indicados en texto libre no existen en la lista. | Hospital (horas de especialista desperdiciadas) | Brecha 2 de la ruta del paciente; inasistencias |

Toda propuesta debe atacar al menos uno de estos dolores y decir cómo se mide (`docs/kpis.md`).

---

## 1. Ajuste importante a la propuesta inicial

Las notas del equipo proponen:
1. consolidar la información,
2. organizarla por tipo,
3. generar un **primer diagnóstico actualizado**,
4. **proponer un diagnóstico**,
5. permitir que los pacientes envíen información.

**Sugerencia:** cambiar "diagnóstico" por **"resumen clínico consolidado"** y **"propuesta de prioridad"**.

Razones:
- **El desafío pide priorizar, no diagnosticar.** La pregunta del HLF es "¿quién empeora mientras espera?", no "¿qué tiene?".
- **Riesgo clínico y regulatorio.** Un sistema que propone diagnósticos es una herramienta de apoyo diagnóstico, con otra exigencia de validación. Uno que **ordena la lista y explica por qué** es mucho más fácil de adoptar.
- **El principio del HLF:** "La herramienta propone y explica; el equipo clínico decide".
- **Es más defendible ante el jurado:** "detectamos que don Manuel tuvo 2 urgencias por hiperglicemia y lo subimos, con esta evidencia" es más fuerte que "creemos que tiene retinopatía".

El sistema sí puede **marcar sospechas como señal de riesgo**, por ejemplo: "diabetes mal controlada + derivación por baja de visión → riesgo de retinopatía diabética". Eso no es un diagnóstico, sino un factor del puntaje con su evidencia.

---

## 2. Separar dos conceptos: prioridad clínica y disponibilidad

Una de las notas del equipo pregunta qué hacer si la consulta requiere exámenes que el paciente aún no tiene. Plantea priorizar a otra persona mientras tanto.

La clave es **no bajar la prioridad clínica** de ese paciente: sigue igual de enfermo. Lo que cambia es si está **listo para usar una hora de box**. Por eso cada solicitud debe tener dos ejes:

| Eje | Pregunta | Ejemplo de valores |
|---|---|---|
| **Prioridad clínica** | ¿Qué tan urgente es atenderlo según su salud? | Puntaje de 0 a 100 o niveles P1–P4 |
| **Disponibilidad** | ¿Puede aprovechar una hora de box **hoy**? | `lista` · `faltan_examenes` · `sin_contacto` · `no_confirma` |

**Cómo se arma la agenda:** se ordena por prioridad clínica, **filtrando** a quienes están `lista`. Quien tiene alta prioridad pero le faltan exámenes **no pierde su lugar**: se gatilla una acción para que los obtenga (orden de examen, recordatorio) y vuelve a estar disponible en cuanto los tenga.

Esto resuelve D1 y D3 a la vez: no se castiga al paciente grave y tampoco se desperdicia la hora de box.

---

## 3. Factores de priorización

Así quedarían los factores de las notas en el puntaje:

| Factor (notas del equipo) | Cómo se mide | Fuente | Peso sugerido |
|---|---|---|---|
| **Enfermedad detectada** | Gravedad del diagnóstico de derivación según una tabla validada por oftalmología. Por ejemplo, retinopatía diabética proliferativa o sospecha de glaucoma > catarata leve | CIE-10 de la SIC + texto de la derivación | Alto |
| **Antecedentes y situación personal** | Comorbilidades (diabetes, HTA, ERC), índice de Charlson o riesgo ACG, edad. También vulnerabilidad social, como vivir solo, ruralidad o tramo de FONASA, **solo si el HLF lo valida**, por temas de equidad | Comorbilidades, RCE, datos de la persona | Medio–alto |
| **Tasa de deterioro** | **Velocidad** de los eventos: urgencias u hospitalizaciones en los últimos 30, 90 y 180 días, comparadas con el período anterior; escalada de tratamiento (por ejemplo, de hipoglicemiante oral a insulina); tendencia de exámenes como HbA1c o creatinina si existen | Eventos, fármacos, exámenes | **Alto: es el núcleo del desafío** |
| **Posición en la cola** | Días de espera **en relación con un plazo clínico razonable** para ese diagnóstico, y no en valor absoluto. Sube de forma gradual para que nadie quede eternamente al fondo | Lista de espera | Medio, como factor de envejecimiento |
| **Combinación histórica de síntomas** | Patrones en la línea de tiempo, por ejemplo "hiperglicemia + hospitalización + baja de visión". Se detectan con reglas clínicas y un LLM que resume la historia **citando la fuente** | RCE, eventos | Medio, como bonificación por patrón |
| **Información aportada por el paciente** (exámenes privados, síntomas nuevos) | Entra como **evidencia pendiente de validar**: se muestra al clínico, y solo cuenta en el puntaje cuando la valida, o lo hace con menor peso | Canal del paciente (propuesta C) | Bajo hasta que se valida |

**Señales de alarma (reglas duras, fuera del puntaje):** pérdida súbita de visión, dolor ocular intenso, visión de "cortina" o destellos. Generan **una alerta inmediata** al equipo clínico, sin importar la posición en la lista.

---

## 4. Las propuestas

Son tres piezas que se pueden construir por separado y que se potencian juntas.

### Propuesta A: Ficha consolidada + motor de priorización dinámica (núcleo)

**Ataca:** D1 y D2 · **KPIs:** tiempo a reevaluación < 72 h, concordancia κ, cobertura

**Qué hace:**
1. **Consolidación nocturna.** Las notas dicen que no se puede cambiar que cada sistema guarde la información por separado. Entonces **no se toca el origen**: cada noche un proceso lee las fuentes (lista de espera, RCE, urgencias, farmacia, egresos) y arma una **ficha consolidada por paciente** en una base aparte, de solo lectura.
   - Con una corrida diaria, un evento se procesa en **menos de 24 h**, lo que cumple holgadamente el KPI de 72 h.
   - Si más adelante se puede, sumar disparadores en tiempo real para urgencias y hospitalizaciones.
2. **Organización por tipo.** Cada dato se clasifica como `diagnóstico`, `examen`, `fármaco`, `atención` (urgencia, hospitalización, consulta), `procedimiento` o `indicación de control`. El texto libre pasa por extracción (NER en español o un LLM con cita del fragmento).
3. **Resumen clínico consolidado.** Una línea de tiempo por paciente, más un resumen de 3 a 5 líneas generado por LLM y anclado a la evidencia. Por ejemplo: *"68 años, DM2 desde 2015. 2 urgencias por hiperglicemia (ago y sep 2026), 1 hospitalización (sep 2026). Inició insulina en sep 2026. En espera de oftalmología por baja de visión hace 140 días."*
4. **Propuesta de prioridad explicada.** Calcula el puntaje de la sección 3 y lo compara con la prioridad vigente. Si sube o baja de nivel, genera una **propuesta** con sus factores y fuentes.
5. **Bandeja de validación clínica.** El médico o gestor ve los cambios del día, ordenados por magnitud, y **acepta, ajusta o rechaza**. Cada decisión queda registrada, lo que además sirve para calibrar los pesos.

**Extra que ataca D3 (controles invisibles):** extraer del texto libre indicaciones como "control en 3 meses" y compararlas con la lista de controles. Si la indicación existe pero el control no está en la lista, se genera una alerta. Esto mide directamente el KPI de controles visibles ≥ 90 %.

**Viable en el hackatón:** sí, con los datos anonimizados del HLF.

---

### Propuesta B: Gestión del box por disponibilidad

**Ataca:** D3 · **KPIs:** uso del box (métrica adicional sugerida), inasistencias

**Qué hace:**
1. Para cada consulta, define **qué se necesita** para que la hora se aproveche: exámenes previos (por ejemplo, campo visual, OCT o HbA1c reciente), confirmación de asistencia y datos de contacto válidos.
2. Calcula la **disponibilidad** de cada paciente (sección 2).
3. **Propone la agenda:** para cada hora libre de box, el paciente de mayor prioridad clínica **que esté listo**, con una lista de reemplazo por si cancela.
4. Para los de alta prioridad que no están listos, genera **acciones**: pedir el examen, recordarle al paciente o hacer un llamado de rescate.
5. Usa el historial de inasistencias para **predecir el riesgo de no asistir** y confirmar antes, nunca para bajar la prioridad clínica.

**Viable en el hackatón:** parcialmente. Se puede simular con datos sintéticos de agenda si el HLF no entrega oferta de horas.

---

### Propuesta C: Canal del paciente (segunda iteración)

**Ataca:** D2 (el paciente tiene información que el hospital no ve) y D3 (confirmación) · **KPIs:** % de pacientes contactables, tiempo a reevaluación

Las notas plantean que hoy, para actualizar su ficha, el paciente tiene que **agendar una consulta solo para llevar exámenes** tomados en otro lugar. Eso gasta una hora de especialista en algo administrativo.

**Qué hace:** un canal liviano, como WhatsApp, SMS o un enlace web seguro, donde el paciente:
1. **Confirma** asistencia y si ya tiene los exámenes requeridos (alimenta la propuesta B).
2. **Sube exámenes externos** (PDF o foto) de clínicas o laboratorios privados. Esto resuelve el caso de quien se hizo exámenes en el sector privado para tener un diagnóstico más rápido y ahora necesita que el hospital actualice su prioridad para la cirugía.
   - El sistema extrae los valores (OCR + LLM) y los deja como **evidencia pendiente de validar**.
   - Un profesional (puede ser TENS o enfermería con un protocolo, no necesariamente el especialista) valida el documento.
   - Una vez validado, entra a la ficha consolidada y **gatilla una reevaluación** de la prioridad.
3. **Responde un cuestionario breve de síntomas** cada cierto tiempo, con preguntas cerradas y orientadas a señales de alarma. Por ejemplo: "¿Ha notado que ve peor que hace un mes?", "¿Ha tenido pérdida súbita de visión en un ojo?". Una respuesta de alarma crea una alerta clínica, no un cambio automático.

**Cuidados:**
- Verificar la identidad antes de aceptar documentos.
- Manejar el consentimiento e informar el uso de los datos (Ley 20.584 de derechos y deberes del paciente, y normativa de datos personales).
- Nunca prometer una fecha: "su información fue recibida y será revisada por el equipo".
- Considerar la brecha digital (personas mayores): ofrecer alternativa telefónica o presencial en el CESFAM.

**Viable en el hackatón:** como **maqueta** (simular el chat y la carga de un PDF de ejemplo). Integrar WhatsApp de verdad requiere aprobaciones que no caben en 3 días.

---

## 5. Recomendación para el hackatón (14 al 16 de octubre)

| Prioridad | Qué construir | Por qué |
|---|---|---|
| **1. Imprescindible** | Propuesta A completa con los datos del HLF: consolidación, línea de tiempo, puntaje, explicación y bandeja de validación | Es exactamente lo que pide el desafío y lo que miden los KPIs |
| **2. Diferenciador** | Extracción de controles en texto libre (dentro de A) | Ataca una brecha que el HLF nombró explícitamente y tiene su propio KPI (≥ 90 %) |
| **3. Visión** | Disponibilidad y agenda (B) + maqueta del canal del paciente (C) | Conecta con el nombre del desafío, "gestión inteligente del recurso box", y muestra la segunda iteración |

### Guion de la demo (3 a 5 minutos)
1. **El problema:** la lista de espera ordenada como está hoy. Don Manuel aparece abajo, como "no urgente".
2. **Corre la consolidación nocturna:** aparecen sus 2 urgencias y su hospitalización. La prioridad propuesta sube y la explicación muestra cada factor con su fuente.
3. **El clínico valida** el cambio con un clic, y queda el registro de la decisión.
4. **Controles visibles:** "Encontramos N indicaciones de control en texto libre que no estaban en la lista".
5. **Agenda del día:** una paciente con prioridad alta pero sin exámenes no ocupa el box; se llama a la siguiente que está lista, y a ella se le gatilla la orden de examen.
6. **Visión:** el paciente sube por WhatsApp un examen hecho en una clínica privada, y eso gatilla la reevaluación.
7. **KPIs:** tiempo a reevaluación, kappa con una muestra experta (si está disponible), controles visibles y cobertura.

---

## 6. Arquitectura sugerida en AWS (por definir con el equipo)

> El hackatón es de AWS; esto es una sugerencia, no una decisión.

```
Fuentes HLF (CSV/Excel anonimizados)
   │  S3 (raw)
   ▼
Proceso nocturno ── AWS Glue o Lambda + EventBridge (cron diario)
   │  normaliza CIE-10, une por ID, clasifica por tipo
   ▼
Ficha consolidada ── S3 (procesado) / RDS o DynamoDB
   │
   ├─► Extracción de texto ── Amazon Bedrock (LLM con salida JSON + cita)
   │                          y/o Comprehend Medical (solo inglés: no sirve para notas en español)
   ├─► Motor de puntaje ───── Python (reglas + pesos configurables)
   ▼
API (Lambda / API Gateway) ──► Interfaz web: bandeja de validación, línea de tiempo, agenda, KPIs
                           ◄── Canal del paciente (maqueta)
```

---

## 7. Riesgos y cómo mitigarlos

| Riesgo | Mitigación |
|---|---|
| El LLM inventa hallazgos | Exigir cita literal y verificar que exista en la fuente; no usar el LLM para el puntaje final, solo para extraer y resumir |
| Sesgo: subir siempre a quien más consulta (más acceso, no más enfermedad) | Revisar la equidad por comuna, edad, sexo y previsión; ponderar la relevancia del evento para el diagnóstico en espera, no solo su cantidad |
| Quien paga exámenes privados se "salta" la fila | La evidencia externa no sube la prioridad por sí sola: solo cuenta lo que el clínico valida, y se evalúa con el mismo criterio que la evidencia interna |
| El equipo clínico no confía en el sistema | Explicación factor por factor; el sistema **propone** y nunca cambia la lista solo; medir kappa con expertos |
| Datos incompletos (sin exámenes, sin fármacos) | Indicar el nivel de confianza en cada propuesta; con poca información, marcar "revisar manualmente" |

---

## 8. Preguntas para el referente del HLF

- [ ] ¿Existe hoy una ficha que concentre diagnósticos, exámenes y fármacos, o cada sistema está por separado? ¿Cuáles vienen en la base del hackatón?
- [ ] ¿Qué exámenes previos exige oftalmología según el tipo de consulta?
- [ ] ¿Cómo se contacta hoy a los pacientes (teléfono, SMS, WhatsApp)? ¿Hay datos de contacto en la base?
- [ ] ¿Cómo se gestionan hoy los exámenes traídos desde el sector privado?
- [ ] ¿Hay disponible una muestra con priorización experta para medir kappa?
- [ ] ¿Pueden compartir la oferta de horas de box de oftalmología (aunque sea agregada)?
- [ ] Dotación de camas: las notas del equipo dicen **403** y la presentación dice **397 (2023)**. Confirmar el dato y el año antes de usarlo en el pitch.
