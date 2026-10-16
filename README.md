# AWS-G12

Priorización clínica dinámica para la lista de espera de especialidad del HLF. El sistema propone y explica; el equipo clínico decide. Contexto en `docs/` y `CLAUDE.md`.

## Cómo ejecutar el motor

Requisitos: Python 3.12 y [uv](https://docs.astral.sh/uv/). El dataset sintético del HLF va en `data/dataset_hlf_ambulatorio/` (no se versiona).

```powershell
. .\scripts\entorno-demo.ps1                    # consola en UTF-8 (en Windows con otra página de códigos)
uv sync                                         # instala las dependencias fijadas en uv.lock
uv run hlf-lote --fecha-corte 2026-10-13        # evalúa todas las solicitudes a esa fecha
uv run hlf-lote --fecha-corte 2026-07-20 --datos data/dataset_hlf_ambulatorio --salidas salidas
```

El lote valida cada perfil (los inválidos van a cuarentena), arma el contexto con solo lo que se sabía a la fecha de corte, calcula el puntaje y el nivel propuesto con `reglas-v0.1.0` y escribe en `salidas/` (ignorado por git): propuestas en Parquet, hallazgos de calidad, cohortes, cuarentena, un resumen y la auditoría. Re-ejecutar el mismo corte no duplica nada. Termina con código distinto de 0 si alguna solicitud no quedó evaluada ni en cuarentena.

## Cómo ejecutar el copiloto IA (U2)

Analiza con Amazon Bedrock las solicitudes que el lote dejó en `priorizacion` y guarda un análisis citado y validado, siempre pendiente de revisión médica. Usa la cadena estándar de credenciales de AWS y exige que existan las salidas de `hlf-lote` para cada fecha (si faltan, muestra los comandos y no llama a Bedrock).

```powershell
uv run hlf-copiloto --fecha-corte 2026-08-10
uv run hlf-copiloto --desde 2026-07-19 --hasta 2026-07-21 [--forzar] [--max-llamadas 300]
```

Modelo por defecto `us.anthropic.claude-sonnet-5` (respaldo: `HLF_BEDROCK_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0`); concurrencia `HLF_COPILOTO_CONCURRENCIA` (1–8, por defecto 4). Resultados en `salidas/analisis/fecha_corte=…/version_reglas=…/analisis.jsonl` (y `fallidos.jsonl`). Re-ejecutar no vuelve a llamar por lo ya analizado; los fallidos se reintentan. `--max-llamadas` es el presupuesto de invocaciones reales al modelo, contando los reintentos: al agotarse, las solicitudes restantes quedan como `limite_llamadas` y la siguiente ejecución las retoma. Códigos de salida: 0 ok, 1 hubo fallidas o quedaron solicitudes por `limite_llamadas`, 2 entrada inválida, 3 error inesperado, 4 permiso o modelo no permitido (Bedrock denegó el acceso o `HLF_BEDROCK_MODEL_ID` no está en la lista permitida), 130 interrumpido con Ctrl+C.

Ctrl+C es seguro: cada solicitud se guarda apenas termina, las llamadas en curso terminan (hasta 70 s; un segundo Ctrl+C no espera) y volver a ejecutar el mismo comando sigue con las que faltan.

## Cómo abrir la bandeja (U3, demo local)

Interfaz en Streamlit para el médico contralor: bandeja ordenada, detalle de cada solicitud, "¿Qué cambió?" entre dos cortes y cobertura. Es de solo lectura sobre `salidas/`: no ejecuta el lote ni el copiloto y no llama a Bedrock. Lo único que escribe es la decisión médica (`salidas/decisiones/decisiones.jsonl`, solo agregar, más un evento `decision_medica` en la auditoría sin el texto del motivo).

```powershell
. .\scripts\entorno-demo.ps1
uv run streamlit run app/bandeja.py     # http://127.0.0.1:8501 (solo localhost, sin telemetría)
```

Sin login: es una demo local con datos sintéticos y médicos ficticios (`app/config_demo.py`). Para usar otras carpetas: `HLF_SALIDAS` y `HLF_DATOS`. Si un corte no tiene propuestas o análisis, la interfaz muestra el comando exacto (`uv run hlf-lote --fecha-corte AAAA-MM-DD`, `uv run hlf-copiloto --fecha-corte AAAA-MM-DD`).

Recorrido de la demo:

1. Barra lateral: elegir "Dra. Demo Uno" y el corte 2026-07-19. IC-HLF-00002 está en baja, sin alerta (se ve con "Incluir sin alerta").
2. "¿Qué cambió?" 2026-07-19 → 2026-07-20: IC-HLF-00002 pasa de baja a crítica, con el registro nuevo EV-000004 y la bandera BR_EVENTO_GRAVE_30D. Elegir la fila abre el Detalle en el corte B.
3. Detalle 2026-07-20: factores con sus IDs, línea de tiempo con EV-000004 resaltado, análisis del copiloto (rotulado como sugerencia) y nota de pre-consulta.
4. Decidir "Aceptar" y guardar: queda en `decisiones.jsonl` y en la auditoría; la fila de la bandeja muestra "aceptada".
5. Corte 2026-07-19, IC-HLF-00349: la advertencia de equidad aparece antes del análisis.

Pruebas y controles:

```powershell
uv run pytest            # ejemplos + propiedades (Hypothesis, perfil "ci" reproducible)
uv run ruff check
uv run mypy src
uv run pip-audit
uv run pytest -m bedrock -s   # prueba contra Bedrock real (consume tokens; excluida por defecto)
```

Los casos de referencia (`tests/ejemplos/test_casos_referencia.py`) usan el dataset real; si no está, se saltan.
