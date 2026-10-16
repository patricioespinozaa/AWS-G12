# Rendimiento

No hay pruebas de carga: el MVP es un lote local y una interfaz de un solo usuario. Se registran mediciones reales como referencia.

| Requisito | Objetivo | Medido (dataset de 500 pacientes) |
|---|---|---|
| RNF-Rendimiento: el lote reevalúa el 100 % de la lista dentro de la ventana que asegura ≤ 72 h | Minutos | `hlf-lote` 2,9 s por corte |
| Copiloto, un corte completo (125 `priorizacion`, Sonnet 5, concurrencia 4) | Terminar antes de la mañana siguiente | ~20 min; ~30–40 s por análisis; ~7–9 k tokens de entrada y ~3–4 k de salida por análisis |
| Copiloto con Haiku 4.5 | Alternativa más rápida | ~5 s por llamada (prueba puntual) |
| Bandeja | Interactiva | Carga de un corte en caché por sesión; sin medición formal |

Cómo medir: `Measure-Command { uv run hlf-lote --fecha-corte 2026-10-13 }`; el copiloto imprime tiempo, llamadas y tokens al terminar.

Para el HLF completo (~26.000 solicitudes) o la red, el diseño de escalado está en la sección 12 de `docs/contexto-tecnico.md` (Glue Spark, Distributed Map, Bedrock Batch Inference). No se probó.
