# Revisión U1: núcleo de datos y motor de reglas (`hlf_priorizacion`)

U1 entrega el pipeline local completo: contrato Pydantic estricto con cuarentena, ingesta y conciliación, repositorio de contexto a fecha de corte sin campos de equidad, auditoría de calidad, motor `evaluar()` puro parametrizado por `reglas-v0.1.0.yaml`, persistencia idempotente en Parquet/JSONL y la CLI `hlf-lote`. Corrí yo mismo ruff, mypy, pytest (perfil `ci`), pip-audit y los tres cortes sobre el dataset real dos veces. Todo pasa, la cobertura es 100 % en los tres cortes, los niveles de los 6 casos de referencia coinciden con la tabla a mano y la re-ejecución es byte a byte idéntica.

Watch for: los mensajes de error del lote registran rutas absolutas del sistema de archivos (confirmed, no bloqueante); la ruta de excepción por solicitud dentro del lote no tiene prueba que la fuerce (confirmed, no bloqueante); dos puntajes se desvían del cálculo a mano sin cambiar nivel, uno por la lectura literal de R5.6 sobre un valor en rango (confirmed, documentado, pendiente de validación clínica T3).

**Verdict**: APPROVED

## High-level view

El plan tiene 41 casillas y todas están en `- [x]`; no queda ninguna `- [ ]`. Las cuatro herramientas de verificación terminan con código 0: ruff sin hallazgos, mypy estricto sin errores en 27 archivos, 107 pruebas aprobadas en 14,5 s con Hypothesis en perfil `ci` (`derandomize=True`, fase `shrink` activa) y pip-audit sin vulnerabilidades conocidas.

Las restricciones duras se cumplen en el código. `ContextoPaciente` no tiene `comuna`, `prevision`, `nivel_socioeconomico` ni `nombre_fantasia`; esos campos solo existen en el esquema de entrada y `nombre_fantasia` se descarta al validar. `evaluar.py` no importa nada de I/O, reloj ni aleatoriedad. `Evaluacion.estado_revision` es un `Literal` único con valor por defecto `pendiente_revision_medica`, y en las 1436 propuestas generadas no hay otro valor. `Factor`, `Bandera`, `Piso` y `AlertaGestion` exigen `ids_registro` con `min_length=1`, y una propiedad verifica que los IDs citados están en `ctx.ids_presentes()`. Las dependencias están fijadas con `==` y `uv.lock` no está ignorado por git.

El lote sobre el dataset real reproduce exactamente lo que dice `resumen.md`: 500/500, 468/468 y 468/468 de cobertura, mismas exclusiones, priorizaciones y cambios de nivel. La segunda pasada informa "Propuestas nuevas: 0 · ya existentes: N · conflictos: 0" y los 12 archivos de salida (sin auditoría) tienen el mismo SHA-256. Las pruebas de casos de referencia leen el dataset real (12 aprobadas) y se saltan con mensaje claro cuando `HLF_DATOS` apunta a una ruta inexistente (12 saltadas).

La configuración inválida detiene el lote con código 2 (fecha inexistente, corte posterior a la extracción, YAML inválido, `--salidas` dentro de los datos), y un perfil en cuarentena no lo detiene. Lo que queda es menor: rutas absolutas en mensajes de log y falta de una prueba que fuerce una excepción de evaluación a mitad de lote.

<details>
<summary>Issues (4)</summary>

1. **Rutas absolutas en logs de error** — `lote.py:385` interpola el mensaje de la excepción y `carga.py:36-44` / `parametros.py:213-217` incluyen la ruta completa (`C:\Users\<usuario>\...`). Usar `ruta.name` o una ruta relativa a `--datos` en esos mensajes. No bloqueante.
2. **Ruta de excepción por solicitud sin prueba** — los `except Exception` de `lote.py:166` (normalización), `lote.py:184` (evaluación) y `lote.py:212` (cohorte) no se ejercitan; solo se prueba la cuarentena. Agregar una prueba en `tests/ejemplos/test_lote.py` que haga fallar `evaluar` para una solicitud (monkeypatch) y verifique `errores["evaluacion"] == 1`, `sin_cubrir`, código de salida 1 y que el resto se evalúa. No bloqueante.
3. **Empeoramiento brusco sobre valor en rango** — PAC-HLF-00032 al 2026-06-29 suma +4 por SatO₂ 97 % frente a mediana 98,5 % (34,00 frente a ≈ 30 a mano). Es la lectura literal de R5.6; llevarlo a la validación clínica T3 y, si se decide limitarlo a valores fuera de rango, registrar el cambio en `bitacora-parametros.md`. No bloqueante.
4. **Confianza sin condición de cohorte n ≥ 30** — desviación documentada en `resumen.md` porque `evaluar()` no recibe la cohorte. Reflejar la decisión en `business-rules.md` (regla de confianza) para que diseño y código no diverjan. No bloqueante.

</details>

<details>
<summary>Details</summary>

### Completitud del plan

`Select-String -Pattern '- \[ \]'` sobre `u1-nucleo-motor-code-generation-plan.md` no devolvió líneas; `- \[x\]` devolvió 41. Pasa.

### Verificación independiente

```
uv run ruff check        -> All checks passed!                              (exit 0)
uv run mypy src          -> Success: no issues found in 27 source files     (exit 0)
uv run pytest -q         -> 107 passed in 14.47s                            (exit 0)
uv run pip-audit         -> No known vulnerabilities found                  (exit 0)
                            (omite solo hlf-priorizacion 0.1.0, paquete local)
```

`tests/conftest.py:18-35` registra `ci` con `derandomize=True` y fases que incluyen `Phase.shrink`, y lo carga por defecto. Las estrategias están en `tests/estrategias/tuberia.py`; ejemplos en `tests/ejemplos/` y propiedades en `tests/propiedades/`. `statsmodels` aparece solo en `tests/propiedades/test_prop_repositorio_calidad.py:11` como oráculo de Wilson y no en `src/`. Pasa.

### Lote sobre el dataset real e idempotencia

Ejecuté los tres cortes con `--salidas %TEMP%\hlf-review-u1` (carpeta vacía), los hashes de salida, y una segunda pasada:

```
2026-10-13  evaluadas 500  en_espera 409/409  cobertura 100.0 % (500/500)
            exclusiones EX_ATENDIDO 76, EX_FALLECIDO 15  priorizacion 125  sube 123 / baja 2  errores 0  exit 0
2026-07-19  evaluadas 468 (32 no vigentes)  en_espera 385/385  cobertura 100.0 % (468/468)
            EX_ATENDIDO_INFERIDO 29, EX_FALLECIDO 10  priorizacion 85  errores 0  exit 0
2026-07-20  evaluadas 468  en_espera 385/385  cobertura 100.0 % (468/468)
            EX_ATENDIDO_INFERIDO 29, EX_FALLECIDO 10  priorizacion 86  errores 0  exit 0
pasada 2:   "Propuestas nuevas: 0 · ya existentes: 500/468/468 · conflictos: 0"
hashes:     12 archivos vs 12, Compare-Object sin diferencias
```

Coincide con la tabla de `resumen.md`. Pasa.

### Casos de referencia

Extraídos del Parquet de la CLI para sus tres cortes, y con `evaluar()` directo sobre el dataset real para 2026-06-29, 2026-09-07 y 2026-09-08. Las 12 pruebas de `test_casos_referencia.py` aprueban:

```
Caso / corte              Mano          Motor (observado)                          Criterio          Nivel coincide
00002 2026-07-19          ≈37,8 baja    37,77 baja, sin bandera                     baja o media      sí
00002 2026-07-20          ≈53,8 media   58,82 media -> critica (BR_EVENTO_GRAVE_30D, EV-000004)  >= alta  sí
00002 2026-10-13          ≈66,6 alta    66,51 alta, sin bandera                     >= alta           sí
00001 2026-10-13          ≈94,8 alta    94,57 alta, PISO_PHQ9, tendencia PHQ-9      >= alta           sí
00028 2026-10-13          ≈13,8 baja    13,82 baja                                  baja máx. 1 nivel sí
00020 2026-10-13          50 media      50,00 media, alerta citas_fallidas (3)      puntaje igual     sí
00032 2026-10-13          exclusión     EX_ATENDIDO                                 exclusión         sí
00032 2026-06-29          ≈30 baja      34,00 baja, sin_alerta, sin bandera/piso    no se dispara     sí
00009 2026-09-07          ≈80 crítica   80,38 alta -> critica (BR_EVENTO_GRAVE_30D) se evalúa         sí
00009 2026-09-08          exclusión     EX_FALLECIDO                                exclusión         sí
```

Todos los niveles y criterios coinciden. Las dos diferencias de puntaje están explicadas en `resumen.md`: al 2026-07-20 la tabla a mano omitió la aceleración (+5), y en 00032 al 2026-06-29 la regla de empeoramiento brusco (R5.6) suma +4 aunque la SatO₂ sigue en rango (Issue 3). Con `HLF_DATOS=C:\no-existe` las 12 pruebas se saltan con "Dataset real no disponible en C:\no-existe…". Pasa.

### Restricciones duras

`ContextoPaciente` (`modelos.py:99-127`) contiene IDs, fechas, edad, sexo, solicitud y registros; ningún campo de equidad. La propiedad `test_equidad_campos_socioeconomicos_no_cambian_la_evaluacion` lo cubre de forma metamórfica. `evaluar.py:11-47` importa solo `math`, `statistics`, `dataclasses`, `date` y módulos internos; `test_evaluar_es_idempotente` y `test_motor_coincide_con_la_referencia` (oráculo independiente) refuerzan la pureza. `prioridad_inicial` se copia de `ctx.solicitud` (`evaluar.py:489,531`) y la propiedad en `test_prop_motor.py:26` verifica que no cambia. Todos los modelos usan `strict=True, frozen=True, extra="forbid"` (`modelos.py:51`).

El logging (`logs.py`) emite `timestamp`, `nivel`, `id_ejecucion` y `mensaje` (las claves en español siguen SECURITY-03 del plan) y filtra campos por lista permitida de IDs, conteos y códigos; las excepciones se registran por tipo. Observé en la salida real que los mensajes de `ErrorEntrada`/`ErrorParametros` incluyen la ruta absoluta, p. ej. `C:\Users\LoG\AppData\Local\Temp\hlf-bad-reglas.yaml no es YAML válido` (Issue 1). No son datos clínicos, pero sí exponen el nombre de usuario del equipo.

Fail-closed observado: `--fecha-corte 2026-13-40` → argparse "fecha inexistente", exit 2; `2026-12-01` → "no puede ser posterior a la fecha de extracción", exit 2; YAML inválido → `ErrorParametros`, exit 2; `--salidas` dentro de los datos → exit 2. Un perfil inválido va a cuarentena y el lote sigue (`test_lote_extremo_a_extremo_idempotente`, 1 en cuarentena, 2 evaluadas, cobertura completa). La captura de excepciones por solicitud existe en `lote.py:166`, `:184` y `:212` y cuenta el error, lo audita y marca la solicitud como sin cubrir, lo que lleva a exit 1 por cobertura incompleta. Ninguna prueba la ejercita (Issue 2).

</details>

<details>
<summary>Archivos revisados</summary>

`pyproject.toml`, `uv.lock` (versiones exactas, lock no ignorado); `src/hlf_priorizacion/modelos.py` (contratos y `ContextoPaciente`); `motor/evaluar.py` (función pura); `lote.py` (CLI, manejo de errores por perfil y fail-closed); `logs.py` (JSON con lista permitida); `ingesta/carga.py`, `motor/parametros.py` (mensajes de error); `tests/conftest.py` (perfiles Hypothesis); `tests/ejemplos/test_casos_referencia.py`, `test_lote.py`; `tests/propiedades/*.py`. Diff completo: `git status` muestra `src/`, `tests/`, `pyproject.toml`, `uv.lock` como nuevos.

</details>
