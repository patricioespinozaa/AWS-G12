# Bitácora de parámetros del motor (R10)

Cada versión de `src/hlf_priorizacion/motor/reglas/reglas-vX.Y.Z.yaml` se anota aquí: qué cambió, por qué y qué casos de `docs/casos-ejemplo.md` se volvieron a verificar. Todos los valores son referenciales y deben validarse con los clínicos del HLF (tema T3 de `docs/contexto-tecnico.md`).

## reglas-v0.1.0 (versión inicial)

| | |
|---|---|
| Fecha | 2026-10-15 |
| Origen | Secciones 6 y 7 de `docs/contexto-tecnico.md`; reglas R5–R8 de `functional-design/business-rules.md` |
| Agregado en el diseño | Umbral de magnitud de la tendencia (R5.7): pendiente ≥ 0,1 × ancho del rango cada 30 días |
| Interpretaciones fijadas al codificar | Ventanas "últimos N días" inclusivas (0 ≤ Δt ≤ N) para banderas, pisos, evidencia de mejoría y confianza; la aceleración usa los intervalos semiabiertos de R5.4. En mediciones bidireccionales, la dirección dañina es el lado del punto medio del rango donde está el último valor. "Zona de riesgo" para la contradicción = fuera del rango normal en la dirección dañina. La evidencia de mejoría (R6.5) exige al menos una medición en los últimos 90 días (la falta de datos no baja la prioridad) |
| Casos verificados | Los 6 casos (10 filas de la tabla "Verificación en seco"); resultados en `code/resumen.md` |
| Cambios de calibración | Ninguno: todos los casos cumplen su criterio con esta versión |
