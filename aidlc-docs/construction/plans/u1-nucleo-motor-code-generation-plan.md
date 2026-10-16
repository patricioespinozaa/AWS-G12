# Plan de Code Generation — U1 Núcleo de datos y motor de reglas

Este plan es la única fuente de verdad para generar U1. Se ejecuta paso a paso y cada paso se marca `[x]` al terminar.

## Contexto de la unidad

| | |
|---|---|
| Unidad | U1 (componentes C1–C5 de `docs/contexto-tecnico.md`) |
| Diseño | `aidlc-docs/construction/u1-nucleo-motor/functional-design/` (entidades, reglas R1–R10, modelo lógico y propiedades) |
| Requisitos | RF-01, RF-02, RF-03, RF-04, RF-05, RF-06; parte de RF-08, RF-09 y RF-12 (`unit-of-work-story-map.md`) |
| Depende de | Nada |
| La usan | U2 (copiloto) y U3 (bandeja), a través de `modelos.py` y los archivos de `salidas/` |
| Entorno verificado | Python 3.12.7, uv 0.12.0, Windows + PowerShell |
| Datos | `data/dataset_hlf_ambulatorio/perfiles.json` (+ CSV). Ignorados por git; nunca se copian a `tests/` |
| Ubicación del código | Raíz del workspace. Nunca en `aidlc-docs/` |

## Restricciones que el código debe cumplir

- `evaluar()` es pura: sin I/O, sin reloj del sistema, sin aleatoriedad.
- `ContextoPaciente` no tiene `comuna`, `prevision`, `nivel_socioeconomico` ni `nombre_fantasia`.
- `prioridad_inicial` nunca se modifica; toda salida nace con `estado_revision = pendiente_revision_medica`.
- **SECURITY-03:** logs estructurados (JSON) con `timestamp`, nivel, `id_ejecucion` y mensaje; sin valores clínicos ni datos de pacientes en el log (solo IDs).
- **SECURITY-05:** validar `--fecha-corte` y rutas de la CLI; Pydantic en modo estricto.
- **SECURITY-10:** dependencias con versión exacta en `pyproject.toml` + `uv.lock`; `pip-audit` limpio.
- **SECURITY-15:** manejo explícito de errores de E/S; un error en un perfil no detiene el lote (se registra y se cuenta); errores de configuración sí lo detienen (fail-closed).
- **PBT-07/08:** generadores de dominio compartidos; Hypothesis con `derandomize=True` en CI y la semilla impresa al fallar.

## Pasos

### Paso 1 — Estructura del proyecto
- [x] `pyproject.toml` con uv: paquete `hlf_priorizacion` en `src/`, Python `>=3.12,<3.13`, script `hlf-lote = "hlf_priorizacion.lote:main"`
- [x] Dependencias fijadas a versión exacta (las vigentes al instalar): `pydantic`, `pyyaml`, `pandas`, `pyarrow`, `numpy`. Grupo dev: `pytest`, `hypothesis`, `statsmodels` (solo oráculo de Wilson), `ruff`, `mypy`, `pip-audit`, `types-PyYAML`
  - Desviación: `pandas` y `numpy` no se agregan como dependencias de ejecución porque el código no los usa (menos superficie, SECURITY-10); `numpy`/`pandas` llegan solo como transitivas de `statsmodels` en dev. Se agregó `pyarrow-stubs` (dev) para `mypy` estricto
- [x] `uv lock` y `uv sync`; `uv.lock` versionado
- [x] Configuración de `ruff`, `mypy` (estricto en `src/`) y `pytest` en `pyproject.toml`; perfiles de Hypothesis `ci` (derandomize) y `dev`
  - Los perfiles de Hypothesis se registran en `tests/conftest.py` (`ci` por defecto, `dev` con `HYPOTHESIS_PROFILE=dev`)
- [x] Verificar que `.gitignore` cubre `salidas/`, `.venv/` y `data/dataset_hlf_ambulatorio` (se agregaron además `.hypothesis/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`)

### Paso 2 — Contratos compartidos (desbloquea U2 y U3)
- [x] `src/hlf_priorizacion/modelos.py`: `Factor`, `Bandera`, `Piso`, `Contradiccion`, `AlertaGestion`, `Evaluacion`, `HallazgoDQ`, `ResultadoCohorte`, `ContextoPaciente` y registros citados, según `domain-entities.md`. Además, los modelos de intercambio que usarán U2 y U3: `AnalisisIA` (esquema `analisis-v1`, sección 8.4 del contexto técnico) y `Decision` (aceptada/ajustada/rechazada, con validación de `prioridad_final` y `motivo`)
  - Catálogos cerrados en `contrato/catalogos.py` (los usan `modelos.py` y `contrato/esquema.py`). Agregados respecto del diseño: `Evaluacion.codigo_exclusion` y `MarcaInferido`; `ContextoPaciente.id_paciente`, `fecha_defuncion` (solo si ≤ corte) e `id_cita_egreso_inferido`; `SolicitudContexto.estado_extraccion` (lo exige R3.3); `AnalisisIA.id_solicitud` y `version_esquema`
- [x] `tests/fixtures/evaluacion_ejemplo.json` con el formato de la sección 6.8, usando IDs reales de PAC-HLF-00002 (sin datos personales: solo IDs, fechas y valores clínicos ya presentes en el dataset sintético)
- [x] Prueba: el fixture valida contra `Evaluacion` (`tests/ejemplos/test_modelos.py`)

### Paso 3 — Contrato y cuarentena (R1)
- [x] `contrato/esquema.py`: modelos Pydantic de entrada (`PerfilCrudo` y anidados), enumerados cerrados, combinaciones tipo/subtipo/severidad, unidad por tipo de medición; acepta `lista_espera` como objeto o lista
  - Hallazgo en el dataset: `minutos_atencion_real` llega como `""` en las citas sin atención (105 citas); el contrato lo interpreta como nulo. Sin ese ajuste, 85 perfiles caían en cuarentena
- [x] `contrato/esquema_json.py`: exporta el JSON Schema 2020-12 a `contrato/contrato-v1.0.0.schema.json`
- [x] `contrato/validacion.py`: `validar_perfil(raw) -> ResultadoValidacion`; descarta `nombre_fantasia`
- [x] Pruebas de ejemplo: perfil válido, cada motivo de cuarentena de la sección 4.2 (`tests/ejemplos/test_contrato.py`, 14 motivos + motivos sin valores de entrada + esquema exportado al día). Con el dataset real: 500/500 perfiles válidos

### Paso 4 — Ingesta
- [x] `ingesta/carga.py`: lectura de `perfiles.json` y CSV con manejo de errores
- [x] `ingesta/normalizacion.py`: CIE-10, `id_medicion` determinista, `especialidad_evento` desde `detalle`, deduplicación
- [x] `ingesta/conciliacion.py`: conteos por serie perfil ↔ CSV; diferencias como hallazgo `verificar` (además de conteos, compara una huella SHA-256 por serie). Con el dataset real: 0 perfiles con diferencias
- [x] Pruebas de ejemplo (`tests/ejemplos/test_ingesta.py`)

### Paso 5 — Repositorio
- [x] `repositorio/contexto.py`: `contexto_a_fecha()` (R2, R3.3 con `fecha_egreso_inferida`), `linea_tiempo()`, huella SHA-256 (clase `Repositorio` en memoria con las firmas de la sección 2.2)
- [x] `repositorio/cohortes.py`: clave, relajación, desenlace a 90 días, seguimiento completo, exclusión del paciente, IC95 Wilson (R9)
- [x] Pruebas de ejemplo (`tests/ejemplos/test_repositorio.py`)

### Paso 6 — Calidad de datos (R4)
- [x] `calidad/reglas.py` y `calidad/auditoria.py`: hallazgos por categoría con límites de plausibilidad de la tabla 7.1
  - "Medición duplicada" y "citas no cronológicas" se detectan en la ingesta (dependen del orden y de los duplicados de origen, que el contexto ya no tiene) y se escriben junto con los hallazgos DQ del lote. Con el dataset real (corte 2026-10-13): 12 mediciones `descartar` por plausibilidad (SatO₂ 101 %, HbA1c < 3 %), 76 `asistio_en_espera`, 10 perfiles con citas no cronológicas
- [x] Pruebas de ejemplo por categoría (`tests/ejemplos/test_calidad.py`)

### Paso 7 — Motor de reglas (R3, R5–R8)
- [x] `motor/reglas/reglas-v0.1.0.yaml` con todos los parámetros de `business-rules.md` (incluido el umbral de tendencia R5.7)
- [x] `motor/parametros.py`: carga y validación de los parámetros (error fatal si faltan o son inválidos)
- [x] `motor/evaluar.py`: implementación de `evaluar()` según `business-logic-model.md`
- [x] `motor/referencia.py`: implementación de referencia simple y legible, solo para el oráculo de pruebas
- [x] `aidlc-docs/construction/u1-nucleo-motor/bitacora-parametros.md` con la entrada inicial de `reglas-v0.1.0`

### Paso 8 — Persistencia y auditoría
- [x] `persistencia/salidas.py`: escritura idempotente de propuestas en Parquet (`salidas/propuestas/fecha_corte=…/version_reglas=…/`), clave `(id_solicitud, fecha_corte, version_reglas)`; lectura para U2 y U3
  - Semántica `attribute_not_exists`: una clave existente no se sobrescribe (si llega distinta, se cuenta como conflicto y se informa). Hallazgos DQ, cuarentena y cohortes van en JSONL de solo agregado que además es idempotente (solo agrega claves nuevas), para que re-ejecutar no duplique
- [x] `auditoria/registro.py`: JSONL solo de agregado (`salidas/auditoria/…`), un evento `evaluacion_motor` por solicitud y `error_proceso` por fallo
- [x] Pruebas de ejemplo (`tests/ejemplos/test_persistencia.py`)

### Paso 9 — CLI del lote
- [x] `lote.py`: `hlf-lote --fecha-corte AAAA-MM-DD [--datos RUTA] [--salidas RUTA]`, flujo de `business-logic-model.md`, resumen final (evaluadas, cuarentena, exclusiones, cambios de nivel, cobertura) y código de salida ≠ 0 si la cobertura no es 100 %
  - Opciones agregadas: `--reglas RUTA` (otra versión de parámetros) y `--fecha-extraccion` (por defecto 2026-10-13). Códigos: 0 ok, 1 cobertura incompleta, 2 entrada/configuración inválida, 3 error inesperado. En cortes pasados, las solicitudes con `fecha_ingreso_lista > corte` se informan como "no vigentes a la fecha" y no entran al universo de cobertura (aún no existían)
  - Prueba de integración: `tests/ejemplos/test_lote.py`
- [x] Logging JSON configurado en el punto de entrada; manejador global de errores (`logs.py`: lista permitida de campos; excepciones solo por tipo)

### Paso 10 — Pruebas basadas en propiedades
- [x] `tests/estrategias/`: generadores de paciente, solicitud, evento (solo combinaciones catalogadas), medición (normal, riesgo, extremo, imposible), cita, perfil completo y fecha de corte válida; con casos borde (también "borde exacto" del rango, perfil sin registros, evento y defunción el día del corte). `tests/estrategias/tuberia.py` encadena contrato → ingesta → contexto → DQ → motor
- [x] `tests/propiedades/`: las 18 propiedades de la sección "Propiedades testeables" de `business-logic-model.md`, más la de equidad sobre `PerfilCrudo` (20 pruebas en 4 archivos: las 18 + equidad + "el contexto solo contiene registros hasta el corte" y "estado desconocido antes de la extracción"). En una muestra de 300 casos generados hubo 114 priorizaciones, 83 exclusiones, 91 con bandera, 25 con piso y 97 con mediciones descartadas

### Paso 11 — Pruebas de ejemplo de los 6 casos
- [x] `tests/ejemplos/test_casos_referencia.py`: cada fila de la tabla "Verificación en seco" de `business-logic-model.md`, leyendo el dataset real. Si el dataset no existe, la prueba se salta con un mensaje claro (no falla en CI sin datos)
  - 12 pruebas: las 10 filas + egreso inferido de PAC-HLF-00032 al 2026-07-15 + el fixture de la sección 6.8 (PAC-HLF-00002 al 2026-08-10), que se regeneró desde la salida real del motor. Ruta configurable con `HLF_DATOS`. Verificado: con `HLF_DATOS=C:\no-existe` las 12 se saltan con el mensaje

### Paso 12 — Verificación
- [x] `uv run ruff check`, `uv run mypy src`, `uv run pytest` (con el perfil `ci` de Hypothesis), `uv run pip-audit`
  - `ruff check`: "All checks passed!" · `mypy src` (estricto): "Success: no issues found in 27 source files" · `pytest` con `HYPOTHESIS_PROFILE=ci`: 107 passed (encabezado `perfil=ci derandomize=True print_blob=True`) · `pip-audit`: "No known vulnerabilities found" (solo se omite el propio paquete local `hlf-priorizacion`, que no está en PyPI)
- [x] `uv run hlf-lote --fecha-corte 2026-10-13`, `2026-07-19` y `2026-07-20` sobre el dataset real: cobertura 100 % y resultados de PAC-HLF-00002 según el diseño
  - 2026-10-13: 500/500 cubiertas (409/409 `en_espera`), 91 exclusiones (76 `EX_ATENDIDO`, 15 `EX_FALLECIDO`), 125 priorizaciones, 0 cuarentena, 0 errores, código 0
  - 2026-07-19 y 2026-07-20: 468/468 cubiertas (385/385 `en_espera` vigentes; 32 solicitudes aún no ingresaban), 29 `EX_ATENDIDO_INFERIDO` y 10 `EX_FALLECIDO`, código 0
  - PAC-HLF-00002: 07-19 → 37,77 baja; 07-20 → 58,82 calculado media, propuesto **crítica** por `BR_EVENTO_GRAVE_30D` (EV-000004); 10-13 → 66,51 alta, sin bandera. Coincide con el diseño
- [x] Ejecutar dos veces el mismo corte y comprobar que las salidas son idénticas (idempotencia)
  - Se re-ejecutaron los tres cortes: los 12 archivos de `salidas/` (salvo la auditoría) tienen el mismo SHA-256; las propuestas Parquet tienen además el mismo SHA-256 que en una ejecución anterior desde una carpeta vacía. Segunda ejecución: "Propuestas nuevas: 0 · ya existentes: 500/468/468 · conflictos: 0". La auditoría solo crece (+1436 eventos por cada pasada de los 3 cortes)
  - Ajuste hecho al verificar: el `resumen.json` persistido ya no guarda los contadores de escritura (nuevas/existentes), que cambian entre ejecuciones; esos se informan por consola y log
- [x] Si un caso falla, aplicar R10 (nueva versión de parámetros + bitácora) o informar al usuario si un ajuste rompe otro caso
  - No hizo falta: los 6 casos cumplen su criterio con `reglas-v0.1.0` (anotado en `bitacora-parametros.md`)

### Paso 13 — Documentación
- [x] `aidlc-docs/construction/u1-nucleo-motor/code/resumen.md`: archivos creados, cómo ejecutar, resultados de la verificación, desviaciones
- [x] `README.md`: sección breve "Cómo ejecutar el motor"
- [x] `CLAUDE.md`, sección Estado: comandos de instalación y ejecución (se ajustó también la frase "Aún no hay código implementado" del primer punto)

## Fuera de este plan

Modo copiloto (U2), interfaz (U3), artefactos de despliegue en AWS (U4: fuera del MVP), migraciones de base de datos (no hay base de datos en el MVP).
