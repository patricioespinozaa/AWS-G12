# C6.5 nueva sobre los análisis guardados (solo lectura)

Fecha: 2026-10-16T02:27Z. Regla: C6.5 de la decisión E-1 = C (`copiloto/validacion.py`, `EQUIDAD_TERMINOS`).

## Cómo se hizo

- Se leyeron con `leer_analisis()` los `analisis.jsonl` de `salidas/analisis/fecha_corte=2026-07-19|20|21/version_reglas=reglas-v0.1.0/` (85 + 5 + 5 = **95 análisis**: 74 con `copiloto-v1.0.0`, 21 con `copiloto-v1.1.0`).
- Sobre cada `AnalisisIA` se corrieron `atributo_no_disponible()` (regla 1, revisando cada oración de cada campo para listar todas las menciones) y `frases_revision_equidad()` (regla 2). Script temporal fuera del repositorio, borrado después.
- No se modificó, borró ni reescribió ningún archivo de `salidas/`. SHA-256 de los cinco `.jsonl` antes y después, idénticos (`analisis.jsonl` 07-19 `58EC8D7A…`, 07-20 `D4EA6404…`, 07-21 `4D20AEAB…`; `fallidos.jsonl` 07-19 `161EA84D…`, 07-20 `7E5C005C…`).

- Re-ejecutado el 2026-10-16 con la regla 1 ampliada (comunal, previsional, socio-económico/socio económico, N.S.E.; hallazgos 1 y 2 de `review-equidad.md`): mismo resultado y mismos hashes.
- Re-ejecutado el 2026-10-16 con la normalización de la segunda pasada de `review-equidad.md` (NFKD, separadores y `_` como un espacio; raíces `\w*comuna\w*` y `\w*prevision\w*`; "Fondo Nacional de Salud"; "N S E"; GSE): mismo resultado (0 rechazados, 1 marcado) y mismos hashes.

## Resultado

| Regla | Análisis afectados |
|---|---|
| 1. Rechazo (`equidad_atributo_no_disponible`: comuna, previsión, NSE) | **0 de 95** |
| 2. Marca `revision_equidad` (inasistencias + verbo de bajada en la misma oración) | **1 de 95** (1 oración) |

No hay nada que decidir sobre rechazos: ningún análisis guardado menciona comuna, previsión ni nivel socioeconómico.

### Marcado por la regla 2

| fecha_corte | id_solicitud | version_prompt | Campo | Oración (datos sintéticos) |
|---|---|---|---|---|
| 2026-07-19 | IC-HLF-00349 | copiloto-v1.1.0 | `resumen` | "El paciente no asistió a una cita de Neurología el 2026-06-01 (CT-000184), lo que no se usa aquí como motivo de postergación." |

Es el tipo de frase que la regla 2 delega al médico: niega usar la inasistencia como motivo, pero junta "no asistió" con "postergación".

## Lo que significa para los datos guardados

- Los registros guardados no traen el campo `revision_equidad`, y por ser solo agregado no se reescriben. Al leerlos, `leer_analisis()` les asigna una lista vacía, así que IC-HLF-00349 **no** mostrará la advertencia en U3 aunque la regla nueva la marcaría.
- Como `ya_analizada` vale entre versiones de prompt, estos 95 análisis no se recalculan. Si el usuario quiere la marca en IC-HLF-00349, hay dos opciones: que U3 aplique `frases_revision_equidad()` al leer (sin llamadas al modelo), o volver a analizar con `--forzar` y el prompt v1.2.0 (hoy `--forzar` no filtra por solicitud: recalcula todas las pendientes del corte 2026-07-19, del orden de 85 llamadas o más). Queda a decisión del usuario; no se hizo ninguna de las dos.
