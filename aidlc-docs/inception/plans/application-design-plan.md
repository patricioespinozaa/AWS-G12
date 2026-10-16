# Plan de Application Design — Contexto técnico (`docs/contexto-tecnico.md`)

Esta etapa produce el entregable solicitado: un contexto técnico detallado. Como no se genera código, adapto los artefactos de diseño a **secciones del documento** y a las decisiones que realmente moldean su contenido.

## Checklist de ejecución

- [x] Confirmar decisiones de diseño (preguntas de abajo)
- [x] Redactar `docs/contexto-tecnico.md` con estas secciones:
  - [x] 1. Propósito, alcance y relación con el contexto de negocio
  - [x] 2. Principios rectores y restricciones transversales (incl. equidad, "la IA no decide")
  - [x] 3. Arquitectura lógica (capas y componentes) — equivale a `components.md`
  - [x] 4. Arquitectura física en AWS (servicios concretos por capa, una región multi-AZ)
  - [x] 5. Contrato de datos, validación y cuarentena
  - [x] 6. Repositorio de datos: fecha de corte, línea de tiempo, cohortes, capacidad de box
  - [x] 7. Motor de reglas determinista (secuencia, niveles, parámetros versionados) — equivale a `component-methods.md`
  - [x] 8. Calidad de datos (niveles, categorías, límites de plausibilidad)
  - [x] 9. Copiloto IA (modos reactivo/barrido, herramientas, salida estructurada, anti-inyección)
  - [x] 10. Trazabilidad e interoperabilidad: auditoría inmutable + FHIR R4 / CL Core (capa de primera clase)
  - [x] 11. Uso del recurso box (alto nivel)
  - [x] 12. Orquestación y flujos (lote nocturno, bandeja) — equivale a `services.md`
  - [x] 13. Dependencias y flujo de datos entre capas — equivale a `component-dependency.md`
  - [x] 14. Seguridad (mapeo SECURITY-01..15 aplicables)
  - [x] 15. Resiliencia (mapeo RESILIENCY-01..15 aplicables; DR, observabilidad, runbooks)
  - [x] 16. Estrategia de pruebas (PBT + ejemplos; PBT-01..10)
  - [x] 17. CI/CD, gestión de cambios, rollback y despliegue
  - [x] 18. Temas abiertos y cobertura de la sección 12.9 del Business Context
  - [x] Diagramas Mermaid validados donde aporten
- [x] Resumen de cumplimiento de extensiones (Security/Resiliency/PBT)
- [x] Validación de contenido (Mermaid parseable, estructura correcta)

---

## Preguntas de diseño

Responde con la letra después de `[Answer]:`. Cada pregunta trae mi recomendación. Avísame con "listo".

### Pregunta D1 — Lenguaje/runtime objetivo que asumirá el documento
Para nombrar framework de PBT, estructura de proyecto y runtime de los servicios AWS, necesito fijar un lenguaje objetivo (es una suposición de diseño, no implica construir ahora).

A) **Python** (Lambda/Glue/Fargate; PBT con Hypothesis). Encaja con datos, Bedrock y procesamiento batch.

B) **TypeScript/Node.js** (Lambda/Fargate; PBT con fast-check).

C) **Ambos**: Python para datos/motor de reglas/IA, TypeScript para API/frontend.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A (Python)** como lenguaje principal del backend de datos y reglas; es el más natural para este dominio y para Bedrock/Glue.

### Pregunta D2 — Cómputo del lote nocturno
¿Qué servicio de cómputo asumo como principal para la consolidación nocturna y el motor de reglas?

A) **AWS Step Functions** orquestando **AWS Lambda** (y **AWS Glue** para ETL de los CSV/perfiles). Serverless, multi-AZ por defecto, costo por uso.

B) **AWS Batch** / **ECS Fargate** para trabajos de mayor duración.

C) **Amazon EMR Serverless** (si el volumen creciera mucho).

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. 500 pacientes hoy; serverless con Step Functions + Lambda + Glue cubre de sobra y escala. Menciono B/C como alternativa si crece el volumen.

### Pregunta D3 — Almacén del repositorio de datos consolidado
¿Qué almacén asumo para el contexto a fecha de corte, línea de tiempo y cohortes?

A) **Amazon S3** (data lake, Parquet particionado por fecha) + **Amazon Athena** para consultas analíticas/cohortes, y **Amazon DynamoDB** para las tablas de salida (`propuesta_prioridad`, `decision_clinica`).

B) **Amazon Aurora PostgreSQL** (relacional) para todo (perfiles consolidados, salidas y auditoría).

C) Híbrido: **S3 + Athena** para análisis y **Aurora PostgreSQL** para salidas transaccionales y bandeja.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **C**. S3/Athena para el "repositorio a fecha de corte" y cohortes (naturalmente temporal e inmutable), Aurora PostgreSQL para propuestas/decisiones/bandeja (transaccional, con integridad referencial).

### Pregunta D4 — LLM del copiloto
¿Qué servicio asumo para el copiloto IA?

A) **Amazon Bedrock** (modelos gestionados, sin salida de datos del entorno AWS; soporta salida estructurada y herramientas).

B) Dejarlo abstracto ("LLM gestionado") sin fijar proveedor.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A (Amazon Bedrock)**, coherente con P3 (servicios AWS concretos) y con la privacidad (los datos no salen del entorno).

### Pregunta D5 — Capa FHIR
Elegiste FHIR como capa de primera clase. ¿Cómo la materializo en AWS?

A) **AWS HealthLake** (almacén FHIR R4 gestionado) como repositorio interoperable del perfil y el `RiskAssessment`/`Provenance`.

B) Servicio FHIR propio (p. ej. librería HAPI FHIR sobre Fargate) si se necesita control total de perfiles CL Core.

C) Describir ambas opciones y recomendar una.

X) Other (describe después de `[Answer]:`)

[Answer]: C

> Recomendación: **C**, recomendando **HealthLake** como opción primaria y HAPI FHIR como alternativa si CL Core exige perfiles no soportados.

### Pregunta D6 — Interfaz / bandeja del clínico
¿Asumo una pila concreta para las vistas (clínico, gestor de lista, box) y la bandeja de validación?

A) **Frontend**: React; **API**: Amazon API Gateway + Lambda; **Auth**: Amazon Cognico. Descrito a nivel de arquitectura.

B) Mantener la interfaz a alto nivel, sin fijar framework de frontend.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**, a nivel de arquitectura (sin maquetar), para poder aplicar las reglas de Seguridad (headers, CORS, authz) de forma concreta.

### Pregunta D7 — Profundidad de los diagramas Mermaid
¿Cuántos diagramas quieres?

A) Varios: arquitectura lógica, arquitectura física AWS, flujo del lote nocturno, secuencia del copiloto reactivo y mapeo FHIR.

B) Solo los esenciales (arquitectura física AWS + flujo del lote).

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**, siempre que cada diagrama aporte y sea parseable por un LLM (texto Mermaid), como pediste.
