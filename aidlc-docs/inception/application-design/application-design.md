# Application Design (consolidado)

El entregable de esta etapa es `docs/contexto-tecnico.md`. Para no duplicar contenido, los artefactos estándar de AI-DLC apuntan a sus secciones:

| Artefacto AI-DLC | Sección en `docs/contexto-tecnico.md` |
|---|---|
| components.md | 2 (arquitectura lógica) y 2.1 (componentes C1–C11 con criticidad) |
| component-methods.md | 2.2 (firmas) y 6 (motor de reglas) |
| services.md | 3 (servicios AWS por capa) y 10 (orquestación, degradación, bandeja, vistas) |
| component-dependency.md | Diagramas de las secciones 2, 3 y 10.1; 9.3 (relaciones FHIR) |

## Decisiones de diseño aplicadas (D1–D7)

| Ref | Decisión |
|---|---|
| D1 | Python 3.12 (PBT con Hypothesis) |
| D2 | Step Functions + Lambda + Glue |
| D3 | S3 (Parquet) + Athena + DynamoDB. Auditoría inmutable en S3 Object Lock. Excepción acotada: Aurora PostgreSQL solo si la capa FHIR usa HAPI |
| D4 | Amazon Bedrock (Converse, herramientas, salida forzada, Guardrails) |
| D5 | HealthLake preferente; HAPI FHIR en Fargate si la región o CL Core lo exigen |
| D6 | React + API Gateway + Lambda + Cognito |
| D7 | Diagramas Mermaid: lógica, física AWS, secuencia del motor, secuencia del copiloto reactivo, lote nocturno, relaciones FHIR |

## Verificaciones hechas

- HealthLake no está disponible en São Paulo; la región AWS Chile está anunciada para fines de 2026 (fuentes citadas en la sección 0 del documento). La región queda como tema abierto T1.
- El ejemplo numérico de la sección 6.8 se recalculó con las reglas 6.2–6.5.
- Los pesos de eventos (6.3) son los de `docs/enfoque.md` escalados ×2.
