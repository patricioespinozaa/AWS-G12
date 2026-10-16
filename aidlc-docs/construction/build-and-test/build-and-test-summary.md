# Resumen de Build and Test (2026-10-16)

## Construcción

| | |
|---|---|
| Herramienta | uv 0.12.0, Python 3.12.7 |
| Estado | Correcto: `uv sync --locked`, `uv build` (wheel 109 KB, sdist 79 KB) |
| Comandos | `hlf-lote`, `hlf-copiloto`, `streamlit run app/bandeja.py` |

## Pruebas

| Tipo | Resultado |
|---|---|
| Lint y tipos | ruff limpio; mypy estricto sin errores (45 archivos) |
| Unitarias, propiedades e interfaz | **286 passed, 1 deselected** (la de Bedrock real) |
| Integración U1 → U2 → U3 | Correcta con el dataset real. Análisis guardados: 2026-07-19 a 07-21 (95) y 2026-10-13 (125 solicitudes). Recorrido de la bandeja confirmado a mano por el usuario, incluido el clic en la fila |
| Bedrock real | `pytest -m bedrock` pasó en U2. No se volvió a correr en esta etapa (consume tokens) |
| Rendimiento | Lote 2,9 s por corte; copiloto ~20 min por corte completo con Sonnet 5 |
| Seguridad | pip-audit limpio; controles de logs, validación, equidad y red verificados por pruebas |

## Cambios hechos en esta etapa

1. **Bandeja:** la decisión ya no viene preseleccionada en "Aceptar"; guardar sin elegir muestra un error y no guarda.
2. **Bandeja:** si la auditoría falla después de guardar la decisión, se avisa que la decisión **sí** quedó guardada y que no se vuelva a guardar (antes decía "No se pudo guardar" e invitaba a duplicarla).
3. **Copiloto, defecto encontrado en uso real:** dos ejecuciones simultáneas del 2026-10-13 (una del usuario, 05:21–05:40, y otra lanzada por el agente, 05:33–05:41) analizaron dos veces 44 solicitudes: 44 análisis repetidos en `analisis.jsonl` y ~50 llamadas extra (~0,4 M tokens de entrada, ~0,2 M de salida). Ahora `hlf-copiloto` toma un bloqueo exclusivo del sistema operativo sobre `salidas/.hlf-copiloto.lock`: una segunda ejecución termina con código 2 sin llamar a Bedrock. Se libera solo si el proceso muere. La bandeja ya mostraba un único análisis por solicitud, así que la demo no se ve afectada. Los repetidos no se borraron (archivo solo de agregado).

4 pruebas nuevas de bloqueo (con un segundo proceso real) y 2 de interfaz.

## Pendientes conocidos (no bloqueantes)

- Copiloto: Ctrl+C durante el reparto inicial de tareas no cancela las ya enviadas; reintentos de servicio tras Ctrl+C; sin prueba automática del segundo Ctrl+C.
- Bandeja: mensajes de validación con nombres técnicos de campo; dos validaciones pequeñas en la capa de presentación.
- U4 (despliegue AWS), U5 (box) y U6 (FHIR) fuera del MVP.
- Validación clínica de parámetros (T3) y región definitiva (T1).

## Estado general

- **Construcción:** correcta
- **Pruebas:** todas pasan
- **Listo para la demo local:** sí
