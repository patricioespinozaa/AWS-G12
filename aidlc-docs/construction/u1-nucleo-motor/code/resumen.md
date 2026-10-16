# U1 — Resumen de la generación de código

Plan: `aidlc-docs/construction/plans/u1-nucleo-motor-code-generation-plan.md` (13 pasos, todos marcados). Diseño: `functional-design/` (R1–R10). Parámetros: `reglas-v0.1.0`, sin calibración (ver `../bitacora-parametros.md`).

## Archivos creados

| Ruta | Contenido |
|---|---|
| `pyproject.toml`, `uv.lock` | Paquete `hlf_priorizacion` (src layout, `uv_build`), script `hlf-lote`, dependencias con versión exacta, configuración de ruff, mypy estricto y pytest |
| `src/hlf_priorizacion/modelos.py` | Contratos compartidos: registros del contexto, `ContextoPaciente`, `HallazgoDQ`, `ResultadoCohorte`, `Factor`, `Bandera`, `Piso`, `Contradiccion`, `AlertaGestion`, `MarcaInferido`, `Evaluacion`, `RegistroCitado`; para U2/U3: `AnalisisIA` (`analisis-v1`) y `Decision` |
| `src/hlf_priorizacion/contrato/` | `catalogos.py` (enumerados y combinaciones), `esquema.py` (`PerfilCrudo`, `PerfilValido`), `validacion.py` (`validar_perfil`), `esquema_json.py` + `contrato-v1.0.0.schema.json` (JSON Schema 2020-12) |
| `src/hlf_priorizacion/ingesta/` | `carga.py` (JSON/CSV con errores controlados), `normalizacion.py` (CIE-10, `id_medicion`, especialidad del evento, deduplicación, orden), `conciliacion.py` (perfil ↔ CSV) |
| `src/hlf_priorizacion/repositorio/` | `contexto.py` (`contexto_a_fecha`, `linea_tiempo`, huella, `Repositorio`), `cohortes.py` (R9 + Wilson) |
| `src/hlf_priorizacion/calidad/` | `reglas.py` (plausibilidad 7.1), `auditoria.py` (`auditar`) |
| `src/hlf_priorizacion/motor/` | `reglas/reglas-v0.1.0.yaml`, `parametros.py` (carga fail-closed), `evaluar.py` (función pura), `referencia.py` (oráculo de pruebas) |
| `src/hlf_priorizacion/persistencia/salidas.py` | Parquet idempotente de propuestas, JSONL idempotente de DQ/cuarentena/cohortes, resumen |
| `src/hlf_priorizacion/auditoria/registro.py` | JSONL de solo agregado con ULID |
| `src/hlf_priorizacion/logs.py`, `lote.py` | Logging JSON con lista permitida de campos; CLI `hlf-lote` |
| `tests/ejemplos/` | 87 pruebas de ejemplo (contrato, ingesta, repositorio, calidad, motor, persistencia, lote, modelos y los 6 casos de referencia) |
| `tests/propiedades/`, `tests/estrategias/` | 20 propiedades Hypothesis y los generadores de dominio compartidos |
| `tests/fixtures/evaluacion_ejemplo.json` | Salida real del motor para PAC-HLF-00002 al 2026-08-10 (formato 6.8) |
| `aidlc-docs/construction/u1-nucleo-motor/bitacora-parametros.md` | Entrada de `reglas-v0.1.0` |

## Cómo ejecutar

```powershell
uv sync                                        # crea .venv con las versiones de uv.lock
uv run hlf-lote --fecha-corte 2026-10-13       # lee data/dataset_hlf_ambulatorio, escribe en salidas/
uv run pytest                                  # perfil Hypothesis "ci" por defecto
uv run ruff check; uv run mypy src; uv run pip-audit
```

Opciones de `hlf-lote`: `--datos RUTA`, `--salidas RUTA`, `--reglas RUTA` y `--fecha-extraccion AAAA-MM-DD` (por defecto 2026-10-13). Códigos de salida: 0 ok, 1 cobertura incompleta, 2 entrada o configuración inválida, 3 error inesperado.

Salidas (todas en `salidas/`, ignorado por git): `propuestas/fecha_corte=…/version_reglas=…/propuestas.parquet`, `hallazgos_dq/fecha_corte=…/hallazgos.jsonl`, `cohortes/…/cohortes.jsonl`, `cuarentena/fecha_extraccion=…/cuarentena.jsonl`, `resumen/…/resumen.json` y `auditoria/eventos.jsonl`. U2 y U3 leen las propuestas con `persistencia.salidas.leer_propuestas()`.

## Verificación (ejecutada el 2026-10-15)

| Comando | Resultado |
|---|---|
| `uv run ruff check` | All checks passed! |
| `uv run mypy src` (estricto) | Success: no issues found in 27 source files |
| `uv run pytest` (`HYPOTHESIS_PROFILE=ci`, `derandomize=True`) | 107 passed (87 de ejemplo, contando parametrizaciones, + 20 propiedades) |
| `uv run pip-audit` | No known vulnerabilities found (solo se omite el paquete local `hlf-priorizacion`) |
| `pytest tests/ejemplos/test_casos_referencia.py` con `HLF_DATOS=C:\no-existe` | 12 skipped con el mensaje "Dataset real no disponible…" |

Lote sobre el dataset real:

| Corte | Evaluadas | `en_espera` | Cobertura | Exclusiones | Priorizaciones | Cuarentena / errores | Código |
|---|---|---|---|---|---|---|---|
| 2026-10-13 | 500 | 409/409 | 100 % (500/500) | 76 `EX_ATENDIDO`, 15 `EX_FALLECIDO` | 125 (123 suben, 2 bajan) | 0 / 0 | 0 |
| 2026-07-19 | 468 (32 aún no ingresaban) | 385/385 | 100 % (468/468) | 29 `EX_ATENDIDO_INFERIDO`, 10 `EX_FALLECIDO` | 85 | 0 / 0 | 0 |
| 2026-07-20 | 468 | 385/385 | 100 % (468/468) | 29 `EX_ATENDIDO_INFERIDO`, 10 `EX_FALLECIDO` | 86 | 0 / 0 | 0 |

Idempotencia: al re-ejecutar los tres cortes, los 12 archivos de salida (salvo la auditoría) conservan su SHA-256 y el lote informa "Propuestas nuevas: 0 · conflictos: 0". Los Parquet también son idénticos byte a byte a los de una ejecución anterior desde una carpeta vacía. La auditoría solo crece (1436 eventos por pasada).

Calidad de datos en el dataset real: 500/500 perfiles cumplen el contrato; 0 diferencias de conciliación; 12 mediciones descartadas por plausibilidad (SatO₂ 101 %, HbA1c < 3 %); 76 `asistio_en_espera`; 10 perfiles con citas no cronológicas.

### Casos de referencia: valores reales frente a la tabla a mano

| Caso | Corte | A mano | Motor (`reglas-v0.1.0`) | Criterio | ¿Pasa? |
|---|---|---|---|---|---|
| PAC-HLF-00002 | 2026-07-19 | ≈ 37,8 baja | 37,77 baja | baja o media | Sí |
| PAC-HLF-00002 | 2026-07-20 | ≈ 53,8 media → crítica | 58,82 media → **crítica** (`BR_EVENTO_GRAVE_30D`, EV-000004) | ≥ alta | Sí |
| PAC-HLF-00002 | 2026-10-13 | ≈ 66,6 alta | 66,51 alta, sin bandera | ≥ alta | Sí |
| PAC-HLF-00001 | 2026-10-13 | ≈ 94,8 alta | 94,57 alta, `PISO_PHQ9`, factor `medicion_tendencia` del PHQ-9 | ≥ alta, explica tendencia | Sí |
| PAC-HLF-00028 | 2026-10-13 | ≈ 13,8 baja | 13,82 baja (buena respuesta −2,83; reducción dosis −3,35) | baja como máximo un nivel | Sí |
| PAC-HLF-00020 | 2026-10-13 | 50 media | 50,00 media con y sin citas; `citas_fallidas` (3 citas) | puntaje igual; alerta | Sí |
| PAC-HLF-00032 | 2026-10-13 | exclusión | `EX_ATENDIDO` | exclusión | Sí |
| PAC-HLF-00032 | 2026-06-29 | ≈ 30 baja | 34,00 baja | no se dispara | Sí |
| PAC-HLF-00009 | 2026-09-07 | ≈ 80 crítica | 80,38 alta → **crítica** | se evalúa | Sí |
| PAC-HLF-00009 | 2026-09-08 | exclusión | `EX_FALLECIDO` | exclusión | Sí |

Diferencias con el cálculo a mano (no cambian ningún nivel ni criterio): al 2026-07-20 la tabla omitió la aceleración (+5: 1 evento grave en 90 días frente a 0); en PAC-HLF-00032 al 2026-06-29 suma +4 por empeoramiento brusco (SatO₂ 97 % frente a una mediana previa de 98,5 %, más de 0,2 × ancho del rango, en la dirección dañina), aunque el valor sigue en rango. Es la lectura literal de R5.6; queda como tema para la validación clínica (T3). Además, PAC-HLF-00032 al 2026-07-15 sale `EX_ATENDIDO_INFERIDO` (egreso inferido 2026-06-30, confianza media), como define R3.3.

## Desviaciones del diseño o del plan

| Tema | Decisión | Motivo |
|---|---|---|
| Dependencias | No se agregaron `pandas` ni `numpy` al runtime; se agregó `pyarrow-stubs` en dev | El código no los usa (menos superficie, SECURITY-10); mypy estricto |
| `minutos_atencion_real = ""` | El contrato lo interpreta como nulo | El dataset lo trae así en las 105 citas sin atención; sin esto, 85 perfiles iban a cuarentena |
| Campos agregados a los modelos | `Evaluacion.codigo_exclusion`, `MarcaInferido`; `ContextoPaciente.id_paciente`, `fecha_defuncion` (solo si ≤ corte), `id_cita_egreso_inferido`; `SolicitudContexto.estado_extraccion`; `AnalisisIA.id_solicitud` y `version_esquema` | Necesarios para R3.3, para explicar exclusiones y para enlazar el análisis con la propuesta |
| Hallazgos de ingesta | "Duplicado" y "citas no cronológicas" se detectan en la ingesta y el lote los agrega a los hallazgos del corte (solo con IDs presentes en el contexto) | Dependen del orden y de los duplicados de origen, que el contexto ya no conserva |
| Confianza | No se usa la condición de cohorte n ≥ 30 | `evaluar()` no recibe la cohorte (firma de la sección 2.2) |
| Interpretaciones de reglas | Ventanas inclusivas; dirección dañina bidireccional según el lado del punto medio; evidencia de mejoría exige ≥ 1 medición en 90 días; `asistio_en_espera`/`estado_inconsistente` solo cuando el estado es conocido (corte = extracción) | Detalle en `bitacora-parametros.md` |
| Cobertura en cortes pasados | Las solicitudes con ingreso posterior al corte se informan como "no vigentes a la fecha" y no entran al universo | Aún no existían en esa fecha |
| JSONL "solo agregar" | DQ, cuarentena y cohortes se agregan solo si su clave no está | Respeta "solo agregar" sin duplicar al re-ejecutar |
| `resumen.json` | No guarda los contadores de escritura | Cambian entre ejecuciones y romperían la idempotencia |
| CLI | Opciones extra `--reglas` y `--fecha-extraccion` | Probar otra versión de reglas y otro corte de extracción sin tocar código |
| Cohortes | Se calculan y guardan para las `priorizacion`, pero `evaluar()` no las usa | Las consume U2 |

## Seguridad (MVP local)

Logs JSON con `timestamp`, `nivel`, `id_ejecucion` y `mensaje`, con lista permitida de campos (IDs, conteos, códigos); las excepciones se registran solo por tipo. Validación estricta con Pydantic y de los argumentos de la CLI (formato y rango de `--fecha-corte`, rutas existentes, `--salidas` fuera de la carpeta de datos). Errores por perfil se cuentan y no detienen el lote; parámetros o fuentes inválidos lo detienen (código 2). No hay servicios de red: la CLI es local y sin autenticación, como define el MVP. Verificado por prueba: el stderr del lote no contiene valores clínicos ni datos personales del perfil sintético.
