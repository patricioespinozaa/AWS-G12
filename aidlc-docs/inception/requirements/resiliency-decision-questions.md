# Preguntas de decisión — Extensión de Resiliencia (y operación)

Habilitaste la extensión de **Resiliencia** y pediste **diseño técnico detallado (P2:B)** con **servicios AWS concretos (P3:A)**. Las reglas de resiliencia (RESILIENCY-02, 03, 04, 08, 14, 15) exigen que **tú** definas ciertas decisiones de arquitectura y operación; no debo elegirlas por ti. Tus respuestas determinan los servicios AWS y la estrategia que escribiré en el contexto técnico.

Responde con la letra después de `[Answer]:`. Si dudas, al final de cada pregunta añadí mi **recomendación** para este sistema (lote nocturno, datos clínicos anonimizados, prototipo con vocación productiva). Avísame con "listo" al terminar.

---

## Pregunta R1 — Objetivos RTO/RPO y estrategia de recuperación ante desastres
¿Qué objetivos de tiempo (RTO) y de pérdida de datos (RPO) necesita el sistema? Esto define la estrategia de DR y la redundancia.

A) RPO/RTO: horas — **Backup & Restore**. Costo más bajo. Datos respaldados, servicios se redepliegan desde IaC. Adecuado para cargas no críticas.

B) RPO/RTO: decenas de minutos — **Pilot Light**. Datos vivos, servicios inactivos listos para escalar.

C) RPO/RTO: minutos — **Warm Standby**. Datos vivos, servicios a capacidad reducida.

D) RPO/RTO: casi en tiempo real — **Multi-site Active/Active**. Costo más alto, cero downtime.

E) N/A — una sola región con multi-AZ es suficiente; sin DR entre regiones.

X) Other (describe después de `[Answer]:`)

[Answer]: B

> Recomendación: **A** o **E**. El sistema es un **lote nocturno** (no tiempo real) con ventana de 72 h; tolera recuperación en horas. Backup & Restore + multi-AZ basta y es coherente con el bajo acoplamiento temporal.

---

## Pregunta R2 — Topología regional
¿El sistema requiere despliegue multi-región o basta una región con multi-AZ?

A) Una región, multi-AZ — tolera caída de zona, no de región completa. Menor costo.

B) Multi-región activo-pasivo — sobrevive a caída de región con failover. Mayor costo.

C) Multi-región activo-activo — sobrevive a caída de región sin downtime. Costo más alto.

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. Consistente con R1=A/E y con un proceso nocturno.

---

## Pregunta R3 — Proceso de gestión de cambios
¿Cómo se gobiernan los cambios a producción de esta carga?

A) Usar un proceso organizacional existente — indícalo (p. ej. ServiceNow, Jira Change). AI-DLC se alineará a él.

B) No existe proceso formal — que AI-DLC proponga uno ligero (registro de cambio + aprobación + nota de rollback).

C) N/A — exenta de gestión formal de cambios (documentar motivo).

X) Other (describe después de `[Answer]:`)

[Answer]: B

> Recomendación: **B** (proponer uno ligero), apropiado para un prototipo que aspira a producción.

---

## Pregunta R4 — Herramientas de CI/CD
¿Qué tooling de CI/CD debe usar la carga?

A) Usar un pipeline existente — indícalo (p. ej. GitHub Actions, GitLab CI, Jenkins, AWS CodePipeline).

B) No existe — que AI-DLC proponga una definición de CI/CD acorde al IaC y runtime elegidos.

X) Other (describe después de `[Answer]:`)

[Answer]: B
> Recomendación: **B**, con **GitHub Actions** o **AWS CodePipeline** (el repo ya usa git). Lo detallaré en el documento.

---

## Pregunta R5 — Mecanismo de rollback
¿Cómo se revierte un despliegue fallido a producción?

A) Redesplegar la versión previa de IaC/artefacto (rollback por versión fijada)

B) Blue/green: volver al entorno anterior

C) Canary con auto-rollback por métricas de salud

D) Rollback consciente de base de datos (reversión de migración de esquema/datos)

E) Usar el procedimiento de rollback existente de la organización — indícalo

X) Other (describe después de `[Answer]:`)

[Answer]: A y D

> Recomendación: **A** para los servicios de cómputo y **D** marcado como atención especial para los almacenes con esquema (tablas `propuesta_prioridad`, `decision_clinica`, auditoría inmutable).

---

## Pregunta R6 — Estilo de despliegue
¿Qué estrategia de despliegue es aceptable para el perfil de riesgo de esta carga?

A) Directo / in-place (menor costo, mayor radio de impacto) — para cargas no críticas

B) Rolling (reemplazo gradual de instancias)

C) Blue/green (corte sin downtime, mayor costo)

D) Canary (desplazamiento progresivo de tráfico con auto-rollback)

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A** o **B**. Al ser batch nocturno, el radio de impacto de un despliegue directo es acotado.

---

## Pregunta R7 — Proceso de respuesta a incidentes
¿Cómo se manejan los incidentes de producción de esta carga?

A) Usar el proceso de respuesta a incidentes existente — indícalo (p. ej. PagerDuty, proceso interno de on-call).

B) No existe proceso formal — que AI-DLC proponga uno ligero de respuesta a incidentes y corrección de errores (COE).

X) Other (describe después de `[Answer]:`)

[Answer]: 
B
> Recomendación: **B** (proponer uno ligero).

---

## Pregunta R8 — Enfoque de pruebas de resiliencia
¿Cómo se validarán los mecanismos de resiliencia (failover, recuperación)?

A) Usar una práctica existente de DR testing / game day / chaos engineering — indícala.

B) No existe — que AI-DLC proponga un calendario de pruebas de DR y experimentos de caos.

C) Diferir a la fase de Operaciones — capturar escenarios ahora, ejecutar en Operaciones.

X) Other (describe después de `[Answer]:`)

[Answer]: B

> Recomendación: **C**. Capturamos los escenarios ahora (restore desde backup, re-ejecución del lote) y se ejecutan en Operaciones.
