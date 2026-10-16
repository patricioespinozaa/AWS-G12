# U1 — Reglas de negocio

Los valores numéricos son los referenciales de `docs/contexto-tecnico.md` (secciones 6 y 7), versionados como `reglas-v0.1.0`. Las respuestas F-1..F-5 del plan quedan incorporadas.

## R1 Contrato y cuarentena

| Regla | Detalle |
|---|---|
| R1.1 | Un perfil va a cuarentena si falla cualquiera de las condiciones de la sección 4.2 del contexto técnico. Se guardan los motivos y la versión del contrato |
| R1.2 | Un perfil en cuarentena no se evalúa; su solicitud recibe la alerta `perfil_en_cuarentena` |
| R1.3 | Cobertura: cada solicitud `en_espera` termina evaluada o en cuarentena. Si no, el lote falla |

## R2 Fecha de corte (sin fuga de información futura)

| Regla | Detalle |
|---|---|
| R2.1 | Solo entran eventos, mediciones y citas con fecha ≤ `fecha_corte` |
| R2.2 | `fecha_corte` no puede ser posterior a `fecha_extraccion` (2026-10-13) ni anterior a `fecha_ingreso_lista`. Fuera de ese rango, error de validación |
| R2.3 | La edad se recalcula: `edad_corte = edad − años completos entre fecha_corte y fecha_extraccion` |
| R2.4 | `estado_a_la_fecha` según `domain-entities.md` |

## R3 Exclusiones duras

| Regla | Condición | Resultado |
|---|---|---|
| R3.1 | `fecha_defuncion ≤ fecha_corte` | `exclusion`, código `EX_FALLECIDO` |
| R3.2 | `fecha_corte = fecha_extraccion` y `estado = atendido` | `exclusion`, código `EX_ATENDIDO` |
| R3.3 (F-1) | `fecha_corte < fecha_extraccion`, `estado = atendido` en la extracción y existe una cita `asistio` de la misma especialidad con fecha ≤ `fecha_corte` | `exclusion`, código `EX_ATENDIDO_INFERIDO`, con la última de esas citas como `fecha_egreso_inferida` y la marca `inferido` |
| R3.4 | Paciente `en_espera` con citas `asistio` | **No** se excluye (asistir no implica egreso, `docs/datos.md`); puede generar `estado_inconsistente` |

Si un paciente fallecido sigue con estado distinto de `fallecido`, además se emite `fallecido_en_lista`.

## R4 Calidad de datos

Tabla de la sección 7 del contexto técnico. Lo marcado `descartar` se quita **antes** del puntaje. Límites de plausibilidad: sección 7.1. El motor calcula `fuera_de_rango` con los rangos de referencia y no usa el booleano de origen; si difieren, hallazgo `verificar`.

## R5 Puntaje

```
puntaje = acotar_0_100( base + Σ eventos + aceleración + min(20, Σ mediciones) + espera )
```

| Regla | Detalle |
|---|---|
| R5.1 Base | alta 60, media 40, baja 20 |
| R5.2 Evento | `w(tipo, subtipo) × r × exp(−λ·Δt)`, λ = ln 2 / 90, Δt en días hasta el corte. Pesos: sección 6.3 |
| R5.3 Relación | `r = 1,0` si `especialidad_evento` = especialidad de la solicitud; `0,5` si no |
| R5.4 Aceleración | +5 si eventos graves en (corte−90, corte] > eventos graves en (corte−180, corte−90] |
| R5.5 Zona | Por tipo de medición, último valor no descartado: `min(10, 10 × distancia/ancho)` en la dirección dañina (tabla 6.4) |
| R5.6 Brusco | +4 si el último valor se aleja de la mediana de los anteriores más de 0,2 × ancho, en la dirección dañina. Requiere ≥ 1 valor previo |
| R5.7 Tendencia | +4 si la pendiente (regresión lineal de las últimas 3 a 5 mediciones) va en la dirección dañina con magnitud ≥ 0,1 × ancho por cada 30 días, y esas mediciones abarcan ≥ 60 días. **Umbral de magnitud agregado en este diseño** (el contexto técnico no lo fijaba) para no sumar por ruido |
| R5.8 Espera | `min(10, 10 × max(0, días − plazo)/plazo)`; plazos alta 30, media 90, baja 180 |
| R5.9 Contradicción | Si un evento de mejoría tiene una medición en zona de riesgo de la misma especialidad entre −14 y +30 días, su aporte negativo se reemplaza por 0 |

En mediciones bidireccionales (presión, glicemia), "dirección dañina" es alejarse del rango por cualquier lado.

## R6 Niveles

| Regla | Detalle |
|---|---|
| R6.1 | `nivel_calculado`: baja < 40 ≤ media < 60 ≤ alta |
| R6.2 Pisos | Sobre mediciones de los últimos 90 días: EVA ≥ 8, HbA1c ≥ 10 %, PHQ-9 ≥ 15 → al menos `alta` |
| R6.3 Banderas | Sobre los últimos 90 días (mediciones) o 30 días (eventos): tabla 6.6 del contexto técnico → `crítica` |
| R6.4 (F-3) | La bandera por evento grave dura 30 días desde el evento; después se evalúa sin ella |
| R6.5 (F-2) | `nivel_propuesto` nunca queda más de un nivel por debajo de `prioridad_inicial`. Bajar además exige evidencia de mejoría: al menos un evento de mejoría sin contradicción **y** todas las mediciones de los últimos 90 días en rango. Si no hay esa evidencia, el nivel propuesto no baja de `prioridad_inicial` |
| R6.6 | Orden: nivel calculado → límite de bajada (R6.5) → pisos → banderas. El resultado de una bandera o un piso no lo puede deshacer otra regla |

## R7 Alertas de gestión

Tabla 6.7 del contexto técnico. No modifican el puntaje ni el nivel. `control_invisible` es N/A en el MVP (sin texto clínico). `alta_sin_examenes` es N/A (sin datos de exámenes requeridos).

## R8 Tipo de resultado y confianza

| Regla | Detalle |
|---|---|
| R8.1 | `exclusion` si R3; si no, `priorizacion` si `nivel_propuesto ≠ prioridad_inicial` o hay bandera; si no, `gestion` si hay alertas; si no, `sin_alerta` |
| R8.2 | Confianza según la sección 6.8 del contexto técnico. Una exclusión inferida (R3.3) tiene confianza `media` como máximo |

## R9 Cohortes (F-4)

Sección 5.3 del contexto técnico, en memoria. El desenlace (evento grave en 90 días desde el ingreso) se calcula solo con registros ≤ corte, y solo entran solicitudes con `fecha_ingreso_lista ≤ corte − 90`. El propio paciente queda fuera. IC95 de Wilson.

## R10 Calibración (F-5)

Si un caso de `docs/casos-ejemplo.md` falla, se ajustan los parámetros en una nueva versión `reglas-v0.1.x` y se anota en `aidlc-docs/construction/u1-nucleo-motor/bitacora-parametros.md` qué cambió, por qué y qué casos se volvieron a verificar. Si un ajuste rompe otro caso, se consulta al equipo.

## Equidad (transversal)

`comuna`, `prevision` y `nivel_socioeconomico` no existen en `ContextoPaciente`. Las citas no entran a R5 ni a R6: solo a R7.


---

# Cambio reglas-v0.2.0 — Solicitudes del mismo paciente y relaciones clínicas (2026-10-16)

Pedido del usuario: cuando un paciente ya en espera recibe una nueva SIC de la misma especialidad y otra subespecialidad, cada SIC debe considerar el posible impacto de la otra, en ambos sentidos. Las relaciones entre eventos y diagnósticos, incluso de especialidades distintas, vienen de un documento del hospital que se trata como **insumo estándar**.

Base de negocio: secciones 5.1 (la acumulación de consultas del mismo paciente "es un fenómeno a considerar"), 5.3 (deduplicación) y 7 (factor "cruce entre especialidades", "según definición clínica vigente").

`reglas-v0.1.0` queda sin cambios; `reglas-v0.2.0` pasa a ser la versión por defecto.

## Insumo: documento de relaciones clínicas

- Archivo versionado `data/conocimiento/relaciones-clinicas-vX.Y.Z.yaml`, referenciado por versión desde `reglas-v0.2.0.yaml` (`relaciones: relaciones-clinicas-v0.1.0`).
- La versión actual es una **plantilla sintética no validada** (`estado: sintetico_no_validado`). Debe reemplazarla el documento del HLF (T3).
- Se valida al cargar: versión coincide con el nombre, factores en [0, 1], especialidades del catálogo, CIE-10 con formato válido, sin pares repetidos. Inválido → el lote se detiene (fail-closed, igual que los parámetros).
- Si `estado` no es `validado`, **solo las evaluaciones que usaron el documento** (algún evento de otra especialidad o algún factor `otra_solicitud`) llevan el motivo de confianza "relaciones clínicas no validadas", y su confianza no puede ser `alta`. Las demás no cambian.

## R5.3 (modificada) — Relación evento ↔ solicitud

| Caso | Factor `r` |
|---|---|
| Evento de la misma especialidad que la solicitud | 1,0 |
| Evento de otra especialidad, par listado en `especialidades.pares` (`de` = especialidad del evento, `a` = de la solicitud) | El del documento |
| Evento de otra especialidad, par no listado | `especialidades.por_defecto_otra_especialidad` (0,5, igual que v0.1.0) |

El factor usado se informa en el detalle del factor ("relación Endocrinología → Cardiología 0,7 según relaciones-clinicas-v0.1.0").

## R5.10 (aclaración) — Eventos anteriores al ingreso de la solicitud

Los eventos y mediciones del paciente anteriores a `fecha_ingreso_lista` de una solicitud **sí aportan** a esa solicitud, con su decaimiento normal. Son la historia del paciente y pueden ser el motivo de la derivación (por ejemplo, una nueva SIC que llega tras una hospitalización). El hallazgo DQ `registro_previo_ingreso` sigue siendo `info` y solo se informa. Esto ya era el comportamiento del código; ahora queda escrito y se corrige la sección 7 del contexto técnico, que decía "no aporta".

## R11 (nueva) — Otras solicitudes abiertas del mismo paciente

Para cada solicitud A y cada otra solicitud B del mismo paciente:

| Regla | Detalle |
|---|---|
| R11.1 Vigencia | B cuenta si `fecha_ingreso_lista_B ≤ corte` y B no está excluida al corte por R3 (fallecido, atendido o atendido inferido) |
| R11.2 Duplicado (negocio 5.3) | Si A y B tienen la misma especialidad **y** el mismo CIE-10, son duplicadas: no se aportan puntaje entre sí. La más reciente (mayor `fecha_ingreso_lista`; empate por `id_solicitud`) recibe la alerta de gestión `sic_duplicada` con el ID de la otra. La subespecialidad distinta no evita el duplicado si el CIE-10 coincide |
| R11.3 Relación | `rel(A, B)` = factor del par `{CIE-10_A, CIE-10_B}` en `diagnosticos.pares` (simétrico); si no está: misma especialidad → `por_defecto_misma_especialidad` (0,5); otra especialidad → `por_defecto_otra_especialidad` (0,0, sin impacto) |
| R11.4 Aporte | `aporte_B = peso_otra_solicitud[prioridad_inicial_B] × rel(A, B)`, con pesos alta 8, media 5, baja 3. **Sin decaimiento:** una solicitud abierta es un problema clínico vigente, no un evento que se aleja en el tiempo |
| R11.5 Tope | La suma de aportes por otras solicitudes en A no supera 10 |
| R11.6 Simetría | El cálculo es simétrico por construcción: A recibe impacto de B y B recibe impacto de A, cada uno con la prioridad inicial de la otra |
| R11.7 Explicación | Factor `otra_solicitud` con `ids_registro = [id_solicitud_B]` y detalle "CIE-10_B (subespecialidad, prioridad inicial), relación x según relaciones-clinicas-vX" |
| R11.8 Equidad | Sin cambios: R11 solo usa especialidad, CIE-10, prioridad inicial y fechas |

El puntaje queda: `base + eventos + aceleración + min(20, mediciones) + espera + min(10, otras solicitudes)`, acotado a [0, 100]. R6 (niveles, límite de bajada, pisos, banderas) no cambia.

## Efecto esperado en el escenario de referencia

Escenario sintético reproducible `data/synthetic/escenario-multi-sic/` (PAC-SIN-00001; IC-SIN-00001 I20 baja, ingreso 2025-11-08; IC-SIN-00002 I50 media, ingreso 2026-08-01), corte 2026-08-10, `rel(I20, I50) = 0,9`. Valores reales del lote:
- IC-SIN-00001 (I20): recibe `5 × 0,9 = 4,5` de la nueva: 79,85 → 84,35.
- IC-SIN-00002 (I50): recibe `3 × 0,9 = 2,7` de la anterior: 97,27 (94,57 sin R11).

(El cálculo previo con PAC-HLF-00002 en memoria daba los mismos aportes, +4,5 y +2,7.)

## Efecto en el dataset actual

Ninguno en los puntajes: cada paciente tiene una sola SIC y no hay eventos de otra especialidad (verificado: 0 de 786). Los 6 casos de referencia deben dar lo mismo que con v0.1.0; solo cambia `version_reglas`.

## Propiedades testeables nuevas (PBT-01)

- Simetría: con dos solicitudes A y B, el aporte de B en A usa la prioridad de B y el de A en B usa la de A, con el mismo `rel`.
- Agregar una SIC de otra especialidad sin par listado no cambia el puntaje de las existentes (rel = 0).
- Agregar una SIC nunca baja el puntaje de otra solicitud del paciente (aportes ≥ 0).
- Duplicadas (misma especialidad y CIE-10) no se aportan entre sí.
- Tope: el aporte total por otras solicitudes ≤ 10.
- Una SIC con ingreso posterior al corte no aporta (sin fuga de información futura).
- Con una sola SIC por paciente, v0.2.0 con el documento por defecto da el mismo puntaje que v0.1.0 (oráculo).
