# Datos

El HLF entregó el **Dataset Atención Ambulatoria Dinámica HLF** para el reto *Priorización Clínica Evolutiva y Uso del Recurso Box*. Este documento resume su esquema, lo que contiene de verdad y en qué se aparta de lo que anunció la presentación del desafío.

Fuente: `data/dataset_hlf_ambulatorio/dataset_hlf_ambulatorio/` (`README.md`, `diccionario_datos.md`, `pacientes_ejemplo_HLF.md`). Para casos concretos, ver `docs/casos-ejemplo.md`.

> ⚠️ Aunque este dataset es sintético, la carpeta `data/dataset_hlf_ambulatorio/` está en `.gitignore` y los CSV no se versionan. Mantenerlo así: cualquier dato real del hospital va en `data/raw/`.

## Resumen

| Característica | Valor |
|---|---|
| Origen | **100 % sintético** (semilla 20261013). Sin RUT ni nombres reales |
| Pacientes | 500 (`PAC-HLF-00001` … `PAC-HLF-00500`) |
| Fecha de referencia ("hoy") | **2026-10-13** |
| Especialidades | 7: Broncopulmonar, Cardiología, Endocrinología, Gastroenterología, Neurología, Salud Mental, Traumatología. **No incluye oftalmología** |
| Estructura | Serie temporal de eventos y mediciones durante la espera |
| Respuesta de referencia | **No hay.** Cada equipo diseña su algoritmo de priorización dinámica y de uso de box |
| Llave de enlace | `id_paciente`; `citaciones.id_box` → `agenda_box.id_box` |

## Archivos

| Archivo | Filas | Grano |
|---|---|---|
| `pacientes.csv` | 500 | Un paciente (tabla maestra) |
| `lista_espera.csv` | 500 | Una solicitud en espera (una por paciente) |
| `eventos_clinicos.csv` | 786 | Un evento clínico con fecha (0..N por paciente) |
| `mediciones.csv` | 2.487 | Una medición con fecha (0..N por paciente) |
| `agenda_box.csv` | 2.188 | Un bloque de agenda de un box en un día hábil |
| `citaciones.csv` | 257 | Una cita ofrecida (0..N por paciente) |
| `perfiles.json` | 500 | Un objeto por paciente con todo lo anterior anidado (salvo `agenda_box`) |

```
pacientes (1) ──< lista_espera (1)
pacientes (1) ──< eventos_clinicos (0..N)
pacientes (1) ──< mediciones (0..N)
pacientes (1) ──< citaciones (0..N) >── agenda_box (por id_box)
```

## Esquema por archivo

### `pacientes.csv`
| Campo | Tipo | Valores | Notas |
|---|---|---|---|
| `id_paciente` | texto | `PAC-HLF-#####` | PK |
| `nombre_fantasia` | texto | `Paciente <Flor> NNN` | Ficticio; útil para la demo |
| `edad` | entero | 19–90 | A la fecha de referencia |
| `sexo` | texto | `F`, `M` | |
| `comuna` | texto | La Florida, La Granja, La Pintana, Pirque, Puente Alto, San José de Maipo, San Ramón | Red Sur Oriente |
| `prevision` | texto | FONASA A–D, ISAPRE | |
| `nivel_socioeconomico` | texto | bajo, medio-bajo, medio | |
| `fallecido` | booleano | `true`, `false` | 15 pacientes fallecidos |
| `fecha_defuncion` | fecha | ISO o vacío | Control de exclusión |

### `lista_espera.csv` (la lista "congelada")
| Campo | Tipo | Valores | Notas |
|---|---|---|---|
| `id_paciente` | texto | FK | |
| `id_solicitud` | texto | `IC-HLF-#####` | Interconsulta |
| `especialidad` | texto | 7 especialidades | |
| `sub_especialidad` | texto | 15 valores | Ver tabla de diagnósticos abajo |
| `diagnostico_cie10` | texto | 17 códigos de **3 caracteres** (`E11`, `I20`…) | Sin subcategoría: al normalizar, no agregar punto |
| `diagnostico_texto` | texto | Descripción del CIE-10 | |
| `prioridad_inicial` | texto | alta, media, baja | **Línea base estática**. Nunca se sobrescribe |
| `fecha_ingreso_lista` | fecha | 2025-04-21 … 2026-09-30 | Desde aquí se cuentan los días de espera |
| `origen_derivacion` | texto | CESFAM/APS, Urgencia, Hospitalización, Otro hospital red | |
| `estado` | texto | en_espera, atendido, fallecido (el diccionario también define citado y egresado, que no aparecen) | |

**Diagnósticos presentes**

| Especialidad | Sub-especialidad | CIE-10 |
|---|---|---|
| Broncopulmonar | Asma / EPOC | J45 Asma · J44 EPOC |
| Cardiología | Cardiología adulto | I10 Hipertensión esencial · I20 Angina de pecho |
| Cardiología | Insuficiencia cardíaca | I50 Insuficiencia cardíaca |
| Endocrinología | Diabetes | E11 Diabetes mellitus tipo 2 · E66 Obesidad |
| Endocrinología | Tiroides | E03 Hipotiroidismo |
| Gastroenterología | Digestivo alto / Hígado | K21 Enfermedad por reflujo · K70 Enfermedad hepática |
| Neurología | Cefaleas / Epilepsia | G43 Migraña · G40 Epilepsia |
| Salud Mental | Psicología / Psiquiatría adulto | F41 Trastorno de ansiedad · F32 Episodio depresivo |
| Traumatología | Columna / Hombro / Rodilla | M54 Lumbago · M75 Lesión del hombro · M17 Artrosis de rodilla |

### `eventos_clinicos.csv` (motor de la priorización dinámica)
| Campo | Tipo | Valores | Notas |
|---|---|---|---|
| `id_paciente` | texto | FK | |
| `id_evento` | texto | `EV-######` | Usar como `fuente` en la explicación |
| `fecha_evento` | fecha | Entre el ingreso a la lista y hoy (o la defunción) | |
| `tipo_evento` | texto | Ver tabla | |
| `subtipo` | texto | 13 valores | |
| `severidad` | texto | leve, moderada, grave | |
| `detalle` | texto | `"<subtipo> (<especialidad>)"` | Es plantilla, **no** texto libre clínico |

**Combinaciones tipo / subtipo / severidad** (son fijas: cada subtipo tiene siempre la misma severidad)

| `tipo_evento` | `subtipo` | `severidad` | n | Dirección esperada |
|---|---|---|---|---|
| `visita_urgencia` | triage ESI 2 | grave | 55 | ↑↑ |
| `visita_urgencia` | descompensación grave | grave | 15 | ↑↑ |
| `visita_urgencia` | descompensación | moderada | 40 | ↑ |
| `hospitalizacion` | ingreso hospitalario | grave | 55 | ↑↑ |
| `hospitalizacion` | ingreso UCI | grave | 15 | ↑↑↑ |
| `examen_alterado` | resultado alterado | moderada | 103 | ↑ |
| `cambio_farmaco` | aumento dosis | moderada | 103 | ↑ |
| `cambio_farmaco` | reducción dosis | leve | 49 | ↓ |
| `control_aps` | buena respuesta | leve | 49 | ↓ |
| `control_aps` | estabilización | leve | 40 | ↓ |
| `control_aps` | control crónico / control de rutina / control | leve | 262 | ≈ |

La columna "dirección esperada" es una lectura del equipo, no viene en los datos.

### `mediciones.csv` (señales objetivas)
| Campo | Tipo | Valores | Notas |
|---|---|---|---|
| `id_paciente` | texto | FK | |
| `fecha_medicion` | fecha | Entre el ingreso y hoy (o la defunción) | |
| `tipo_medicion` | texto | Ver tabla | |
| `valor` | numérico | | |
| `unidad` | texto | %, L/min, mg/dL, mmHg, puntos | |
| `fuera_de_rango` | booleano | | Calculado con los rangos de abajo |

| `tipo_medicion` | Rango normal | Unidad | Especialidades donde aparece |
|---|---|---|---|
| `presion_sistolica` | 90–139 | mmHg | Cardiología |
| `presion_diastolica` | 60–89 | mmHg | Cardiología |
| `HbA1c` | 4,0–6,4 | % | Endocrinología |
| `glicemia` | 70–140 | mg/dL | Endocrinología, Gastroenterología |
| `saturacion_o2` | 95–100 | % | Broncopulmonar |
| `peak_flow` | 350–600 | L/min | Broncopulmonar |
| `escala_dolor_eva` | 0–3 | puntos | Traumatología, Neurología |
| `PHQ9` | 0–9 | puntos | Salud Mental |

`fuera_de_rango` es binario. Para medir **cuánto** se aleja y la **tendencia**, calcular la distancia al rango y la pendiente de la serie.

### `agenda_box.csv` (capacidad instalada)
| Campo | Tipo | Valores | Notas |
|---|---|---|---|
| `id_box` | texto | `BOX-01` … `BOX-20` | |
| `fecha` | fecha | 2026-04-14 … 2026-10-13, días hábiles | |
| `especialidad` | texto | 7 especialidades | Cada box atiende **siempre la misma** especialidad (Cardiología y Traumatología tienen 1 box; Broncopulmonar, 6) |
| `bloque_inicio` / `bloque_fin` | hora | 08:30 / 13:30 | Un bloque de 5 h por box y día |
| `capacidad_cupos` | entero | 8, 10, 12 | |
| `cupos_usados` | entero | 0–12 | ≤ capacidad. Ocupación global ≈ 74 % |
| `minutos_sobretiempo` | entero | 0–124 | Atraso acumulado del box ese día |

### `citaciones.csv` (asistencia y uso real)
| Campo | Tipo | Valores | Notas |
|---|---|---|---|
| `id_paciente` | texto | FK | 237 pacientes con al menos una cita |
| `id_cita` | texto | `CT-######` | |
| `id_box` | texto | FK a `agenda_box` | |
| `fecha_cita` | fecha | 2026-01-31 … 2026-10-10 | Solo fecha, sin hora |
| `especialidad` | texto | 7 especialidades | |
| `estado_cita` | texto | asistio (152), no_asistio (60), reprogramo (41), cancelo (4) | |
| `minutos_atencion_real` | entero | 15–55 o vacío | Solo si `asistio` |

## Distribuciones clave

| Variable | Distribución |
|---|---|
| `prioridad_inicial` | media 238 · baja 168 · alta 94 |
| `estado` | en_espera 409 · atendido 76 · fallecido 15 |
| `origen_derivacion` | CESFAM/APS 304 · Urgencia 102 · Hospitalización 52 · Otro hospital red 42 |
| `especialidad` | Traumatología 104 · Cardiología 101 · Endocrinología 85 · Salud Mental 79 · Broncopulmonar 54 · Neurología 41 · Gastroenterología 36 |
| Pacientes con eventos | 381 de 500 |
| Pacientes con mediciones | 451 de 500 |

## Reglas de uso

- **Fecha de corte.** Para recalcular la prioridad a una fecha *t*, usar solo eventos, mediciones y citas con fecha ≤ *t*. Así se simula lo que el hospital sabía ese día y se evita filtrar información del futuro.
- **Ausencia de registros.** Un paciente sin eventos ni mediciones no tiene señales durante la espera (estable o de ingreso reciente). No es un error ni un dato faltante que haya que imputar.
- **Exclusión de fallecidos.** Con `fallecido = true` el paciente sale de la lista y no recibe nuevas citaciones. Toda su actividad es anterior a `fecha_defuncion` (verificado).
- **Patrones sin etiquetar.** Deterioro progresivo, deterioro agudo, mejora, inasistencia y estabilidad no vienen marcados: el algoritmo debe descubrirlos. Ver `docs/casos-ejemplo.md`.

## Advertencias de calidad (verificadas sobre el dataset)

- **`citaciones` no siempre cruza con `agenda_box`.** De 257 citas, 118 no tienen un bloque con el mismo `(id_box, fecha)`, y 121 caen en un box que ese día atiende otra especialidad. Además 27 citas son anteriores al inicio de la agenda (2026-04-14). Tratar `agenda_box` y `citaciones` como fuentes de capacidad y de demanda **independientes**; no sumar citas para reconstruir `cupos_usados`.
- **Fechas de ingreso:** el diccionario dice "hasta 2026-10"; el máximo real es 2026-09-30.
- **CIE-10 sin subcategoría:** todos los códigos tienen 3 caracteres. Normalizar a mayúsculas, sin agregar punto.
- **Sin vínculo cita → solicitud:** las citas no traen `id_solicitud`. Como hay una solicitud por paciente, se puede enlazar por `id_paciente`.
- **Todo `atendido` tiene al menos una cita con `asistio`**, pero también hay 76 citas con `asistio` de pacientes que siguen `en_espera`. Asistir a una cita no implica salir de la lista: no inferir el egreso desde `citaciones`.

## Diferencias con lo anunciado en la presentación

La presentación del desafío anunció una base de **oftalmología** con más campos. El dataset entregado cambia el alcance:

| Anunciado | En el dataset | Consecuencia |
|---|---|---|
| Oftalmología | 7 otras especialidades | El algoritmo debe ser genérico por especialidad; la relevancia evento ↔ diagnóstico se define por especialidad |
| Tipo: consulta nueva o control | No existe | No se pueden separar las dos listas ni medir controles visibles con este dataset |
| Fecha de derivación | No existe | Los días de espera se cuentan desde `fecha_ingreso_lista` |
| Causal de egreso | Solo `estado` | `fallecido` y `atendido` hacen de causal |
| Establecimiento de origen | Solo `origen_derivacion` (categórico) | |
| RCE en texto libre (indicaciones de control, fármacos) | `detalle` es plantilla | La extracción con NER/LLM no tiene material real aquí; probarla con datos sintéticos propios |
| Comorbilidades, riesgo ACG | No existen | El puntaje se apoya en diagnóstico, edad, eventos y mediciones |
| — | **Nuevo:** `mediciones`, `agenda_box`, `citaciones`, `nivel_socioeconomico` | Permite tendencias objetivas y el segundo eje del reto: uso del box |

## Tablas que genera el sistema

```
propuesta_prioridad (id_solicitud FK, fecha_corte, fecha_calculo, puntaje,
                     prioridad_propuesta, explicacion JSON, version_modelo)
decision_clinica    (id_solicitud FK, id_propuesta FK, decision [acepta|ajusta|rechaza],
                     prioridad_final, motivo, usuario, fecha)
```

`prioridad_inicial` nunca se modifica: la propuesta va en `propuesta_prioridad` y la decisión humana en `decision_clinica`.

## Preguntas abiertas para el HLF

- [ ] ¿Habrá una versión con oftalmología, o el prototipo se evalúa con estas 7 especialidades?
- [ ] ¿Hay una muestra con priorización experta para medir concordancia (kappa)? El README dice que no hay respuesta de referencia.
- [ ] ¿Cuál es la relación esperada entre `citaciones` y `agenda_box`, dado que muchas citas no cruzan?
- [ ] ¿La escala de tres niveles (alta, media, baja) es la que usa hoy el HLF?
- [ ] ¿Qué significa "uso del recurso box" en la evaluación: ocupación, inasistencias, sobretiempo o asignación de cupos?

## Datos sintéticos propios

Para tests y casos que el dataset no cubre (oftalmología, notas en texto libre, indicaciones de control, el **caso de don Manuel** de `docs/contexto.md`), generar trayectorias en `data/synthetic/` con **el mismo esquema que este dataset**.
