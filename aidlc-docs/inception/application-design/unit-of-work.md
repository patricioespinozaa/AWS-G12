# Unidades de trabajo — MVP demo (16-10-2026)

Decisiones del plan (`aidlc-docs/inception/plans/unit-of-work-plan.md`): U-1=A, U-2=B, U-3=D, U-4=B, U-5=A, U-6=A, U-7=B, U-8=A.

## Alcance del MVP

Entran **U1, U2 y U3**, ejecutadas en local con el dataset sintético y Bedrock real en `us-east-1`. **U4, U5 y U6** quedan fuera de la demo: se presentan con los diagramas de `docs/contexto-tecnico.md` y se construyen después.

Tipo de despliegue: **monolito modular** (un paquete Python + una app Streamlit). No hay servicios desplegables independientes en el MVP.

## Desviaciones del diseño, solo para la demo

| Diseño (`docs/contexto-tecnico.md`) | MVP | Motivo | Cómo se vuelve al diseño |
|---|---|---|---|
| React + API Gateway + Cognito (D6) | Streamlit local, sin login | Tiempo de construcción | U3-prod reemplaza la interfaz; el paquete no cambia |
| DynamoDB + S3 Object Lock (D3) | Archivos locales: Parquet para propuestas, JSONL solo de agregado para análisis, decisiones y auditoría | Sin infraestructura en la demo | U4 cambia el adaptador de persistencia |
| Step Functions + Glue (D2) | Script `hlf-lote --fecha-corte AAAA-MM-DD` | Ídem | U4 envuelve las mismas funciones en Lambdas |
| Organización 15.1 (paquetes separados) | Un paquete `hlf_priorizacion` con submódulos | U-7 | Se puede separar sin cambiar interfaces |
| Copiloto reactivo | Solo barrido | U-6 | Se agrega en una versión posterior |

Reglas de las extensiones que pasan a **N/A en la demo local** y se exigen al desplegar: SECURITY-02, 04, 07, 08, 12 y 14 (no hay red, API pública ni usuarios); RESILIENCY-04 a 09, 11 a 13 (no hay despliegue). Siguen exigidas en el MVP: SECURITY-03 (logs sin datos clínicos), 05 (validación de entradas), 10 (dependencias fijadas), 15 (manejo de errores); y todas las de PBT para U1 y U2.

## U1 — Núcleo de datos y motor de reglas

| | |
|---|---|
| Componentes | C1 contrato, C2 ingesta, C3 repositorio, C4 calidad de datos, C5 motor de reglas (secciones 4–7 del contexto técnico) |
| Responsable | Persona 1 |
| Entrada | `data/dataset_hlf_ambulatorio/perfiles.json` (+ CSV para conciliación) |
| Salida | `Evaluacion` por solicitud y fecha de corte, con el formato de la sección 6.8; propuestas en `salidas/propuestas/fecha_corte=…/` |
| Incluye | Validación del contrato y cuarentena; ID determinista de medición; contexto a fecha de corte (sin `comuna`, `prevision`, NSE ni nombre); hallazgos DQ; puntaje con eventos, mediciones, espera, banderas, pisos, contradicciones y alertas de gestión; parámetros en `reglas-v0.1.0.yaml`; CLI del lote |
| Excluye | Cohortes con Athena (se calculan en memoria con pandas si da el tiempo; si no, el copiloto declara `datos_faltantes`) |
| Aceptación | Los 6 casos de `docs/casos-ejemplo.md` pasan como pruebas de ejemplo (ver criterios abajo); 100 % de las filas `en_espera` evaluadas o en cuarentena; las propiedades de la sección 16.2 que aplican al motor pasan con Hypothesis |

Criterios de los casos de ejemplo:

| Caso | Criterio |
|---|---|
| PAC-HLF-00001 (deterioro progresivo) | Se mantiene ≥ alta; la explicación incluye la tendencia del PHQ-9 |
| PAC-HLF-00002 (deterioro agudo) | Corte 2026-07-19: baja o media. Corte 2026-07-20 o posterior: ≥ alta (el diseño la lleva a `crítica` por bandera roja de urgencia grave en 30 días) |
| PAC-HLF-00028 (mejora) | Puede bajar como máximo un nivel; explicación con los eventos de mejora |
| PAC-HLF-00020 (inasistencia) | Puntaje igual con y sin sus citas; alerta `citas_fallidas` |
| PAC-HLF-00032 (atendido) | Con corte en la fecha de extracción: `exclusion` |
| PAC-HLF-00009 (fallecido) | Corte ≥ 2026-09-08: `exclusion`; corte anterior: se evalúa |

**Decisión pendiente para el diseño funcional de U1:** según el diseño (4.4), con un corte anterior a la extracción `estado` pasa a `desconocido_a_la_fecha`, así que un paciente `atendido` no se excluye en cortes pasados. `docs/casos-ejemplo.md` dice que PAC-HLF-00032 está atendido "desde 2026-06-30". Hay que decidir si esa fecha se puede inferir (por ejemplo, de la cita `asistio`) o si se mantiene la regla del diseño. `docs/datos.md` advierte que asistir no implica salir de la lista.

## U2 — Copiloto (modo barrido)

| | |
|---|---|
| Componentes | C6 (sección 8 del contexto técnico, solo 8.2, 8.4, 8.5 y 8.6) |
| Responsable | Persona 2 |
| Entrada | `PaqueteBarrido`: snapshot del contexto + `Evaluacion` de U1 + hallazgos DQ |
| Salida | `AnalisisIA` (esquema `analisis-v1`) en `salidas/analisis/…jsonl`, estado `pendiente_revision_medica` |
| Modelo | Variable `HLF_BEDROCK_MODEL_ID`, por defecto `us.anthropic.claude-sonnet-5`; respaldo `us.anthropic.claude-haiku-4-5-20251001-v1:0`. Solo modelos permitidos por la política del workshop |
| Incluye | Converse con `toolChoice` forzado a `registrar_analisis`; prompt versionado con huella; validación de esquema, citas y cifras; reintento y marca `fallido`; registro `llamada_modelo` en la auditoría local; se ejecuta solo sobre `priorizacion` y `exclusion` |
| Aceptación | Para PAC-HLF-00002 con corte 2026-08-10: análisis válido, todo hallazgo `documentado` cita IDs existentes, `prioridad_sugerida = critica` o discrepancia justificada; si Bedrock falla, U1 publica igual |
| Prueba sin Bedrock | Cliente de Bedrock inyectable; en pruebas se usa uno falso que devuelve respuestas fijas o malformadas |

## U3 — Bandeja y vistas (Streamlit)

| | |
|---|---|
| Componentes | C8 bandeja, C11 web (sección 10.3 y 10.4, versión mínima) |
| Responsable | Persona 3 (o Persona 1 al terminar U1) |
| Entrada | Propuestas de U1 y análisis de U2 desde `salidas/` |
| Vistas | 1) Bandeja por especialidad, ordenada por magnitud del cambio, críticas primero. 2) Detalle: línea de tiempo citada, factores con aporte, banderas, análisis IA y nota de pre-consulta. 3) Selector de fecha de corte. 4) Panel de cobertura y alertas de gestión |
| Decisión | Aceptar, ajustar (exige prioridad y motivo) o rechazar (exige motivo); se agrega a `salidas/decisiones.jsonl` y a la auditoría. Nunca se edita una decisión pasada |
| Usuario | Campo de texto "médico" sin autenticación (solo demo local; declarado en la presentación) |
| Aceptación | El recorrido de PAC-HLF-00002 se puede mostrar de punta a punta: corte 2026-07-19 → 2026-07-20 → análisis → decisión registrada |

## Fuera del MVP

| Unidad | Contenido | Cómo se muestra en la demo |
|---|---|---|
| U4 Infraestructura y lote | SAM, Step Functions, Lambdas, DynamoDB, S3 Object Lock, CloudWatch | Diagrama de arquitectura física (contexto técnico, sección 3) |
| U5 Box | Disponibilidad, riesgo de inasistencia, propuesta de agenda | Diseño de la sección 11; la alerta `citas_fallidas` de U1 da un adelanto |
| U6 FHIR | RiskAssessment + Provenance, validación CL Core | Mapeo de la sección 9.3 |

## Organización del código

Patrón monolito multi-unidad (`code-generation.md`), con un solo paquete (U-7=B):

```
pyproject.toml                    # dependencias fijadas + uv.lock
src/hlf_priorizacion/
    contrato/                     # U1: modelos Pydantic, JSON Schema, cuarentena
    ingesta/                      # U1: carga, normalización, ID de medición
    repositorio/                  # U1: contexto a fecha de corte, línea de tiempo
    calidad/                      # U1: hallazgos DQ
    motor/                        # U1: evaluar() puro + reglas/reglas-v0.1.0.yaml
    copiloto/                     # U2: cliente Bedrock, prompts/, validación
    persistencia/                 # U1/U2/U3: lectura y escritura en salidas/
    auditoria/                    # registro JSONL solo de agregado
    lote.py                       # CLI hlf-lote
    modelos.py                    # contratos compartidos: Evaluacion, AnalisisIA, Decision
app/
    bandeja.py                    # U3: Streamlit
tests/
    ejemplos/                     # casos de docs/casos-ejemplo.md
    propiedades/                  # Hypothesis
    estrategias/                  # generadores de dominio
salidas/                          # generado; en .gitignore
```

`salidas/` contiene datos derivados de pacientes y va en `.gitignore`.
