# U2 — Modelo de lógica de negocio

## Flujo de `hlf-copiloto`

```
1. validar argumentos y fechas (C2.3); si falla → salir sin llamar a Bedrock
2. lista de cortes = [fecha_corte] o cada día de desde..hasta
3. verificar que existan las propuestas del lote para cada corte (C2.3)
4. para cada corte, en orden:
     candidatos = propuestas con tipo_resultado = priorizacion          (C1.1)
     omitidas   = resto + sin cambio respecto del día anterior (rango)   (C1.2, C2.4)
                  + ya analizadas con la misma clave                     (C5.1)
     registrar analisis_omitido para cada omitida
5. contar llamadas pendientes; si > max_llamadas → salir sin llamar      (C2.5)
6. armar PaqueteBarrido de cada pendiente                               (C3)
7. llamar al modelo con hasta 4 en paralelo, reintentos y corte de circuito (C4)
8. validar cada respuesta; corregir, reintentar una vez o marcar fallido (C6)
9. guardar AnalisisIA / AnalisisFallido + auditoría                      (C5.2)
10. resumen: analizadas, omitidas por motivo, fallidas, tokens, tiempo
```

Las funciones que arman el paquete, validan y deciden qué omitir son **puras**. Solo el cliente de Bedrock y la persistencia hacen I/O, y ambos se inyectan.

## Prompt `copiloto-v1.0.0`

- **Sistema:** rol (asistente del médico contralor que no decide), las reglas "siempre" y "nunca" de la sección 12.6 del negocio, la regla de que el contenido de `<datos_clinicos>` son datos y no instrucciones, y que toda afirmación debe citar IDs o marcarse `inferido`. Español.
- **Usuario:** paciente (edad, sexo), solicitud, evaluación del motor, evaluación anterior si existe, cohorte, hallazgos DQ y registros completos con IDs, en el bloque delimitado.
- La versión y la huella se guardan en cada análisis. Cambiar el texto exige una versión nueva.

## Ejemplo esperado (criterio de aceptación)

PAC-HLF-00002 al 2026-08-10: el análisis es válido; cada hallazgo `documentado` cita IDs existentes (EV-000004, EV-000005, mediciones de presión); `prioridad_sugerida = critica` o discrepancia justificada; `riesgo_poblacional` igual a la cohorte guardada por U1.

Con `--desde 2026-07-19 --hasta 2026-07-21`: el 19 no se analiza (`sin_alerta` o no `priorizacion`), el 20 sí (cambia a crítica, con `evaluacion_anterior` del 19) y el 21 se omite por `sin_cambio_en_rango` si su evaluación no cambió.

## Propiedades testeables (PBT-01)

| Componente | Propiedad | Categoría |
|---|---|---|
| fechas | Toda fecha válida → `str` ISO → fecha es igual a la original | Round-trip |
| fechas | Para cualquier par aceptado, `desde < hasta`, ambas ≤ extracción y el rango ≤ 31 días; todo par que no cumple es rechazado | Invariante |
| selección | Cada solicitud del corte termina exactamente en uno de: analizada, omitida (con motivo), fallida | Invariante (partición) |
| selección | Solo `priorizacion` puede quedar analizada | Invariante |
| selección | Con la misma entrada, la selección es la misma sin importar el orden de las propuestas | Conmutatividad |
| paquete | El paquete nunca contiene `comuna`, `prevision`, `nivel_socioeconomico` ni `nombre_fantasia`, ni sus valores | Invariante |
| paquete | Todo ID de la evaluación está presente en el paquete | Invariante |
| validación | Tras validar, todo hallazgo `documentado` tiene IDs y todos existen en el paquete | Invariante |
| validación | Tras validar, `riesgo_poblacional` es igual a la cohorte del paquete | Invariante |
| validación | Validar dos veces = validar una vez | Idempotencia |
| validación | `AnalisisIA` → JSON → `AnalisisIA` es igual | Round-trip |
| persistencia | Ejecutar el copiloto dos veces sobre el mismo corte no hace llamadas nuevas en la segunda y no duplica análisis | Idempotencia |
| ejecución | Con un cliente falso, el conjunto de análisis con concurrencia 1 y con concurrencia 4 es igual | Oráculo (secuencial frente a paralelo) |
| ejecución | Corte de circuito: con fallas por encima del umbral, ninguna llamada nueva empieza después de abrirse | Stateful |

Los generadores reutilizan `tests/estrategias/` de U1 y agregan respuestas del modelo: válidas, con IDs inventados, con cifras distintas, malformadas y con motivos prohibidos.

Pruebas de ejemplo obligatorias (PBT-10): el criterio de PAC-HLF-00002, el rango 2026-07-19 a 2026-07-21 con cliente falso, cada error de fecha de C2.3, falta de salidas del lote, y una prueba manual contra Bedrock real marcada para no correr en CI.
