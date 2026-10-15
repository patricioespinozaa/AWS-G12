# Diccionario de datos – Dataset Atención Ambulatoria Dinámica HLF

**Reto:** Priorización Clínica Evolutiva y Uso del Recurso Box
**Dataset:** 500 pacientes · semilla fija · fecha de referencia 13-10-2026 · datos 100% sintéticos
**Llave de enlace:** `id_paciente` (todos los archivos de paciente). `agenda_box` es del hospital y se enlaza con `citaciones` por `id_box`.

Los valores listados son los que efectivamente aparecen en el dataset.

---

## 1. `pacientes.csv` — tabla maestra (500 filas, 1 por paciente)

| Campo | Tipo | Valores / rango | Descripción |
|---|---|---|---|
| `id_paciente` | texto | `PAC-HLF-00001` … `PAC-HLF-00500` | Identificador único ficticio. Llave primaria |
| `nombre_fantasia` | texto | `Paciente <Flor> NNN` | Nombre de fantasía legible. No corresponde a persona real |
| `edad` | entero | 19 – 90 | Edad en años a la fecha de referencia |
| `sexo` | texto | `F`, `M` | Sexo registrado |
| `comuna` | texto | La Florida, La Granja, La Pintana, Pirque, Puente Alto, San José de Maipo, San Ramón | Comuna de residencia (Red Sur Oriente, contexto Hospital La Florida) |
| `prevision` | texto | FONASA A, FONASA B, FONASA C, FONASA D, ISAPRE | Previsión de salud |
| `nivel_socioeconomico` | texto | bajo, medio-bajo, medio | Nivel socioeconómico |
| `fallecido` | booleano | `true`, `false` | Si el paciente falleció |
| `fecha_defuncion` | fecha | `AAAA-MM-DD` o vacío | Fecha de defunción. Vacío si no falleció. Control de exclusión |

---

## 2. `lista_espera.csv` — la lista "congelada" (500 filas, 1 por solicitud)

| Campo | Tipo | Valores / rango | Descripción |
|---|---|---|---|
| `id_paciente` | texto | FK a `pacientes` | Paciente que espera |
| `id_solicitud` | texto | `IC-HLF-00001` … | Identificador de la interconsulta |
| `especialidad` | texto | Broncopulmonar, Cardiología, Endocrinología, Gastroenterología, Neurología, Salud Mental, Traumatología | Especialidad solicitada |
| `sub_especialidad` | texto | 15 valores (coherentes con la especialidad) | Sub-especialidad |
| `diagnostico_cie10` | texto | 17 códigos CIE-10 (E03, E11, E66, F32, F41, G40, G43, I10, I20, I50, J44, J45, K21, K70, M17, M54, M75) | Código diagnóstico (real, asignado sintéticamente) |
| `diagnostico_texto` | texto | descripción del CIE-10 | Diagnóstico legible, coherente con la sub-especialidad |
| `prioridad_inicial` | texto | alta, media, baja | **Estratificación estática inicial** (la "fotografía" que el reto busca "despertar") |
| `fecha_ingreso_lista` | fecha | `2025-04-21` … `2026-10` | Fecha de ingreso a la lista |
| `origen_derivacion` | texto | CESFAM/APS, Urgencia, Hospitalización, Otro hospital red | Desde dónde se derivó |
| `estado` | texto | en_espera, citado, atendido, egresado, fallecido | Estado actual en la lista (en el dataset aparecen: en_espera, atendido, fallecido) |

---

## 3. `eventos_clinicos.csv` — motor de la priorización dinámica (786 filas; serie temporal, 0..N por paciente)

| Campo | Tipo | Valores / rango | Descripción |
|---|---|---|---|
| `id_paciente` | texto | FK a `pacientes` | Paciente del evento |
| `id_evento` | texto | `EV-000001` … | Identificador del evento |
| `fecha_evento` | fecha | dentro de [ingreso_lista, hoy o defunción] | Cuándo ocurrió |
| `tipo_evento` | texto | cambio_farmaco, control_aps, examen_alterado, hospitalizacion, visita_urgencia | Tipo de señal clínica |
| `subtipo` | texto | 13 valores (ej. aumento dosis, triage ESI 2, ingreso hospitalario) | Detalle del evento |
| `severidad` | texto | leve, moderada, grave | Gravedad del evento |
| `detalle` | texto | texto libre | Descripción breve (incluye la especialidad) |

---

## 4. `mediciones.csv` — señales objetivas de evolución (2.487 filas; serie temporal, 0..N por paciente)

| Campo | Tipo | Valores / rango | Descripción |
|---|---|---|---|
| `id_paciente` | texto | FK a `pacientes` | Paciente de la medición |
| `fecha_medicion` | fecha | dentro de [ingreso_lista, hoy o defunción] | Cuándo se midió |
| `tipo_medicion` | texto | HbA1c, PHQ9, escala_dolor_eva, glicemia, peak_flow, presion_diastolica, presion_sistolica, saturacion_o2 | Qué se midió (según especialidad) |
| `valor` | numérico | según tipo | Valor de la medición |
| `unidad` | texto | %, L/min, mg/dL, mmHg, puntos | Unidad |
| `fuera_de_rango` | booleano | `true`, `false` | Si el valor está fuera del rango normal de referencia |

**Rangos normales de referencia usados:** presión sistólica 90–139 mmHg; presión diastólica 60–89 mmHg; HbA1c 4,0–6,4%; glicemia 70–140 mg/dL; saturación O₂ 95–100%; peak flow 350–600 L/min; EVA dolor 0–3 puntos; PHQ-9 0–9 puntos.

---

## 5. `agenda_box.csv` — capacidad instalada (2.188 filas; 1 por bloque de box/día)

| Campo | Tipo | Valores / rango | Descripción |
|---|---|---|---|
| `id_box` | texto | `BOX-01` … `BOX-20` | Box de atención |
| `fecha` | fecha | 2026-04-14 … 2026-10-13 (días hábiles) | Día de agenda |
| `especialidad` | texto | las 7 especialidades | Especialidad que atiende el box ese día |
| `bloque_inicio` | hora | 08:30 | Inicio del bloque |
| `bloque_fin` | hora | 13:30 | Fin del bloque |
| `capacidad_cupos` | entero | 8, 10, 12 | Cupos disponibles en el bloque |
| `cupos_usados` | entero | 0 – 12 | Cupos efectivamente ocupados (≤ capacidad) |
| `minutos_sobretiempo` | entero | 0 – 124 | Atraso acumulado del box ese día |

---

## 6. `citaciones.csv` — asistencia y uso real (257 filas; 1 por cita ofrecida)

| Campo | Tipo | Valores / rango | Descripción |
|---|---|---|---|
| `id_paciente` | texto | FK a `pacientes` | Paciente citado |
| `id_cita` | texto | `CT-000001` … | Identificador de la cita |
| `id_box` | texto | FK a `agenda_box` (`BOX-01`…`BOX-20`) | Box asignado |
| `fecha_cita` | fecha | 2026-01-31 … | Fecha/hora ofrecida |
| `especialidad` | texto | las 7 especialidades | Especialidad de la cita |
| `estado_cita` | texto | asistio, no_asistio, reprogramo, cancelo | Resultado de la cita |
| `minutos_atencion_real` | entero | 15 – 55, o vacío | Duración real. Solo tiene valor si `estado_cita = asistio` |

---

## 7. Cómo se relacionan los archivos

```
pacientes (1) ──< lista_espera (1 por paciente)
pacientes (1) ──< eventos_clinicos (0..N)
pacientes (1) ──< mediciones (0..N)
pacientes (1) ──< citaciones (0..N) >── agenda_box (por id_box)
```

- **Enlace principal:** `id_paciente`.
- **Enlace de uso de box:** `citaciones.id_box` → `agenda_box.id_box`.
- `perfiles.json` entrega todo esto ya consolidado: un objeto por paciente con sus series anidadas (eventos, mediciones, citas).

## 8. Notas de uso

- **Recalcular prioridad a una fecha de corte:** usar solo registros con fecha ≤ corte, para simular lo que el hospital sabía ese día.
- **Ausencias con significado:** un paciente sin filas en `eventos_clinicos` o `mediciones` es alguien sin señales registradas mientras espera (estable o de ingreso reciente). No es un error.
- **Control de exclusión:** los pacientes con `fallecido = true` no deben recibir nuevas citaciones; toda su actividad es anterior a `fecha_defuncion`.
