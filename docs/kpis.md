# KPIs y métricas de éxito

Métricas definidas por el HLF para evaluar la solución.

| KPI | Definición | Línea base | Meta |
|---|---|---|---|
| ⭐ **Tiempo a reevaluación** (KPI estrella) | Tiempo entre un evento clínico relevante (urgencia, hospitalización, cambio de tratamiento) y la reevaluación de la prioridad | Sin medir; hoy no hay detección sistemática | **< 72 h** |
| **Concordancia** | Acuerdo entre la prioridad propuesta y la priorización clínica experta, medido con kappa | Sin medir | **κ ≥ 0,70** |
| **Controles visibles** | % de indicaciones de control en texto libre que quedan en la lista | Sin medir | **≥ 90 %** |
| **Cobertura** | % de la lista revisada con un criterio común | Parcial | **100 %** |

## Cómo calcularlas

### Tiempo a reevaluación
```
para cada evento relevante e:
    t_reevaluacion(e) = fecha_calculo de la primera propuesta_prioridad posterior a e − fecha(e)
KPI = % de eventos con t_reevaluacion < 72 h   (reportar también la mediana)
```
En el prototipo, la reevaluación debería dispararse al ingresar el evento, así que el tiempo depende sobre todo de la frecuencia con que se cargan los datos.

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

## Métricas adicionales sugeridas

- **Caso de don Manuel:** su prioridad debe subir tras la primera urgencia por hiperglicemia.
- **Equidad:** comparar la distribución de cambios de prioridad por edad, sexo, comuna y previsión, para no penalizar sistemáticamente a ningún grupo.
- **Explicabilidad:** % de propuestas con al menos un factor explicativo trazable a un dato de origen. Meta: 100 %.
