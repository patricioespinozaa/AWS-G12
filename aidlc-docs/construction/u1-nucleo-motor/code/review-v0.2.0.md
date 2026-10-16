# reglas-v0.2.0: otras SIC del mismo paciente (R11) y documento de relaciones clínicas (R5.3)

El cambio hace que cada solicitud de un paciente reciba un aporte acotado de sus otras solicitudes abiertas (R11) y que el factor `r` de los eventos de otra especialidad salga de un documento de relaciones clínicas versionado y validado fail-closed (`data/conocimiento/relaciones-clinicas-v0.1.0.yaml`). `reglas-v0.2.0.yaml` es una copia de v0.1.0 más `relaciones` y `otras_solicitudes`; sin documento, el motor se comporta exactamente como v0.1.0. Los cuatro comandos del gate pasan en esta revisión, `reglas-v0.1.0.yaml` es byte a byte igual al commit, y el dataset real da el mismo resultado en 500 de 500 solicitudes salvo `version_reglas`.

Watch for: la bandeja abre el corte 2026-10-13 en v0.2.0, donde no hay análisis de Sonnet 5 (están en v0.1.0), y `hlf-copiloto --fecha-corte 2026-10-13` ahora apunta a v0.2.0 (likely: 500 llamadas nuevas a Bedrock si se corre sin `--reglas`). Los archivos de `data/` están sin versionar y el motor no arranca sin `data/conocimiento/` (confirmed).

**Verdict**: APPROVED

## High-level view

R5.3 y R11 viven en el motor puro y leen el documento desde `ParametrosReglas.documento_relaciones`, que solo puede llenar `cargar_parametros`; declararlo en el YAML se rechaza. La relación entre diagnósticos es simétrica por construcción (`frozenset`), la de especialidades es dirigida, y R11 no decae, respeta el tope de 10, trata como duplicadas a las SIC con la misma especialidad y CIE-10 (alerta `sic_duplicada` solo en la más reciente) y solo cuenta SIC con ingreso ≤ corte, filtradas en el repositorio y otra vez en el motor.

El documento falla cerrado: versión igual al nombre del archivo, factores en [0, 1], especialidades del catálogo, CIE-10 con formato válido, sin pares repetidos ({a,b} = {b,a} en diagnósticos y (de, a) en especialidades). Mientras no esté `validado`, una evaluación que lo usó lleva "relaciones clínicas no validadas" y no puede quedar en `alta`. El motivo se agrega solo cuando el documento intervino, no en todas las evaluaciones como dice la letra del diseño (confirmed). Así el dataset real queda igual también en la confianza.

La bandeja tiene un selector `lateral-version` con las versiones que tienen propuestas en el corte, ordenadas por semver y con la más nueva por defecto. Para 2026-10-13 eso significa abrir sin análisis IA (likely, tema de producto). El Detalle muestra las otras SIC y el estado del documento.

<details>
<summary>Issues (5)</summary>

1. **Archivos de data/ sin versionar** — `data/conocimiento/relaciones-clinicas-v0.1.0.yaml` y `data/synthetic/escenario-multi-sic/*.json` están sin rastrear (`?? data/`, confirmed). Sin el documento, v0.2.0 (la versión por defecto) detiene el lote. Hay que incluirlos en el commit.
2. **Bandeja y copiloto en 2026-10-13** — por defecto se abre v0.2.0 sin análisis de Sonnet 5, y `hlf-copiloto --fecha-corte 2026-10-13` sin `--reglas` volvería a llamar a Bedrock por 500 propuestas (likely). Hay que confirmar con el usuario si se re-corre el copiloto sobre v0.2.0 o si la bandeja prefiere la versión que tiene análisis.
3. **Diseño desalineado con lo implementado** — business-rules.md dice "cada evaluación lleva el motivo" y cita PAC-HLF-00002 (75,05 → 79,55). El código agrega el motivo solo cuando se usó el documento, y el escenario reproducible es PAC-SIN-00001 (79,85 → 84,35). (confirmed) Hay que actualizar el texto del diseño para que coincida.
4. **Ruta del documento ligada al checkout** — `DIRECTORIO_CONOCIMIENTO` usa `parents[3]` de `relaciones.py` y solo resuelve en un checkout o una instalación editable (likely). En U4 (contenedor o wheel) hay que fijar `HLF_CONOCIMIENTO` o empaquetar el documento. Mientras tanto falla cerrado, sin resultados incorrectos.
5. **Marca de duplicado en el Detalle ignora R11.1** — `bandeja.datos.otras_solicitudes()` lista y marca como "posible duplicado" también las SIC que el motor descartó por R3 (atendida o atendido inferido), confirmed. Conviene aplicar la misma vigencia que el motor o rotular las no vigentes.

</details>

<details>
<summary>Details</summary>

### Gate: los cuatro comandos

Se corrieron desde la raíz, después de `. .\scripts\entorno-demo.ps1`, sin `-m bedrock`. `uv run ruff check`: All checks passed. `uv run mypy src`: Success, no issues found in 46 source files. `uv run pytest`: 337 passed, 1 deselected (el de Bedrock), 93,5 s. `uv run pip-audit`: No known vulnerabilities found; solo se omite el paquete local `hlf-priorizacion`, que no está en PyPI. Todos terminaron con exit 0 y coinciden con lo que informa `resumen-v0.2.0.md`. No se hizo ninguna llamada a Bedrock.

### R5.3 y R11 en el motor, contra la sección "Cambio reglas-v0.2.0"

En `_factores_eventos`, la misma especialidad usa 1,0. Otra especialidad con documento usa `doc.factor_especialidad(de=evento, a=solicitud)`, que es dirigido, cae en `por_defecto_otra_especialidad` (0,5) y deja el factor y la versión en el detalle. Sin documento se mantiene el `r` fijo de v0.1.0. Pasa.

`_otras_solicitudes` implementa R11.1 a R11.7. Cumple todas las propiedades:

- **Simetría:** `factor_diagnosticos` compara `frozenset({a, b})`, así que `rel(A, B) == rel(B, A)`. Cada lado usa la prioridad inicial de la otra SIC.
- **Sin decaimiento:** el aporte es `peso[prioridad_B] × rel`, sin término temporal.
- **Tope:** se recorta en orden (ingreso, id) hasta 10. Lo cubren `test_tope_de_10_recorta_el_ultimo_aporte` (7,2 + 2,8) y la propiedad con 3 SIC.
- **Duplicados:** misma especialidad y mismo CIE-10 dan `continue` sin aporte en ambos sentidos. La alerta va solo a la más reciente según (`fecha_ingreso_lista`, `id_solicitud`). Varias duplicadas van en una sola alerta.
- **Sin fuga futura:** `contexto_a_fecha` filtra las SIC con ingreso ≤ corte y `_vigente_al_corte` lo vuelve a comprobar.
- **Exclusiones R3:** R3.2 y R3.3 reutilizan `cita_egreso_inferido`, la misma función que usa el contexto.
- **Valores por defecto de `rel`:** misma especialidad sin par da 0,5, otra especialidad sin par da 0,0, y `rel ≤ 0` no genera factor.
- **Fórmula:** el puntaje queda `… + min(10, otras)` acotado a [0, 100]. R6 no cambia.

El oráculo de `referencia.py` reimplementa lo mismo de forma independiente (bucle sobre pares, suma con tope) y `test_motor_coincide_con_la_referencia_con_varias_sic` lo compara con el motor.

Confianza: `no_validadas = doc no validado y (algún evento usó el documento o hay factores otra_solicitud)`. Ese caso agrega el motivo e impide `alta` (máximo `media`). Es una lectura condicional de "cada evaluación lleva el motivo" (confirmed, issue 3). Es la que permite que los 6 casos de referencia y el dataset real no cambien, como pide el mismo diseño.

### Carga fail-closed del documento

`RelacionesClinicas` usa pydantic estricto con `extra="forbid"`. Las validaciones son:

- **Factores:** `FactorRelacion` en [0, 1], también para los valores por defecto.
- **Especialidades:** las de los pares tienen que estar en `ESPECIALIDADES_CATALOGO`; un par consigo misma se rechaza.
- **CIE-10:** formato con `PATRON_CIE10`.
- **Pares repetidos:** en diagnósticos se compara `frozenset`, así que {a,b} y {b,a} cuentan como repetidos y {a,a} se rechaza; en especialidades se compara (de, a).
- **Estado:** `estado` es un Literal.
- **Versión:** tiene que coincidir con `ruta.stem`.

`cargar_parametros` traduce `ErrorRelaciones` a `ErrorParametros`. Rechaza `documento_relaciones` en el YAML y exige que `relaciones` y `otras_solicitudes` vayan juntas. `test_relaciones.py` cubre cada caso inválido, el archivo ausente y la versión distinta. Pasa.

### reglas-v0.1.0 intacta y dataset real sin cambios

`git rev-parse HEAD:…/reglas-v0.1.0.yaml` y `git hash-object` del archivo dan `a1d8b3a90ab80de4d065ec96526b559eec7d5946`, y `git diff --quiet` sale con 0. El SHA-256 del blob extraído con `git cat-file` y el del archivo de trabajo son idénticos (`CBCBE6A8…0ECE`), así que es byte a byte igual.

Para el corte 2026-10-13 se compararon `propuestas.parquet` de v0.1.0 y v0.2.0. Las dos tienen 500 filas con los mismos IDs. Entre columnas, solo difieren `version_reglas` (500) y `evaluacion_json` (500). Dentro de `evaluacion_json`, excluyendo `version_reglas`, la diferencia en campos es 0. `puntaje` coincide en 500 de 500 (409 numéricos, suma 22 493,44, mínimo 13,82, máximo 100,0; 91 son None por exclusión), y `nivel_propuesto` también coincide en 500 de 500 (alta 153, media 138, baja 94, crítica 24, None 91). Hay 0 factores `otra_solicitud`, 0 alertas `sic_duplicada` y 0 motivos de relaciones no validadas. Pasa.

### Particiones v0.1.0 en salidas/

`salidas/` está en `.gitignore`, así que git no sirve para comprobarlo. Se revisaron las fechas de modificación. Los 26 archivos `reglas-v0.1.0` y `hallazgos_dq` tienen como última escritura 2026-10-16T02:44:08, antes de que se creara `relaciones.py` (07:44). La única corrida posterior (08:07:36) escribió solo particiones `reglas-v0.2.0` (propuestas, resumen, cohortes). Los hashes de antes del cambio no se pudieron recalcular, pero ningún archivo v0.1.0 se tocó después de que empezó el cambio. Pasa. Las verificaciones de esta revisión escribieron solo en `%TEMP%` y no cambiaron ninguna fecha de modificación de `salidas/`.

### Escenario sintético reproducido con el CLI

Se corrió `hlf-lote --fecha-corte 2026-08-10` sobre carpetas temporales, ya borradas. Resultados:

- **Una SIC:** IC-SIN-00001 da 79,85.
- **Dos SIC:** IC-SIN-00001 da 84,35, con `otra_solicitud` 4,5 = 5 × 0,9, `ids_registro=["IC-SIN-00002"]` y detalle "I50 (Insuficiencia cardíaca, prioridad inicial media), relación 0.9". IC-SIN-00002 da 97,27, con `otra_solicitud` 2,7 = 3 × 0,9 citando IC-SIN-00001.
- **Evento EV-900002:** en las tres evaluaciones aporta 6,63, con detalle "relación Endocrinología → Cardiología 0.7 según relaciones-clinicas-v0.1.0".
- **Confianza:** `media` en las tres, con motivos ["sin mediciones en los últimos 30 días", "relaciones clínicas no validadas"]. Con `--reglas reglas-v0.1.0.yaml`, la misma SIC da 77,96 y confianza `alta`, así que el documento es lo que baja la confianza.
- **Variante duplicada:** cambiando IC-SIN-00002 a I20, misma especialidad y otra subespecialidad, ninguna de las dos tiene factores `otra_solicitud`. IC-SIN-00001 da 79,85 sin alerta. IC-SIN-00002 da 94,57 con `sic_duplicada` [IC-SIN-00001].

Todo coincide con `resumen-v0.2.0.md`. Pasa.

El diseño cita PAC-HLF-00002 del dataset real, con 75,05 → ≈ 79,55 y 89,77 → ≈ 92,47. El escenario versionado es sintético porque el dataset del hospital no se versiona. Los aportes (+4,5 y +2,7) son los mismos y solo cambia la base (issue 3).

### Selector de versión en la bandeja

Se usó Streamlit AppTest sobre una copia temporal de las salidas reales de 2026-10-13, con `HLF_SALIDAS` en `%TEMP%` y el dataset real en solo lectura. El corte por defecto es 2026-10-13. `lateral-version` ofrece `["reglas-v0.2.0", "reglas-v0.1.0"]` y arranca en `reglas-v0.2.0`. Al elegir `reglas-v0.1.0` no hay excepciones. `test_selector_de_version_por_defecto_la_mas_nueva` cubre también un corte que solo tiene v0.2.0. El orden usa la tupla semver (`_clave_version`), no texto, así que v0.10.0 queda sobre v0.2.0. Pasa.

El costo es de producto (likely, issue 2). Los análisis de Sonnet 5 para 2026-10-13 están en la partición v0.1.0, así que el usuario que abre la bandeja ve "Análisis IA pendiente" en las 500 hasta que cambie el selector. La salida obvia, correr el copiloto sobre v0.2.0, implica 500 llamadas a Bedrock.

La tabla de otras SIC del Detalle calcula `duplicada` solo por especialidad y CIE-10 y lista todas las `ctx.otras_solicitudes`, sin aplicar la vigencia R11.1 del motor (confirmed, issue 5). Una SIC atendida al corte aparece y puede quedar marcada "posible duplicado" aunque el motor la haya ignorado y no haya emitido `sic_duplicada`.

### Despliegue y versionado del insumo

`relaciones.py` resuelve `data/conocimiento/` como `Path(__file__).resolve().parents[3]` (likely, issue 4). Eso funciona en el checkout con `uv run`, pero en un wheel instalado o en una imagen de U4 apunta fuera del paquete. El fallo es cerrado (el lote se detiene con `ErrorParametros`) y existe `HLF_CONOCIMIENTO` para corregirlo, pero U4 lo tiene que tener en cuenta.

Además, `git status` muestra `data/` completo sin rastrear (confirmed, issue 1). `.gitignore` no excluye `data/conocimiento/` ni `data/synthetic/**/*.json`, así que basta con agregarlos al commit. Sin ellos, un clon nuevo no puede correr la versión por defecto y fallan `test_relaciones.py`, `test_multi_sic.py` y las propiedades multi-SIC.

</details>

<details>
<summary>Archivos cambiados</summary>

- `src/hlf_priorizacion/motor/relaciones.py` (nuevo): modelos y carga fail-closed del documento.
- `src/hlf_priorizacion/motor/reglas/reglas-v0.2.0.yaml` (nuevo): v0.1.0 + `relaciones` + `otras_solicitudes`.
- `data/conocimiento/relaciones-clinicas-v0.1.0.yaml` (nuevo, sin rastrear): plantilla sintética no validada.
- `data/synthetic/escenario-multi-sic/` (nuevo, sin rastrear): escenario con dos SIC y variante con una.
- `motor/evaluar.py`: R5.3 desde el documento, R11, alerta `sic_duplicada`, límite de confianza.
- `motor/parametros.py`: versión por defecto v0.2.0, campos nuevos y carga del documento.
- `motor/referencia.py`: oráculo con R5.3 y R11.
- `repositorio/contexto.py`: `cita_egreso_inferido` compartida.
- `modelos.py`, `contrato/catalogos.py`: `otra_solicitud` y `ESPECIALIDADES_CATALOGO`.
- `bandeja/datos.py`, `app/bandeja.py`: selector de versión, otras SIC y estado del documento en el Detalle.
- `ingesta/normalizacion.py`: solo un comentario.
- `docs/contexto-tecnico.md`, `README.md`, `CLAUDE.md`, `business-rules.md`, `bitacora-parametros.md`: documentación.
- Pruebas: `test_multi_sic.py`, `test_relaciones.py`, `test_prop_motor_multi_sic.py` (nuevas); las que fijaban v0.1.0 pasan a `VERSION_POR_DEFECTO` o quedan parametrizadas.

Diff completo: `git diff HEAD` más los archivos sin rastrear de `git status --short -uall`.

</details>
