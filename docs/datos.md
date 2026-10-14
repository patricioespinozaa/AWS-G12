# Datos

El HLF entrega una **base acotada y anonimizada de usuarios de oftalmología**. Este documento describe los campos que anunció la presentación del desafío. Los nombres de columna, tipos y formatos reales están **por confirmar** cuando llegue la base: actualizar este archivo en ese momento.

> ⚠️ Los datos del hospital **no se suben al repositorio**. Ubicación local: `data/raw/` (ignorada por git).

## Fuentes y campos anunciados

### 1. Persona
| Campo | Notas |
|---|---|
| ID anonimizado | Clave para unir todas las tablas |
| Edad | |
| Sexo | |
| Comuna de origen | |
| Establecimiento de origen | CESFAM u otro establecimiento que deriva |
| Previsión | FONASA (tramo A–D), ISAPRE u otra |

### 2. Demanda y lista de espera
| Campo | Notas |
|---|---|
| Tipo | Consulta nueva o control |
| Fecha de derivación | Fecha de la interconsulta (SIC) |
| Fecha de ingreso a la lista | |
| Diagnóstico CIE-10 | Diagnóstico de sospecha de la derivación |
| Prioridad asignada | Prioridad manual actual; es la **línea base** contra la que se compara |
| Días de espera | Verificar si se calcula desde la derivación o desde el ingreso |
| Causal de egreso | Motivo de salida de la lista (atención, abandono, fallecimiento, etc.) |

### 3. Registro clínico electrónico (RCE)
| Campo | Notas |
|---|---|
| Diagnósticos | CIE-10 y/o texto |
| Atenciones y procedimientos | |
| Fármacos | Útil para detectar cambios de tratamiento (por ejemplo, inicio de insulina) |
| Indicaciones y plazos de control | **Texto libre**, por ejemplo "control en 3 meses". Hay que extraerlas para hacer visibles los controles |

### 4. Eventos durante la espera
| Evento | Por qué importa |
|---|---|
| Consultas de urgencia | Señal de descompensación |
| Hospitalizaciones | Señal de deterioro grave |
| Cambios terapéuticos | Indican progresión o mal control |
| Inasistencias | Riesgo de perder el seguimiento; no necesariamente sube la prioridad clínica |

### 5. Epidemiología y riesgo
| Campo | Notas |
|---|---|
| Comorbilidades | Diabetes, hipertensión (HTA), enfermedad renal crónica (ERC) |
| Carga de morbilidad | Posiblemente el riesgo ACG de la red; por confirmar |
| Variables oftalmológicas registradas | Por ejemplo agudeza visual o hallazgos de fondo de ojo; por confirmar |

## Modelo de datos sugerido

```
persona (id_paciente PK, edad, sexo, comuna, establecimiento_origen, prevision)
   │
   ├── solicitud_lista (id_solicitud PK, id_paciente FK, tipo [nueva|control],
   │                    fecha_derivacion, fecha_ingreso, cie10, prioridad_asignada,
   │                    causal_egreso, fecha_egreso)
   │
   ├── evento (id_evento PK, id_paciente FK, tipo [urgencia|hospitalizacion|
   │           cambio_tratamiento|inasistencia|...], fecha, cie10, texto)
   │
   ├── nota_clinica (id_nota PK, id_paciente FK, fecha, texto)
   │
   └── comorbilidad (id_paciente FK, cie10, fecha_diagnostico)

# Tablas generadas por el sistema
propuesta_prioridad (id_solicitud FK, fecha_calculo, puntaje, prioridad_propuesta,
                     explicacion JSON, version_modelo)
control_extraido   (id_nota FK, plazo_texto, plazo_dias, fecha_control_esperada,
                    fragmento_origen, en_lista BOOLEAN)
```

## Preguntas abiertas para el HLF

- [ ] ¿Formato de entrega (CSV, Excel, base de datos)?
- [ ] ¿Qué escala de prioridad usa hoy la lista? ¿Cuántos niveles?
- [ ] ¿Los días de espera se cuentan desde la derivación o desde el ingreso?
- [ ] ¿Las notas del RCE vienen como texto completo o como extractos?
- [ ] ¿Se incluye el riesgo ACG? ¿Con qué escala?
- [ ] ¿Qué variables oftalmológicas vienen (agudeza visual, fondo de ojo, presión intraocular)?
- [ ] ¿Hay una muestra con priorización experta para medir la concordancia (kappa)?

## Datos sintéticos

Mientras no estén los datos reales, y para tests y demos, generar trayectorias sintéticas en `data/synthetic/` con el mismo esquema. Incluir al menos el **caso de don Manuel** (ver `docs/contexto.md`) como caso de prueba.
