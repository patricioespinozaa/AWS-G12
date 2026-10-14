# Análisis exploratorio (EDA)

Resumen de los hallazgos sobre el dataset sintético del HLF (`docs/datos.md`). El detalle, con tablas y gráficos, está en los notebooks de `notebooks/`:

| Notebook | Contenido |
|---|---|
| `01_eda_lista_espera.ipynb` | Calidad de datos, demografía, composición de la lista, qué explica la prioridad inicial, tiempos de espera, fallecidos |
| `02_eda_evolucion_clinica.ipynb` | Eventos clínicos, mediciones, tendencias, si la prioridad inicial anticipa la evolución, líneas de tiempo de los casos de referencia |
| `03_eda_box_citaciones.ipynb` | Capacidad y ocupación de box, sobretiempo, inasistencias, cruce citas ↔ agenda, oferta vs. demanda por especialidad |

`notebooks/carga.py` carga las tablas con fechas parseadas, categorías ordenadas y `dias_espera` calculado. Para ejecutar: `jupyter notebook notebooks/` (requiere pandas, matplotlib, seaborn y scipy).

## Hallazgos principales

### 1. La foto congelada no sirve para priorizar
- **La prioridad inicial no se asocia con ninguna variable disponible:** especialidad, origen de derivación, edad, sexo, comuna, previsión ni nivel socioeconómico (todas p > 0,2). Ni siquiera los derivados desde urgencia u hospitalización tienen más prioridad alta.
- **No anticipa la evolución:** tienen al menos un evento grave el 16 % de los pacientes de prioridad alta, el 15 % de los de media y el 11 % de los de baja (χ² p = 0,46).
- **No ordena la atención:** entre los atendidos, los de prioridad alta esperaron más (mediana 306 días) que los de media (210). Entre los que siguen en espera, alta y baja llevan tiempos parecidos (301 vs. 335 días).

**Consecuencia:** el puntaje dinámico no puede apoyarse mucho en `prioridad_inicial`. Conviene tratarla como un punto de partida débil y dejar que los eventos y las mediciones muevan la propuesta.

### 2. Hay un grupo concreto que la lista no ve
**41 pacientes en espera (10 %) tienen prioridad baja o media y al menos un evento grave** (urgencia ESI 2 o descompensación grave, seguida de hospitalización). Cardiología (9) y Traumatología (7) concentran la mayor parte. Son el objetivo directo del reto y un buen número para la demo.

### 3. La tendencia de las mediciones es la mejor señal temprana
- Entre los pacientes con ≥ 3 mediciones de un tipo, **los que tienden fuerte al empeoramiento tienen evento grave en el 36 % de los casos, frente al 1 % de los que mejoran o están estables**.
- Una medición fuera de rango aislada en los 60 días previos anticipa poco: 33 % antes de un evento grave frente al 23 % de línea base.
- El primer evento grave llega con una mediana de 190 días tras el ingreso: hay margen para detectar el deterioro antes.

**Consecuencia:** el puntaje debe usar la **pendiente** de las mediciones (normalizada por el ancho del rango), no solo `fuera_de_rango`. Ver la sección 3 de `docs/enfoque.md`.

### 4. Artefactos del generador sintético: no sobreajustar
- Las secuencias de eventos son **deterministas**: triage ESI 2 → ingreso hospitalario, descompensación grave → ingreso UCI, descompensación moderada → estabilización. Toda hospitalización viene precedida de su urgencia, con una mediana de 16,5 días.
- Los 70 pacientes con eventos graves tienen **exactamente un episodio** (2 eventos graves cada uno).
- Cada subtipo de evento tiene siempre la misma severidad.
- `fuera_de_rango` coincide al 100 % con los rangos documentados.

Una regla como "si hay ESI 2, predecir hospitalización" funcionaría perfecto aquí y fallaría con datos reales. Las reglas deben tener sentido clínico, no solo ajustarse a este dataset.

### 5. Uso del box: el problema es la distribución, no la ocupación
- **La capacidad está mal repartida respecto de la demanda:**

| Especialidad | % de los pacientes en espera | % de la capacidad de box | Box | Demanda / capacidad |
|---|---|---|---|---|
| Traumatología | 21,8 | 4,9 | 1 | **4,45** |
| Cardiología | 20,5 | 5,2 | 1 | **3,94** |
| Salud Mental | 15,6 | 10,1 | 2 | 1,54 |
| Endocrinología | 15,9 | 19,6 | 4 | 0,81 |
| Gastroenterología | 7,3 | 10,3 | 2 | 0,71 |
| Neurología | 8,6 | 19,7 | 4 | 0,44 |
| Broncopulmonar | 10,3 | 30,1 | 6 | 0,34 |

  La lista es una muestra de 500 pacientes, así que se comparan proporciones y no cifras absolutas.
- **Ocupación pareja, cerca de 74 %,** en todas las especialidades, box y días de la semana. Hay cupos libres sobre todo donde sobra capacidad.
- **El sobretiempo no depende de la ocupación** (ρ = 0,02). La atención real dura más que el cupo teórico (mediana 36 min frente a 30 min), lo que apunta a la duración de la consulta como causa.
- **No-show de 23 %** (60 de 257 citas). Ninguna variable del paciente lo predice (todas p > 0,4), y el 95 % de los pacientes tiene una sola cita: no hay historial para un modelo individual de no-show. Una estrategia por especialidad o bloque (confirmación, sobreagenda) es más defendible.

### 6. Calidad de datos
- Sin duplicados; los nulos son los esperados.
- **`citaciones` y `agenda_box` casi no cruzan:** solo 18 de 257 citas (7 %) caen en un bloque del mismo box, día y especialidad. Analizarlas por separado.
- 76 citas con `asistio` son de pacientes que siguen `en_espera`.

## Implicancias para el prototipo

1. Priorizar las **señales dinámicas** (eventos graves recientes y tendencia de mediciones) por sobre `prioridad_inicial`.
2. Usar a los **41 pacientes "invisibles"** como caso central de la demo, junto con los 6 de `docs/casos-ejemplo.md`.
3. Para el eje box, proponer una **redistribución de box entre especialidades** (Broncopulmonar y Neurología → Traumatología y Cardiología) antes que un modelo de no-show.
4. Validar con fechas de corte y desconfiar de cualquier regla que solo funcione por las secuencias deterministas del generador.
