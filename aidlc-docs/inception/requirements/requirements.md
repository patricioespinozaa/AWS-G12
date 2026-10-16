# Requisitos — Completar el contexto técnico (Priorización clínica dinámica · HLF)

## Análisis de intención

| Dimensión | Valor |
|---|---|
| **Petición del usuario** | "Usando AI-DLC, revisar el contexto y que me complete el contexto técnico." |
| **Tipo de petición** | Enhancement documental / New Project (artefacto de diseño): revisar el contexto de negocio existente y producir un **contexto técnico completo** que sirva de insumo al diseño técnico detallado. |
| **Alcance estimado** | System-wide (describe todo el sistema), pero acotado a **documentación/diseño**: no se genera código de aplicación en esta etapa. |
| **Complejidad** | Complex: dominio clínico, principio de "la IA no decide", trazabilidad, FHIR, motor de reglas determinista, copiloto IA, dos ejes (clínico + box). |
| **Profundidad de requisitos** | Comprehensive. |

## Entregable objetivo

Un documento Markdown en español, **nuevo e independiente**, ubicado **junto al contexto general** (en `docs/`), que **complete el contexto técnico** del sistema a nivel de **diseño técnico detallado**, nombrando **servicios AWS concretos** por capa, con **FHIR R4 / CL Core como capa de primera clase**, y la priorización clínica como foco (uso de box a alto nivel). Diagramas en Mermaid (texto, comprensible por LLM) cuando aporten.

- **Ruta propuesta del entregable**: `docs/contexto-tecnico.md`
- **Fuente de verdad del negocio** (no se modifica): el documento de Business Context (secciones 1–13) y `docs/contexto.md`, `docs/datos.md`, `docs/enfoque.md`, `docs/kpis.md`, `CLAUDE.md`.

## Decisiones de alcance (respuestas de Requirements Analysis)

| Ref | Pregunta | Decisión |
|---|---|---|
| P1 | Ubicación | Documento `.md` nuevo, junto al contexto general (`docs/contexto-tecnico.md`). |
| P2 | Profundidad | **Diseño técnico detallado** (stack, servicios AWS por capa, esquemas, parámetros, despliegue). |
| P3 | Nivel AWS | **Nombrar servicios AWS concretos** por capa (recomendación). |
| P4 | FHIR | **Capa de primera clase**: mapeo FHIR R4 / CL Core, Provenance, RiskAssessment, versionado. |
| P5 | Eje box | Priorización clínica como foco principal; **uso de box a alto nivel**. |
| P6 | Idioma/formato | Español, Markdown, con diagramas Mermaid cuando sean comprensibles por un LLM. |

## Configuración de extensiones (habilitadas)

| Extensión | Estado | Consecuencia en el contexto técnico |
|---|---|---|
| Security Baseline | **Habilitada** | El documento debe incorporar las reglas SECURITY-01..15 aplicables (cifrado en reposo/tránsito, logging, validación de entradas, mínimo privilegio, red restrictiva, gestión de secretos, manejo seguro de errores, auditoría inmutable, cadena de suministro). |
| Resiliency Baseline | **Habilitada** | El documento debe incorporar RESILIENCY-01..15 aplicables (clasificación de criticidad, RTO/RPO, observabilidad, salud, multi-AZ, auto-escalado, aislamiento de dependencias, DR, backups, runbooks, pruebas, respuesta a incidentes). |
| Property-Based Testing | **Habilitada** | El documento debe definir la estrategia de pruebas: PBT (round-trip, invariantes, idempotencia, oráculo, stateful) + ejemplos, con framework por lenguaje y reproducibilidad por semilla. |

## Decisiones de resiliencia y operación (del usuario)

| Ref | Decisión | Nota |
|---|---|---|
| DR (R1+R2+Aclaración) | **Una región, multi-AZ, Backup & Restore. RTO/RPO en horas.** | Coherente con el lote nocturno y la ventana de 72 h (KPI). Escalable a Pilot Light multi-región si pasa a near-real-time o 24/7. |
| R3 Gestión de cambios | **Proponer** proceso ligero (registro de cambio + aprobación + nota de rollback). | No existe proceso formal. |
| R4 CI/CD | **Proponer** pipeline (GitHub Actions o AWS CodePipeline) acorde al IaC y runtime. | — |
| R5 Rollback | **Por versión fijada (A)** para cómputo **+ consciente de BD (D)** para almacenes con esquema. | Las migraciones de `propuesta_prioridad`, `decision_clinica` y la auditoría requieren reversión controlada. |
| R6 Estilo de despliegue | **Directo / in-place.** | Radio de impacto acotado por ser batch nocturno. |
| R7 Respuesta a incidentes | **Proponer** proceso ligero de IR + COE. | — |
| R8 Pruebas de resiliencia | **Proponer** calendario de pruebas de DR y experimentos de caos. | Escenarios: restore desde backup, re-ejecución del lote. |

---

## Requisitos funcionales (del contexto técnico a documentar)

El contexto técnico (documento objetivo) debe describir, a nivel de diseño detallado:

- **RF-01 Principio rector.** Formalizar "el software DETECTA → la IA ANALIZA → el MÉDICO DECIDE → todo queda TRAZADO", con la salida siempre en estado `pendiente_revision_medica` hasta la decisión clínica.
- **RF-02 Determinismo.** Puntajes, cohortes e intervalos los calcula código determinista; el LLM no produce cifras.
- **RF-03 Contrato de datos y cuarentena.** Esquema oficial de entrada (perfil por paciente, equivalente a `Patient/$everything`), validación y aislamiento de perfiles inválidos a cuarentena; reglas de conciliación tabla-plana ↔ contrato; identificador determinista de medición; cruce cita–box por `(id_box, fecha)`.
- **RF-04 Fecha de corte.** Todo cálculo usa solo registros con fecha ≤ corte (sin fuga de información futura); `estado` anterior al corte se reemplaza por `desconocido_a_la_fecha`.
- **RF-05 Motor de reglas.** Secuencia de evaluación (exclusiones duras → base → eventos con decaimiento → mediciones bidireccionales → tiempo de espera → banderas rojas → pisos → contradicciones → gestión), niveles de salida (crítica/alta/media/baja), parámetros versionados, cada punto con motivo y registros de respaldo.
- **RF-06 Calidad de datos.** Niveles `descartar`/`verificar`/`info`, categorías de hallazgo, límites de plausibilidad separados de los rangos normales; un dato imposible no altera prioridades.
- **RF-07 Copiloto IA.** Rol de asistente del médico contralor; modos reactivo (con herramientas de consulta restringidas) y barrido (nocturno, perfil precargado, salida forzada estructurada); reglas "siempre/nunca"; esquema de salida estructurada; resistencia a inyección por texto de registros.
- **RF-08 Salidas del agente.** Resumen clínico consolidado, propuesta de prioridad explicada, alertas, bandeja de validación (aceptar/ajustar/rechazar) y propuesta de agenda por box.
- **RF-09 Trazabilidad.** Registro de auditoría inmutable (llamada al modelo, herramienta, análisis IA, decisión médica, error de proceso) que responda "quién vio qué, cuándo, con qué datos, qué sugirió la IA y qué decidió el médico".
- **RF-10 Interoperabilidad FHIR.** Mapeo a FHIR R4 (Patient, ServiceRequest/CIE-10, Encounter EMER/IMP/AMB, Observation/LOINC, Appointment, RiskAssessment preliminary/final, Provenance assembler/verifier), validado contra CL Core de HL7 Chile.
- **RF-11 Uso del box (alto nivel).** Señales de riesgo de no-show (separadas del puntaje clínico), ocupación/sobretiempo por especialidad y propuesta de asignación de cupos ociosos.
- **RF-12 Cadencia.** Lote nocturno que consolida registros y recalcula prioridades; un evento relevante se refleja en ≤ 72 h (KPI principal).
- **RF-13 Vistas.** Para el clínico, el gestor de la lista y la gestión de box; con selector de fecha de corte para la demo.

## Requisitos no funcionales

- **RNF-Seguridad (SECURITY-01..15).** Datos clínicos anonimizados; el modelo nunca recibe nombres; RUT pseudonimizado con hash y sal secreta; secretos fuera del control de versiones; cifrado en reposo y en tránsito (TLS 1.2+); auditoría inmutable (append-only); validación de entradas; mínimo privilegio IAM; red deny-by-default; manejo de errores fail-closed; retención de logs ≥ 90 días; los textos de registros se tratan como datos, nunca como instrucciones.
- **RNF-Resiliencia (RESILIENCY-01..15).** Clasificación de criticidad por componente; DR Backup & Restore una región multi-AZ (RTO/RPO en horas); observabilidad (métricas/logs/trazas); health checks; multi-AZ en cómputo y almacenamiento; auto-escalado/concurrencia; timeouts y aislamiento de dependencias; backups cifrados y validados; runbooks de failover/failback; respuesta a incidentes y pruebas de DR capturadas para Operaciones.
- **RNF-Pruebas (PBT-01..10).** Estrategia PBT + ejemplos: round-trip (serialización FHIR, parse/format de fechas, round-trip del contrato de datos), invariantes (el puntaje respeta pisos/banderas; comuna/previsión/NSE nunca bajan la prioridad; monotonía del envejecimiento), idempotencia (recálculo con la misma fecha de corte da el mismo resultado), oráculo (motor determinista vs. referencia), stateful (bandeja de validación), generadores de dominio, shrinking y reproducibilidad por semilla, framework por lenguaje.
- **RNF-Equidad.** Comuna, previsión y nivel socioeconómico **nunca bajan** la prioridad; la inasistencia no baja la prioridad clínica.
- **RNF-Explicabilidad.** Cada cambio de prioridad muestra evento gatillante, factores con su peso, fuentes citadas y nivel de confianza; "revisar manualmente" si la información es insuficiente.
- **RNF-Trazabilidad/Versionado.** Cada análisis guarda modelo, versión del prompt e identificador de solicitud.
- **RNF-Rendimiento.** El lote nocturno debe reevaluar el 100 % de la lista dentro de la ventana que garantiza el KPI de ≤ 72 h.

## Criterios de éxito del entregable

1. El documento `docs/contexto-tecnico.md` cubre **todos** los temas de la sección 12.9 ("Temas que el diseño técnico debe detallar") del Business Context.
2. Nombra **servicios AWS concretos por capa** y justifica brevemente cada elección.
3. Desarrolla **FHIR R4 / CL Core** como capa de primera clase (recursos, perfiles, Provenance/RiskAssessment, versionado).
4. Incorpora de forma explícita las reglas aplicables de **Security**, **Resiliency** y **PBT**, con resumen de cumplimiento.
5. Es **coherente** con el contexto de negocio existente (no lo contradice) y respeta el principio "la IA no decide".
6. Español, Markdown, con diagramas Mermaid donde aporten; validado para parseo.

## Fuera de alcance

- Generación de código de aplicación (se abordaría en la fase de Construcción, si el usuario lo decide).
- Integración con VIAU y homologación formal ACG→G.
- Modificar el documento de negocio existente (el contexto técnico va en archivo aparte).

---

## Resumen

El objetivo es producir, siguiendo AI-DLC, un **contexto técnico detallado** (`docs/contexto-tecnico.md`) que complete la sección 12 del Business Context: principios, arquitectura lógica con **servicios AWS concretos**, contrato de datos y cuarentena, motor de reglas determinista, calidad de datos, copiloto IA (reactivo/barrido), **trazabilidad e interoperabilidad FHIR R4/CL Core de primera clase**, y uso de box a alto nivel. Se incorporan como restricciones las extensiones habilitadas (Seguridad, Resiliencia, PBT) y las decisiones de DR/operación del usuario (una región multi-AZ, Backup & Restore; CI/CD, gestión de cambios, rollback A+D, despliegue directo, IR y pruebas de DR propuestos). No se genera código en esta etapa.
