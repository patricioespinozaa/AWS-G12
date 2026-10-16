# U3 — Modelo de lógica

## Separación

```
src/hlf_priorizacion/bandeja/    # lógica pura y E/S de decisiones: testeable sin Streamlit
    datos.py        # cortes disponibles, carga de propuestas/análisis/DQ/cohortes, contexto reconstruido
    filas.py        # FilaBandeja, orden B2.2, filtros B2.3
    cambios.py      # CambioEntreCortes (B4)
    decisiones.py   # guardar/leer decisiones (B5), estado vigente
app/
    bandeja.py      # Streamlit: solo presenta y llama a bandeja/*
    config_demo.py  # lista fija de médicos ficticios
    .streamlit/config.toml
```

Toda la lógica de orden, filtros, comparación y decisiones vive en `bandeja/` y es pura o con E/S inyectable. `app/bandeja.py` no tiene reglas de negocio.

## Flujo de la sesión

```
1. elegir médico (lista fija)
2. elegir corte (los que tienen propuestas)
3. vista Bandeja → elegir solicitud → Detalle → decidir
4. vista "¿Qué cambió?" (corte A < corte B)
5. vista Cobertura
```

Las lecturas se cachean por `(corte, version_reglas)` con `st.cache_data`. Después de guardar una decisión se invalida solo la caché de decisiones.

## Recorrido de la demo (criterio de aceptación)

1. Corte 2026-07-19 → IC-HLF-00002 en baja, sin alerta.
2. "¿Qué cambió?" 07-19 → 07-20 → IC-HLF-00002 pasa de baja a crítica; registro nuevo EV-000004; bandera BR_EVENTO_GRAVE_30D.
3. Detalle 07-20 → factores con IDs, línea de tiempo con EV-000004 resaltado, análisis del copiloto (crítica, de acuerdo con el motor), nota de pre-consulta.
4. Decidir: aceptar con "Dra. Demo Uno" → queda en `decisiones.jsonl` y en la auditoría; la fila muestra "aceptada".
5. IC-HLF-00349 (07-19) muestra la advertencia de equidad antes del análisis.

## Propiedades testeables (PBT-01)

| Componente | Propiedad | Categoría |
|---|---|---|
| filas | El orden es total y determinista: ordenar una permutación da el mismo resultado | Conmutatividad |
| filas | Toda `crítica` aparece antes que cualquier no crítica | Invariante |
| filas | Filtrar no agrega filas y el resultado es subconjunto ordenado del original | Invariante |
| filas | Aplicar el mismo filtro dos veces = una vez | Idempotencia |
| cambios | Comparar un corte consigo mismo no da cambios | Invariante |
| cambios | Todo `registro_nuevo` tiene fecha en (corte_a, corte_b] | Invariante |
| cambios | Toda solicitud listada como cambio tiene nivel, banderas o pisos distintos entre cortes | Invariante |
| decisiones | `Decision` → JSONL → `Decision` es igual | Round-trip |
| decisiones | Guardar N decisiones deja N registros; ninguno anterior cambia | Invariante (solo agregar) |
| decisiones | La decisión vigente es la de mayor `timestamp` (empate por `id_decision`) | Invariante |
| decisiones | Una secuencia aleatoria de aceptar/ajustar/rechazar válidas e inválidas: solo las válidas se guardan, nunca se edita una existente | Stateful |

Pruebas de ejemplo (PBT-10): el recorrido de la demo con el dataset real (se salta si no hay datos), cada error del formulario de decisión, corte sin propuestas, solicitud sin análisis, huella distinta.

Pruebas de interfaz: `streamlit.testing.v1.AppTest` para cargar la app, elegir corte y solicitud y guardar una decisión. Verificación visual en el navegador con Chrome DevTools si está configurado; si no, capturas manuales.
