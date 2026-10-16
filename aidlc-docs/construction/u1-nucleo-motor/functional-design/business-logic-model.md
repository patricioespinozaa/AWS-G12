# U1 — Modelo de lógica de negocio

## Flujo del lote (`hlf-lote --fecha-corte AAAA-MM-DD`)

```
1. cargar perfiles.json
2. para cada perfil: validar_perfil()        → válido | cuarentena (R1)
3. ingesta: normalizar, ID de medición, especialidad del evento
4. para cada solicitud válida:
     ctx = contexto_a_fecha(solicitud, fecha_corte)      (R2)
     dq  = auditar(ctx)                                    (R4)
     ev  = evaluar(ctx, dq, params)                        (R3, R5–R8)
5. cohortes para las solicitudes con tipo_resultado = priorizacion  (R9)
6. escribir salidas/propuestas/fecha_corte=…/version=…/ (idempotente)
7. escribir hallazgos DQ, cuarentena y eventos de auditoría (JSONL, solo agregar)
8. verificar cobertura (R1.3) y reportar resumen
```

`evaluar()` es pura: no lee archivos, no consulta el reloj y no usa aleatoriedad. Todo lo que necesita viene en sus argumentos.

## Algoritmo de `evaluar(ctx, dq, params)`

```
si exclusión (R3)                 → Evaluacion(tipo=exclusion, …)
registros = quitar_descartados(ctx, dq)
factores  = [base] + eventos + aceleración + mediciones(tope 20) + espera
puntaje   = acotar(Σ aportes)
nivel     = nivel_por_umbral(puntaje)
nivel     = limitar_bajada(nivel, prioridad_inicial, evidencia_mejoria)
nivel     = aplicar_pisos(nivel); nivel = aplicar_banderas(nivel)
alertas   = alertas_gestion(ctx)
tipo, confianza = clasificar(…)
```

## Verificación en seco con los 6 casos (parámetros `reglas-v0.1.0`)

Cálculo a mano con los datos reales del dataset. Sirve para anticipar si hace falta calibrar (R10). Hay redondeos; los valores exactos los dará el código.

| Caso | Corte | Cálculo aproximado | Nivel | Criterio | ¿Pasa? |
|---|---|---|---|---|---|
| PAC-HLF-00002 | 2026-07-19 | 20 base + PAS 167 (zona 5,7 + brusco 4 + tendencia 4) + espera 4,1 ≈ 37,8 | baja | baja o media | Sí |
| PAC-HLF-00002 | 2026-07-20 | 37,8 + ESI 2 (16) ≈ 53,8 → media; bandera evento grave 30 días | **crítica** | ≥ alta | Sí, **solo por la bandera** |
| PAC-HLF-00002 | 2026-10-13 | 20 + ESI 2 (8,4) + hosp. (10,7) + aceleración 5 + PAS 13,7 + espera 8,8 ≈ 66,6 | alta | ≥ alta | Sí |
| PAC-HLF-00001 | 2026-10-13 | 60 + eventos 6,8 + PHQ-9 19 (zona 10 + brusco 4 + tendencia 4) + espera 10 ≈ 94,8; piso PHQ-9 ≥ 15 | alta | ≥ alta, explica tendencia | Sí |
| PAC-HLF-00028 | 2026-10-13 | 20 − 2,8 − 3,4 ≈ 13,8 (PHQ-9 en 0, sin contradicción) | baja | puede bajar como máximo un nivel | Sí (ya está en el nivel más bajo; baja el puntaje) |
| PAC-HLF-00020 | 2026-10-13 | 40 + espera 10 (tope) = 50; mediciones en rango | media | puntaje igual sin citas; alerta `citas_fallidas` (2 `no_asistio` + 1 `reprogramo`) | Sí |
| PAC-HLF-00032 | 2026-10-13 | `atendido` en la extracción | exclusión | exclusión | Sí |
| PAC-HLF-00032 | 2026-06-29 | 20 + espera 10 = 30; saturación en rango | baja | no se dispara por espera | Sí |
| PAC-HLF-00009 | 2026-09-07 | 20 + descomp. grave 16,8 + UCI 23,4 + aceleración 5 + mediciones ≈ 15 ≈ 80; bandera evento grave | crítica | se evalúa antes del fallecimiento | Sí |
| PAC-HLF-00009 | 2026-09-08 | `fecha_defuncion ≤ corte` | exclusión | exclusión | Sí |

**Hallazgo:** en PAC-HLF-00002 el 20 de julio, el puntaje solo llega a **media** (≈ 54). Lo que la sube es la bandera roja por urgencia grave. A los 30 días la bandera vence, pero la hospitalización del 6 de agosto la renueva hasta el 5 de septiembre. Desde ahí el puntaje propio ya supera 60 (≈ 71). El criterio de `casos-ejemplo.md` se cumple en todo el recorrido, aunque al principio depende de la bandera y no del puntaje. Conviene contarlo así en la demo.

Con este resultado no se prevé calibrar para el MVP. Si el código da otra cosa, aplica R10.

## Propiedades testeables (PBT-01)

| Componente | Propiedad | Categoría |
|---|---|---|
| contrato | `PerfilValido` → JSON → `PerfilValido` es igual al original | Round-trip |
| contrato | Normalizar el CIE-10 dos veces = una vez | Idempotencia |
| ingesta | `id_medicion` no cambia si se reordenan las filas o los campos | Conmutatividad |
| ingesta | Deduplicar mediciones dos veces = una vez | Idempotencia |
| repositorio | Agregar registros con fecha > corte no cambia `ContextoPaciente` (salvo su huella de entrada) ni la `Evaluacion` | Invariante metamórfica |
| repositorio | IC95 de Wilson contiene `p` y está en [0, 1]; coincide con `statsmodels` | Invariante + oráculo |
| calidad | Agregar mediciones fuera de plausibilidad no cambia el puntaje | Invariante metamórfica |
| motor | Puntaje ∈ [0, 100] | Invariante |
| motor | Bandera ⇒ `crítica`; piso ⇒ ≥ `alta` | Invariante |
| motor | `nivel_propuesto` ≥ `prioridad_inicial` − 1 nivel; sin evidencia de mejoría, ≥ `prioridad_inicial` | Invariante |
| motor | Sin eventos ni mediciones, el nivel no baja de `prioridad_inicial` | Invariante |
| motor | Agregar citas de cualquier estado no cambia puntaje ni nivel | Invariante metamórfica |
| motor | A igual contexto, más días de espera nunca bajan el puntaje | Invariante (monotonía) |
| motor | `evaluar` dos veces con la misma entrada da exactamente lo mismo | Idempotencia |
| motor | Todo factor con aporte ≠ 0 cita al menos un ID presente en el contexto | Invariante |
| motor | `prioridad_inicial` de la salida = la de la entrada; `estado_revision = pendiente_revision_medica` | Invariante |
| motor | Implementación optimizada = implementación de referencia simple | Oráculo |
| persistencia | Escribir la misma propuesta dos veces deja un solo registro | Idempotencia |

La equidad (comuna, previsión, NSE) se garantiza por estructura, porque esos campos no existen en el contexto. Igual se prueba: variar esos campos en `PerfilCrudo` no cambia la `Evaluacion`.

Componentes sin propiedades PBT propias: la CLI del lote (se cubre con una prueba de integración de ejemplo).
