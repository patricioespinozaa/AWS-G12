# Preguntas de verificación de requisitos

Contexto: pediste "revisar el contexto y completar el contexto técnico". Ya revisé `docs/contexto.md`, `docs/datos.md`, `docs/enfoque.md` y `CLAUDE.md`, además del documento de Business Context que compartiste (que incluye la sección **12. Contexto técnico**).

Antes de redactar el contexto técnico completo, necesito confirmar el alcance y la profundidad. Responde cada pregunta escribiendo la letra elegida después de `[Answer]:`. Si ninguna opción encaja, usa la última opción (Other) y describe tu preferencia.

Avísame cuando termines ("listo"/"done") y procedo.

---

## Pregunta 1
¿Dónde debe quedar el contexto técnico completado?

A) Como un documento nuevo e independiente dentro de `docs/` (p. ej. `docs/contexto-tecnico.md`), dejando el documento de negocio como está

B) Integrado/expandido dentro del documento de contexto existente, reemplazando y ampliando la sección 12

C) Como artefacto de diseño de AI-DLC en `aidlc-docs/inception/application-design/` (y referenciado desde `docs/`)

D) En `docs/enfoque.md`, ampliándolo hasta volverlo el contexto técnico definitivo

X) Other (describe después de `[Answer]:`)

[Answer]: Elaborarse un documento .md junto con el archivo que contenía contexto general.

---

## Pregunta 2
¿Qué profundidad quieres para el contexto técnico? (La sección 12.9 ya lista los temas que el diseño debe detallar.)

A) Marco de referencia conceptual: principios, capas, contratos y comportamiento esperado, SIN fijar implementación ni stack (coherente con el espíritu actual de la sección 12)

B) Diseño técnico detallado: lo anterior MÁS decisiones concretas de stack, servicios AWS por capa, esquemas de datos, parámetros del motor de reglas y plan de despliegue

C) Intermedio: marco conceptual + recomendaciones concretas de servicios AWS y esquemas, dejando parámetros finos (pesos/umbrales) como "a calibrar"

X) Other (describe después de `[Answer]:`)

[Answer]: B

---

## Pregunta 3
El contexto habla de "servicios en la nube (AWS)" (12.9) pero sin fijar implementación. Para el nivel de detalle de servicios AWS, ¿qué prefieres?

A) Nombrar servicios AWS concretos por capa (p. ej. S3, Glue/Lambda, DynamoDB/Aurora, Bedrock, Step Functions, HealthLake para FHIR), como recomendación

B) Mantenerlo agnóstico: describir el tipo de servicio por capa (almacenamiento de objetos, orquestación batch, LLM gestionado, etc.) sin casarse con nombres de producto

C) Dos niveles: tipo de servicio + una opción AWS sugerida entre paréntesis

X) Other (describe después de `[Answer]:`)

[Answer]: A

---

## Pregunta 4
¿El contexto técnico debe cubrir explícitamente la **interoperabilidad FHIR R4 / CL Core** como parte central (recursos, perfiles, Provenance/RiskAssessment), o tratarla como anexo?

A) Parte central: desarrollar el mapeo FHIR y el versionado como una capa de primera clase

B) Anexo/apéndice: mencionarlo y dejar el detalle del mapeo para una fase posterior

C) Mínimo: solo nombrarlo como requisito, sin desarrollarlo

X) Other (describe después de `[Answer]:`)

[Answer]: A

---

## Pregunta 5
¿Debe el contexto técnico incorporar el **segundo eje (uso del recurso box)** con el mismo nivel que la priorización clínica?

A) Sí, ambos ejes al mismo nivel de detalle (priorización clínica + optimización/asignación de box)

B) Priorización clínica como foco principal; uso de box como componente secundario descrito a alto nivel

C) Solo priorización clínica en este contexto técnico; el box se documentará aparte

X) Other (describe después de `[Answer]:`)

[Answer]: B

---

## Pregunta 6
¿Qué idioma y formato final esperas para el documento?

A) Español, Markdown, con diagramas (Mermaid y/o ASCII) y tablas, consistente con el estilo de `docs/`

B) Español, Markdown, solo texto y tablas (sin diagramas)

C) Español con términos técnicos en inglés donde sea estándar (nombres de servicios, patrones)

X) Other (describe después de `[Answer]:`)

[Answer]: Español, Markdown, si diagramas fuesen comprendibles por LLM, entonces con diagramas.

---

## Pregunta: Extensiones de Seguridad
¿Se deben aplicar las reglas de la extensión de seguridad en este proyecto?

A) Sí — aplicar todas las reglas de SEGURIDAD como restricciones bloqueantes (recomendado para aplicaciones de nivel productivo). Nota: el dominio maneja datos clínicos (aunque anonimizados), lo que suele justificar esta opción.

B) No — omitir las reglas de SEGURIDAD (adecuado para PoCs, prototipos y proyectos experimentales como un hackatón)

X) Other (describe después de `[Answer]:`)

[Answer]: A

---

## Pregunta: Extensiones de Resiliencia
¿Se debe aplicar la línea base de resiliencia a este proyecto?

**Qué es.** Aplica un conjunto de buenas prácticas de diseño (orientadas por el AWS Well-Architected Framework, pilar de Fiabilidad) hacia tolerancia a fallos, alta disponibilidad, observabilidad y recuperación.

**Qué NO es.** No vuelve el sistema "listo para producción" ni certifica objetivos de disponibilidad/RTO/RPO. Es un punto de partida.

A) Sí — aplicar la línea base de resiliencia como guía de diseño (recomendado para cargas críticas, como punto de partida a validar)

B) No — omitir la línea base de resiliencia (adecuado para PoCs, prototipos y proyectos experimentales donde prima iterar rápido)

X) Other (describe después de `[Answer]:`)

[Answer]: A

---

## Pregunta: Extensión de Pruebas Basadas en Propiedades (PBT)
¿Se deben exigir reglas de pruebas basadas en propiedades para este proyecto?

A) Sí — exigir todas las reglas de PBT como restricciones bloqueantes (recomendado para proyectos con lógica de negocio, transformaciones de datos, serialización o componentes con estado; el motor de reglas y la "fecha de corte" encajan aquí)

B) Parcial — exigir PBT solo para funciones puras y round-trips de serialización (adecuado para complejidad algorítmica limitada)

C) No — omitir todas las reglas de PBT (adecuado para apps CRUD simples, solo-UI o capas finas de integración)

X) Other (describe después de `[Answer]:`)

[Answer]: A
