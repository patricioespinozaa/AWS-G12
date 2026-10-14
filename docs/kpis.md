# KPIs y métricas de éxito

Métricas definidas por el HLF para evaluar la solución.

| KPI | Definición | Línea base | Meta |
|---|---|---|---|
| ⭐ **Tiempo a reevaluación** (KPI estrella) | Tiempo entre un evento clínico relevante (urgencia, hospitalización, cambio de tratamiento) y la reevaluación de la prioridad | Sin medir; hoy no hay detección sistemática | **< 72 h** |
| **Concordancia** | Acuerdo entre la prioridad propuesta y la priorización clínica experta, medido con kappa | Sin medir | **κ ≥ 0,70** |
| **Controles visibles** | % de indicaciones de control en texto libre que quedan en la lista | Sin medir | **≥ 90 %** |
| **Cobertura** | % de la lista revisada con un criterio común | Parcial | **100 %** |

### Qué se puede medir con el dataset entregado

| KPI | ¿Medible? | Cómo |
|---|---|---|
| Tiempo a reevaluación | Sí, simulado | Recalcular a cada fecha de evento (fecha de corte) |
| Concordancia (kappa) | **No directamente** | El dataset no trae priorización experta. Hay que pedir una muestra al HLF o etiquetarla con su equipo clínico |
| Controles visibles | **No** | No hay texto libre ni distinción entre consulta nueva y control |
| Cobertura | Sí | Sobre las solicitudes `en_espera` |

## Cómo calcularlas

### Tiempo a reevaluación
```
para cada evento relevante e:
    t_reevaluacion(e) = fecha_calculo de la primera propuesta_prioridad posterior a e − fecha(e)
KPI = % de eventos con t_reevaluacion < 72 h   (reportar también la mediana)
```
En el prototipo, la reevaluación debería dispararse al ingresar el evento, así que el tiempo depende sobre todo de la frecuencia con que se cargan los datos.

En el dataset, un "evento relevante" es una fila de `eventos_clinicos` con severidad moderada o grave. Como no hay hora, medir en días: la reevaluación cuenta como oportuna si la propuesta con fecha de corte igual a la del evento (o hasta 3 días después) ya lo incorpora.

### Concordancia (kappa)
- Usar kappa de Cohen **ponderado** (lineal o cuadrático), porque la prioridad es ordinal.
- Hace falta una muestra con priorización experta. Si el HLF no la entrega, armarla con su equipo clínico.
- `sklearn.metrics.cohen_kappa_score(y_experto, y_propuesto, weights="quadratic")`

### Controles visibles
```
controles_visibles = indicaciones de control extraídas que tienen una solicitud de control en la lista
                     / total de indicaciones de control extraídas del texto libre
```
Validar la extracción con una muestra revisada a mano: reportar precisión y exhaustividad.

### Cobertura
```
cobertura = solicitudes activas con propuesta_prioridad vigente / total de solicitudes activas
```
Solicitudes activas: `estado = en_espera` y paciente no fallecido.

## Uso del recurso box

Métricas del segundo eje del reto, calculadas desde `agenda_box` y `citaciones`:

| Métrica | Cálculo |
|---|---|
| Ocupación | `Σ cupos_usados / Σ capacidad_cupos` por especialidad y semana (global ≈ 74 %) |
| Tasa de inasistencia | `no_asistio / citas ofrecidas` (60 de 257 en el dataset) |
| Cupos perdidos | Citas `no_asistio` + `cancelo` |
| Sobretiempo | Media y percentil 90 de `minutos_sobretiempo` por box y especialidad |
| Duración real | Media de `minutos_atencion_real` frente al cupo teórico (300 min / capacidad) |
| Alta prioridad sin cita | Pacientes con prioridad propuesta alta y sin cita futura, por especialidad, frente a los cupos libres de esa especialidad |

## Validación sin respuesta de referencia

Mientras no haya priorización experta:
- **Casos de ejemplo:** los 6 pacientes de `docs/casos-ejemplo.md` deben comportarse como se espera en las fechas de corte indicadas.
- **Coherencia:** los pacientes con hospitalización o urgencia grave reciente deben quedar, en su mayoría, en alta.
- **Estabilidad:** un paciente sin eventos ni mediciones nuevas no debería cambiar de prioridad entre dos fechas de corte cercanas.
- **Sensibilidad:** reportar cuántos pacientes cambian de nivel al variar los pesos ±20 %.

## Métricas adicionales sugeridas

- **Caso de don Manuel:** su prioridad debe subir tras la primera urgencia por hiperglicemia. En el dataset, su equivalente es PAC-HLF-00002: debe pasar de baja a alta tras la urgencia ESI 2 del 2026-07-20.
- **Equidad:** comparar la distribución de cambios de prioridad por edad, sexo, comuna y previsión, para no penalizar sistemáticamente a ningún grupo.
- **Explicabilidad:** % de propuestas con al menos un factor explicativo trazable a un dato de origen. Meta: 100 %.
