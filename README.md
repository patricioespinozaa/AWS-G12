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

El lote valida cada perfil (los inválidos van a cuarentena), arma el contexto con solo lo que se sabía a la fecha de corte, calcula el puntaje y el nivel propuesto con `reglas-v0.2.0` (versión por defecto) y escribe en `salidas/` (ignorado por git): propuestas en Parquet, hallazgos de calidad, cohortes, cuarentena, un resumen y la auditoría. Re-ejecutar el mismo corte no duplica nada. Termina con código distinto de 0 si alguna solicitud no quedó evaluada ni en cuarentena. Para la versión anterior: `--reglas src/hlf_priorizacion/motor/reglas/reglas-v0.1.0.yaml` (cada versión escribe en su propia partición `version_reglas=…`).

`reglas-v0.2.0` agrega dos cosas a `reglas-v0.1.0`: el factor de relación de un evento de otra especialidad sale del documento de relaciones clínicas, y cada SIC del paciente suma el posible impacto de sus otras SIC abiertas (factor `otra_solicitud`, alerta `sic_duplicada` si coinciden especialidad y CIE-10). El documento de relaciones es un insumo estándar versionado en `data/conocimiento/relaciones-clinicas-vX.Y.Z.yaml` (carpeta configurable con `HLF_CONOCIMIENTO`). La versión actual es una plantilla sintética no validada, pendiente de reemplazo por el documento del HLF. En el dataset actual (una SIC por paciente) los resultados son idénticos a `reglas-v0.1.0`.

Escenario sintético de varias SIC del mismo paciente (`data/synthetic/escenario-multi-sic/`, versionado):

```powershell
uv run hlf-lote --fecha-corte 2026-08-10 --datos data/synthetic/escenario-multi-sic --salidas $env:TEMP\hlf-multi-sic\dos
# "antes", con una sola SIC: el lote lee perfiles.json, así que se copia la variante a otra carpeta
New-Item -ItemType Directory $env:TEMP\hlf-multi-sic\una-datos -Force | Out-Null
Copy-Item data\synthetic\escenario-multi-sic\perfiles-una-sic.json $env:TEMP\hlf-multi-sic\una-datos\perfiles.json
uv run hlf-lote --fecha-corte 2026-08-10 --datos $env:TEMP\hlf-multi-sic\una-datos --salidas $env:TEMP\hlf-multi-sic\una
```

## Cómo ejecutar el copiloto IA (U2)

Analiza con Amazon Bedrock las solicitudes que el lote dejó en `priorizacion` y guarda un análisis citado y validado, siempre pendiente de revisión médica. Usa la cadena estándar de credenciales de AWS y exige que existan las salidas de `hlf-lote` para cada fecha (si faltan, muestra los comandos y no llama a Bedrock). Trabaja sobre la versión de reglas por defecto (`reglas-v0.2.0`); con `--reglas` se elige otra.

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

Sin login: es una demo local con datos sintéticos y médicos ficticios (`app/config_demo.py`). Para usar otras carpetas: `HLF_SALIDAS` y `HLF_DATOS`. La barra lateral tiene un selector "Versión de reglas" con las versiones que tienen propuestas en el corte elegido (por defecto la más nueva). Los análisis del copiloto ya generados son de `reglas-v0.1.0`: para verlos, elija esa versión. Si un corte no tiene propuestas o análisis, la interfaz muestra el comando exacto (`uv run hlf-lote --fecha-corte AAAA-MM-DD`, `uv run hlf-copiloto --fecha-corte AAAA-MM-DD`).

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

## Escenario: agregar una nueva SIC a un paciente que ya está en espera (IC-HLF-90002)

Muestra la regla R11 de `reglas-v0.2.0`: dos SIC abiertas del mismo paciente se impactan en ambos sentidos. Se agrega a PAC-HLF-00002 (Cardiología adulto, I20, baja) una SIC ficticia de Cardiología / Insuficiencia cardíaca (I50, media), con ingreso el 2026-08-01.

**Escribir solo la fila en `lista_espera.csv` no basta.** El motor lee las solicitudes desde `perfiles.json`; el CSV se usa solo para conciliar. Con la fila solo en el CSV, IC-HLF-90002 no se evalúa y IC-HLF-00002 recibe un hallazgo `conciliacion_diferencias` (verificado). Hay que agregarla en los dos archivos y volver a correr el lote: la bandeja solo muestra lo que dejó `hlf-lote`.

**No modificar el dataset original ni `salidas/`.** El dataset del HLF es la referencia de todo lo demás, y las propuestas ya guardadas no se sobrescriben (el lote informaría conflictos para IC-HLF-00002). Se trabaja sobre una copia en `data/raw/` (no se versiona) y con salidas aparte (`salidas-escenario/`, tampoco se versiona).

**1. Copiar el dataset**

```powershell
. .\scripts\entorno-demo.ps1
Copy-Item -Recurse data\dataset_hlf_ambulatorio data\raw\escenario-90002
```

**2. Agregar la fila al final de `data\raw\escenario-90002\lista_espera.csv`** (UTF-8, mismas columnas que el encabezado):

```csv
PAC-HLF-00002,IC-HLF-90002,Cardiología,Insuficiencia cardíaca,I50,Insuficiencia cardíaca,media,2026-08-01,Hospitalización,en_espera
```

Columnas: `id_paciente, id_solicitud, especialidad, sub_especialidad, diagnostico_cie10, diagnostico_texto, prioridad_inicial, fecha_ingreso_lista, origen_derivacion, estado`.

**3. Agregar la misma solicitud en `data\raw\escenario-90002\perfiles.json`.** En el perfil `PAC-HLF-00002`, `lista_espera` es un objeto; se convierte en una lista con las dos solicitudes:

```json
"lista_espera": [
  { "...": "el objeto IC-HLF-00002 tal como estaba" },
  {
    "id_solicitud": "IC-HLF-90002",
    "especialidad": "Cardiología",
    "sub_especialidad": "Insuficiencia cardíaca",
    "diagnostico_cie10": "I50",
    "diagnostico_texto": "Insuficiencia cardíaca",
    "prioridad_inicial": "media",
    "fecha_ingreso_lista": "2026-08-01",
    "origen_derivacion": "Hospitalización",
    "estado": "en_espera"
  }
]
```

**4. Correr el lote en varias fechas de corte** (antes y después del ingreso de la nueva SIC):

```powershell
foreach ($f in "2026-07-20", "2026-07-31", "2026-08-01", "2026-08-10", "2026-10-13") {
  uv run hlf-lote --fecha-corte $f --datos data\raw\escenario-90002 --salidas salidas-escenario
}
```

**5. Abrir la bandeja sobre esas salidas** (solo después de los pasos 1 a 4; si las carpetas no existen, la bandeja dice que no hay cortes)

```powershell
$env:HLF_SALIDAS = "salidas-escenario"; $env:HLF_DATOS = "data\raw\escenario-90002"
uv run streamlit run app/bandeja.py
```

Elegir la versión `reglas-v0.2.0` en la barra lateral y comparar cortes en "¿Qué cambió?" (por ejemplo 2026-07-31 → 2026-08-01). En el Detalle de cada SIC aparece la otra SIC del paciente y el factor `otra_solicitud`.

Resultado verificado al 2026-08-10 (reglas-v0.2.0, documento de relaciones v0.1.0):

| | Sin IC-HLF-90002 | Con IC-HLF-90002 |
|---|---|---|
| IC-HLF-00002 (I20, baja) | 75,05 · crítica | 79,55 · crítica (+4,5 = 5 × 0,9 por la I50 media) |
| IC-HLF-90002 (I50, media) | — | 92,47 · crítica (incluye +2,7 = 3 × 0,9 por la I20 baja) |

Antes del 2026-08-01 la nueva SIC no existe para el motor (no hay fuga de información futura) y IC-HLF-00002 no cambia. La relación I20 ↔ I50 = 0,9 sale de `data/conocimiento/relaciones-clinicas-v0.1.0.yaml`, una plantilla sintética no validada clínicamente.

Ten en cuenta:
- Guarda los dos archivos en **UTF-8** (por ejemplo, desde el editor). Si agregas la fila con PowerShell 5.1, usa `[IO.File]::AppendAllText("data\raw\escenario-90002\lista_espera.csv", "<fila>`r`n", [Text.UTF8Encoding]::new($false))`; otros comandos pueden cambiar las tildes ("Cardiología") y la fila ya no coincide con el perfil, lo que produce un hallazgo `conciliacion_diferencias`. Con la fila bien escrita no aparece ese hallazgo (verificado).
- Las variables `HLF_SALIDAS` y `HLF_DATOS` valen solo en esa terminal. Para volver a la bandeja normal: `Remove-Item Env:HLF_SALIDAS, Env:HLF_DATOS -ErrorAction SilentlyContinue` (o abrir otra terminal).
- En este escenario no hay análisis del copiloto. Generarlos llama a Bedrock: `uv run hlf-copiloto --fecha-corte 2026-08-10 --datos data\raw\escenario-90002 --salidas salidas-escenario`.
- Para borrar el escenario: `Remove-Item -Recurse data\raw\escenario-90002, salidas-escenario`.
