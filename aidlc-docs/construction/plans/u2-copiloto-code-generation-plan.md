# Plan de Code Generation — U2 Copiloto (modo barrido)

Este plan es la única fuente de verdad para generar U2. Se ejecuta en orden y cada paso se marca `[x]` al terminar.

## Contexto de la unidad

| | |
|---|---|
| Unidad | U2 (componente C6 de `docs/contexto-tecnico.md`, sección 8) |
| Diseño | `aidlc-docs/construction/u2-copiloto/functional-design/` (entidades, reglas C1–C7, modelo lógico y propiedades) |
| Requisitos | RF-07 (parcial: solo barrido), parte de RF-08 y RF-09 |
| Depende de | U1, ya construida: `modelos.py` (`AnalisisIA`, `Evaluacion`, `ContextoPaciente`, `ResultadoCohorte`), `persistencia.salidas` (`leer_propuestas`, `agregar_jsonl`, `escribir_json`), `repositorio.contexto` (`contexto_a_fecha`, `huella_contexto`), `ingesta`, `auditoria.registro`, `logs.py` |
| La usa | U3 (bandeja), leyendo `salidas/analisis/` |
| Externo | Amazon Bedrock Runtime, `us-east-1`, cuenta del workshop con lista de modelos permitidos |
| Ubicación | `src/hlf_priorizacion/copiloto/` y `tests/`. Nunca en `aidlc-docs/` |

## Hechos que el código debe respetar

- U1 **no guarda el contexto** de cada solicitud: guarda la `Evaluacion` con `huella_contexto`. U2 reconstruye el contexto desde el dataset con `contexto_a_fecha()` y **verifica que su huella sea igual** a la de la evaluación. Si no coincide (datos cambiados desde el lote), esa solicitud se marca fallida con motivo `huella_distinta` y no se llama al modelo.
- Las cohortes las dejó U1 en `salidas/cohortes/fecha_corte=…/version_reglas=…/cohortes.jsonl`.
- Modelos permitidos verificados: `us.anthropic.claude-sonnet-5` (por defecto) y `us.anthropic.claude-haiku-4-5-20251001-v1:0` (respaldo). Sonnet 5.5 está denegado.

## Restricciones

- **SECURITY-03 / C7.2:** logs JSON sin texto clínico ni texto del modelo; solo IDs, `model_id`, `request_id`, tokens, latencia, códigos.
- **SECURITY-05:** validación estricta de todos los argumentos (C2.3) antes de cualquier llamada.
- **SECURITY-10:** `boto3` (y `botocore`) con versión exacta en `pyproject.toml` y `uv.lock`; `pip-audit` limpio.
- **SECURITY-15 / C4.4–C4.5:** timeouts explícitos, reintentos acotados, corte de circuito, fail-closed ante permisos; un fallo de una solicitud no detiene las demás.
- **C7.1:** credenciales solo por la cadena estándar de AWS; nada de claves en código o archivos.
- **PBT:** generadores en `tests/estrategias/` (reutilizar los de U1); perfil `ci` con `derandomize=True`.
- **Las pruebas automáticas no llaman a Bedrock.** La prueba contra Bedrock real se marca (`@pytest.mark.bedrock`) y se excluye por defecto.

## Pasos

### Paso 1 — Dependencias y estructura
- [x] Agregar `boto3` con versión exacta (grupo principal) y `boto3-stubs[bedrock-runtime]` o equivalente en dev; `uv lock`, `uv sync`
- [x] Script `hlf-copiloto = "hlf_priorizacion.copiloto.cli:main"` en `pyproject.toml`
- [x] Marcador `bedrock` registrado en pytest y excluido por defecto (`-m "not bedrock"`)
- [x] Carpeta `src/hlf_priorizacion/copiloto/` con `__init__.py`

### Paso 2 — Configuración y prompt
- [x] `copiloto/config.py`: `ConfigModelo` desde variables de entorno (`HLF_BEDROCK_MODEL_ID`, `HLF_COPILOTO_CONCURRENCIA` 1–8, `HLF_BEDROCK_REGION` por defecto `us-east-1`), temperatura 0, timeout 60 s; validación estricta
- [x] `copiloto/prompts/copiloto-v1.0.0/sistema.md` y `usuario.md` en español, según `business-logic-model.md` y las reglas "siempre/nunca" de la sección 12.6 del negocio (en `docs/contexto-tecnico.md` 8.1 y el contexto de negocio)
- [x] `copiloto/prompt.py`: carga del prompt, `version_prompt` y huella SHA-256

### Paso 3 — Fechas y selección (C1, C2, C5.1)
- [x] `copiloto/fechas.py`: parseo ISO estricto y validación de C2.3 (desde < hasta, ≤ extracción, rango ≤ 31 días, modos excluyentes)
- [x] `copiloto/seleccion.py`: funciones puras que, por corte, reparten cada solicitud en `pendiente` u `omitida(motivo)`, incluido `sin_cambio_en_rango` (C2.4, desactivable) y `ya_analizada`; cálculo de llamadas y tope (C2.5)
- [x] Verificación de que existen las propuestas del lote para cada fecha; mensaje con los comandos `hlf-lote` exactos que faltan

### Paso 4 — Paquete (C3)
- [x] `copiloto/paquete.py`: `PaqueteBarrido` (en `copiloto/modelos.py` o `modelos.py`), reconstrucción del contexto con `contexto_a_fecha`, verificación de huella, evaluación, `evaluacion_anterior` en rango, DQ (con `descartar` marcados), cohorte; render del bloque `<datos_clinicos>`

### Paso 5 — Cliente del modelo (C4)
- [x] `copiloto/cliente.py`: interfaz `ClienteModelo`; `ClienteBedrock` (Converse, herramienta `registrar_analisis` con el JSON Schema de `AnalisisIA` sin `metadatos`, `toolChoice` forzado, timeouts de botocore) y `ClienteFalso` para pruebas (respuestas fijas, malformadas, errores, limitación)
- [x] Reintentos con espera exponencial y jitter; clasificación de errores reintentables y fatales

### Paso 6 — Validación (C6)
- [x] `copiloto/validacion.py`: funciones puras de C6.1–C6.6 con registro de correcciones; un reintento con el error (C6.7)

### Paso 7 — Orquestación y persistencia (C4.3, C4.5, C5)
- [x] `copiloto/barrido.py`: ejecución con `ThreadPoolExecutor` (concurrencia configurable), corte de circuito, resultados en orden determinista por `id_solicitud`
- [x] Persistencia: `salidas/analisis/fecha_corte=…/version_reglas=…/analisis.jsonl` y `fallidos.jsonl` con `agregar_jsonl` y la clave de idempotencia; lectura `leer_analisis()` para U3
- [x] Auditoría: `llamada_modelo`, `analisis_ia`, `analisis_omitido`, `error_proceso`

### Paso 8 — CLI
- [x] `copiloto/cli.py`: `hlf-copiloto (--fecha-corte F | --desde F --hasta F) [--forzar] [--max-llamadas N] [--datos RUTA] [--salidas RUTA] [--reglas RUTA] [--fecha-extraccion F]`; logging JSON; resumen (analizadas, omitidas por motivo, fallidas, tokens, tiempo); códigos de salida 0 ok, 1 hubo fallidas, 2 entrada o configuración inválida, 3 error inesperado, 4 permisos de Bedrock

### Paso 9 — Pruebas
- [x] `tests/estrategias/`: generadores de respuestas del modelo (válidas, IDs inventados, cifras distintas, malformadas, motivos prohibidos) y de pares de fechas
- [x] `tests/propiedades/`: las 14 propiedades de `business-logic-model.md`
- [x] `tests/ejemplos/`: PAC-HLF-00002 al 2026-08-10 con cliente falso; rango 2026-07-19..2026-07-21 con cliente falso; cada error de fecha de C2.3; falta de salidas del lote; huella distinta; permisos denegados; idempotencia (segunda ejecución sin llamadas)
- [x] `tests/integracion/test_bedrock_real.py` marcada `bedrock`: un análisis real de PAC-HLF-00002 al 2026-08-10

### Paso 10 — Verificación
- [x] `uv run ruff check`, `uv run mypy src`, `uv run pytest`, `uv run pip-audit`: todo limpio, sin romper las 107 pruebas de U1
- [x] Asegurar que existen las salidas del lote para 2026-07-19, 2026-07-20, 2026-07-21 y 2026-08-10 (correr `hlf-lote` si faltan)
- [x] **Llamada real a Bedrock (consume tokens de la cuenta del workshop):** `uv run pytest -m bedrock` y `uv run hlf-copiloto --desde 2026-07-19 --hasta 2026-07-21`. Revisar el análisis de IC-HLF-00002 contra el criterio de aceptación y anotar tokens y tiempo
- [x] Re-ejecutar el mismo comando y comprobar 0 llamadas nuevas
- [x] **No** correr el copiloto sobre el corte completo 2026-10-13 en esta verificación (125 llamadas): queda para preparar la demo, con aviso al usuario

### Paso 11 — Documentación
- [x] `aidlc-docs/construction/u2-copiloto/code/resumen.md`: archivos, cómo ejecutar, verificación con números reales, un extracto del análisis de IC-HLF-00002 (solo IDs y texto del modelo; el dataset es sintético), desviaciones
- [x] `README.md` y `CLAUDE.md` (Estado): comando `hlf-copiloto`
- [x] Entrada en `aidlc-docs/audit.md` (solo agregar)

## Fuera de este plan

Modo reactivo con herramientas, Bedrock Guardrails (G-4), interfaz (U3), despliegue en AWS (U4).
