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

## reglas-v0.2.0 (versión por defecto)

| | |
|---|---|
| Fecha | 2026-10-16 |
| Qué cambió | Nuevo insumo estándar `data/conocimiento/relaciones-clinicas-v0.1.0.yaml` (referenciado con `relaciones:`). R5.3: el factor `r` de un evento de otra especialidad sale del documento (par dirigido o su valor por defecto 0,5). Nueva R11: otras SIC abiertas del mismo paciente, `aporte = peso[prioridad_inicial_B] × rel(CIE-10_A, CIE-10_B)`, pesos alta 8 / media 5 / baja 3, sin decaimiento, tope 10, factor `otra_solicitud`; duplicadas (misma especialidad y CIE-10) sin aporte y alerta `sic_duplicada` en la más reciente. Confianza máxima `media` con el motivo "relaciones clínicas no validadas" cuando un factor usó un documento no validado. R5.10 deja escrito que los eventos anteriores al ingreso aportan (ya era así) |
| Por qué | Pedido del usuario (2026-10-16): una nueva SIC de un paciente ya en espera, de la misma especialidad y otra subespecialidad, debe considerar el impacto de la anterior y viceversa, con relaciones definidas por un documento del hospital. Base de negocio: secciones 5.1 (acumulación de consultas del mismo paciente), 5.3 (deduplicación) y 7 (cruce entre especialidades "según definición clínica vigente") |
| Sin cambios | `reglas-v0.1.0.yaml` queda idéntico (mismo blob de git). El resto de los parámetros de v0.2.0 es copia de v0.1.0 |
| Casos verificados | Los 6 casos de referencia corren con ambas versiones (`tests/ejemplos/test_casos_referencia.py`) y dan lo mismo. Lote real 2026-10-13: las 500 propuestas v0.2.0 son idénticas a las v0.1.0 salvo `version_reglas` (0 diferencias de puntaje, niveles, tipo, confianza ni huella). Escenario sintético `data/synthetic/escenario-multi-sic/`: I20 +4,5 (5 × 0,9) e I50 +2,7 (3 × 0,9) |
| Pendiente | El documento de relaciones es una **plantilla sintética no validada** (`estado: sintetico_no_validado`): pares y factores deben reemplazarse por el documento del HLF (tema T3) en una nueva versión del archivo |
