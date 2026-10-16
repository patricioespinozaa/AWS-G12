# Resumen del cambio reglas-v0.2.0 (U1, con ajustes en U3)

Diseño: sección "Cambio reglas-v0.2.0" de `functional-design/business-rules.md`. Bitácora: `bitacora-parametros.md`.

## Archivos

Creados:

| Archivo | Contenido |
|---|---|
| `src/hlf_priorizacion/motor/relaciones.py` | Modelos y carga fail-closed del documento de relaciones (`cargar_relaciones`, `factor_especialidad`, `factor_diagnosticos`). Carpeta `data/conocimiento/` o `HLF_CONOCIMIENTO` |
| `src/hlf_priorizacion/motor/reglas/reglas-v0.2.0.yaml` | Copia de v0.1.0 + `relaciones: relaciones-clinicas-v0.1.0` + `otras_solicitudes` (alta 8, media 5, baja 3, tope 10) |
| `data/synthetic/escenario-multi-sic/perfiles.json` | PAC-SIN-00001 con IC-SIN-00001 (I20, baja) e IC-SIN-00002 (I50, media, ingreso 2026-08-01) |
| `data/synthetic/escenario-multi-sic/perfiles-una-sic.json` | Variante "antes", solo IC-SIN-00001 |
| `tests/ejemplos/test_multi_sic.py` | Escenario antes/después, duplicado, tope, vigencia, lote e idempotencia |
| `tests/ejemplos/test_relaciones.py` | Validación fail-closed del documento y de reglas-v0.2.0 |
| `tests/propiedades/test_prop_motor_multi_sic.py` | Las 7 propiedades nuevas del diseño + oráculo motor = referencia con varias SIC + confianza |

Modificados:

| Archivo | Cambio |
|---|---|
| `motor/parametros.py` | `VERSION_POR_DEFECTO = "reglas-v0.2.0"`; campos opcionales `relaciones`, `otras_solicitudes`, `documento_relaciones` (lo llena `cargar_parametros`; prohibido en el YAML); deben ir juntos |
| `motor/evaluar.py` | R5.3 desde el documento; R11 (`_otras_solicitudes`, vigencia R11.1, duplicados con alerta `sic_duplicada`, tope); motivo "relaciones clínicas no validadas" y confianza máx. `media`. Sin documento, comportamiento v0.1.0 |
| `motor/referencia.py` | Oráculo independiente con R5.3 del documento y R11 |
| `modelos.py` | `TipoFactor` += `otra_solicitud` (sin campos nuevos: la huella no cambia) |
| `contrato/catalogos.py` | `ESPECIALIDADES_CATALOGO` (las 7 del dataset) |
| `repositorio/contexto.py` | `cita_egreso_inferido` compartido por el contexto (R3.3) y el motor (R11.1); comentario de no fuga en `otras_solicitudes` |
| `ingesta/normalizacion.py` | Comentario: la especialidad de respaldo de eventos es la de la primera SIC |
| `bandeja/datos.py`, `app/bandeja.py` | Selector `lateral-version` (versiones con propuestas del corte, por defecto la más nueva); "¿Qué cambió?" usa la versión elegida; Detalle con otras SIC (ID, especialidad, subespecialidad, CIE-10, prioridad inicial, ingreso, marca de duplicado) y versión/estado del documento con aviso si no está validado |
| `docs/contexto-tecnico.md` | 6.2 fórmula, 6.3 relación y R5.10, nueva 6.3.1 (R11), 6.7 `sic_duplicada`, fila de la sección 7 corregida |
| `README.md`, `CLAUDE.md` | Versión por defecto, insumo estándar, comando del escenario |
| Pruebas | Ver "Pruebas que fijaban reglas-v0.1.0" |

`reglas-v0.1.0.yaml` y `relaciones-clinicas-v0.1.0.yaml` no cambiaron (blob de v0.1.0: `a1d8b3a9…`, `git diff` vacío).

## Cómo correr el escenario

```powershell
. .\scripts\entorno-demo.ps1
uv run hlf-lote --fecha-corte 2026-08-10 --datos data/synthetic/escenario-multi-sic --salidas $env:TEMP\hlf-multi-sic\dos-sic\salidas
New-Item -ItemType Directory $env:TEMP\hlf-multi-sic\una-sic\datos -Force | Out-Null
Copy-Item data\synthetic\escenario-multi-sic\perfiles-una-sic.json $env:TEMP\hlf-multi-sic\una-sic\datos\perfiles.json
uv run hlf-lote --fecha-corte 2026-08-10 --datos $env:TEMP\hlf-multi-sic\una-sic\datos --salidas $env:TEMP\hlf-multi-sic\una-sic\salidas
```

`hlf-lote` siempre lee `perfiles.json`, por eso la variante va a otra carpeta. No hay CSV: sin tablas no hay conciliación (aviso `tablas no disponibles para conciliar`, sin hallazgo `verificar`).

## Antes / después (lote real del CLI, corte 2026-08-10, reglas-v0.2.0)

Ambas corridas: cobertura 100 %, exit 0. Una SIC: 1 evaluada. Dos SIC: 2 evaluadas, 2 `priorizacion`.

| Factor | IC-SIN-00001 antes (1 SIC) | IC-SIN-00001 después (2 SIC) | IC-SIN-00002 (2 SIC) |
|---|---|---|---|
| base | 20,00 | 20,00 | 40,00 |
| evento EV-900001 triage ESI 2, hace 21 d | 13,61 | 13,61 | 13,61 |
| evento EV-900002 descompensación (Endocrinología), hace 7 d, r = 0,7 | 6,63 | 6,63 | 6,63 |
| evento EV-900003 ingreso hospitalario, hace 4 d | 17,45 | 17,45 | 17,45 |
| aceleración | 5,00 | 5,00 | 5,00 |
| medicion_zona PAS 158 | 3,88 | 3,88 | 3,88 |
| medicion_brusco | 4,00 | 4,00 | 4,00 |
| medicion_tendencia | 4,00 | 4,00 | 4,00 |
| espera | 5,28 (275 d, plazo 180) | 5,28 | 0,00 (9 d, plazo 90) |
| otra_solicitud | — | **4,50** (I50 media: 5 × 0,9, cita IC-SIN-00002) | **2,70** (I20 baja: 3 × 0,9, cita IC-SIN-00001) |
| **Puntaje** | **79,85** | **84,35** | **97,27** |
| Nivel calculado / propuesto | alta / crítica | alta / crítica | alta / crítica |
| Confianza | media | media | media |

- Bandera `BR_EVENTO_GRAVE_30D` (EV-900001, EV-900003) en los tres: el nivel propuesto ya era crítica, R11 solo sube el puntaje.
- Motivos de confianza en los tres: "sin mediciones en los últimos 30 días" y "relaciones clínicas no validadas". Con reglas-v0.1.0 la misma solicitud da 77,96, confianza `alta`: la diferencia es el evento de Endocrinología (4,74 con r = 0,5 → 6,63 con r = 0,7) y la confianza limitada por el documento no validado.
- IC-SIN-00002 sin R11 sería 94,57.
- Variante duplicada (IC-SIN-00002 con I20; prueba `test_duplicada_no_aporta_y_alerta_en_la_mas_reciente`): 0 factores `otra_solicitud` en ambas y alerta `sic_duplicada` [IC-SIN-00001] solo en IC-SIN-00002 (la más reciente).
- Re-ejecución del lote de dos SIC: 0 nuevas, 2 ya existentes, 0 conflictos (idempotente con 2 SIC de un paciente; `perfil_de_solicitud` y las claves por `id_solicitud` funcionan).

## Comparación con el dataset real (corte 2026-10-13)

`uv run hlf-lote --fecha-corte 2026-10-13` (por defecto v0.2.0): 500 perfiles válidos, 500 evaluadas, cobertura 100 % (500/500), exit 0; tipos `exclusion` 91, `gestion` 89, `priorizacion` 125, `sin_alerta` 195.

Contra las propuestas v0.1.0 existentes: 500 = 500 IDs; diferencias de `puntaje` 0, `nivel_propuesto` 0, `nivel_calculado` 0, `tipo_resultado` 0, `confianza` 0, `huella_contexto` 0; evaluaciones completas distintas salvo `version_reglas`: **0**. Ningún factor `otra_solicitud` (una SIC por paciente) ni eventos de otra especialidad. Las 26 particiones/archivos `reglas-v0.1.0` y `hallazgos_dq` de `salidas/` tienen el mismo hash antes y después.

Los 6 casos de referencia (`tests/ejemplos/test_casos_referencia.py`, 12 pruebas) corren parametrizados con v0.1.0 y v0.2.0 y pasan con ambas; el fixture de la sección 6.8 coincide salvo `version_reglas`.

## Verificación

Desde la raíz, tras `. .\scripts\entorno-demo.ps1`:

| Comando | Resultado |
|---|---|
| `uv run ruff check` | All checks passed |
| `uv run mypy src` (strict) | Success: no issues found in 46 source files |
| `uv run pytest` | **337 passed, 1 deselected** (bedrock); antes 286 passed. +51: test_multi_sic 11, test_relaciones 12, propiedades multi-SIC 11, casos de referencia ×2 versiones +12, bandeja +3, interfaz +2 |
| `uv run pip-audit` | No known vulnerabilities found (solo se omite el propio paquete local) |

No se llamó a Bedrock ni se corrió `hlf-copiloto`. Las pruebas escriben solo en carpetas temporales; las únicas escrituras en `salidas/` reales son las de la corrida 2026-10-13 (partición nueva `version_reglas=reglas-v0.2.0`, más líneas en `auditoria/eventos.jsonl`).

Cobertura de las estrategias (60 ejemplos, perfil `ci`): 41 de 60 perfiles con 2–3 SIC evaluadas, 84 factores `otra_solicitud`, 6 alertas `sic_duplicada`, 91 evaluaciones con el motivo de relaciones no validadas. El tope se cubre con la prueba de ejemplo `test_tope_de_10_recorta_el_ultimo_aporte` (7,2 + 2,8).

## Pruebas que fijaban reglas-v0.1.0 (actualizadas a propósito)

- `tests/ejemplos/test_copiloto.py`, `tests/ejemplos/test_copiloto_interrupcion.py`, `tests/estrategias/bandeja.py`, `tests/propiedades/test_prop_copiloto.py`, `tests/ejemplos/test_lote.py`: la versión del lote de prueba pasa a `VERSION_POR_DEFECTO`.
- `tests/ejemplos/test_casos_referencia.py`: parametrizado con ambas versiones.
- `tests/ejemplos/test_bandeja.py`: el recorrido con las salidas reales de 07-19/20 pide explícitamente `reglas-v0.1.0` (`V_DEMO`), que es donde están los análisis del copiloto.

## Decisiones y desvíos

- **Huella de contexto:** no se agregaron campos a `ContextoPaciente` ni a `SolicitudContexto`. La vigencia de la otra SIC (R11.1) se calcula en el motor con `estado_extraccion`, las citas del contexto y la fecha de extracción, con la misma función que usa el contexto para R3.3. Así las huellas no cambian y las salidas v0.1.0 siguen verificando en U2 y U3 (comprobado: 0 diferencias de huella en 500).
- **Sin fuga futura:** el repositorio ya entregaba solo SIC con ingreso ≤ corte; el motor además lo vuelve a filtrar (propiedad `test_sic_con_ingreso_posterior_al_corte_no_aporta` cubre ambos niveles).
- **"Usó el documento"** = algún evento de otra especialidad (par listado o valor por defecto del documento) o algún factor `otra_solicitud`. El motivo solo se agrega en ese caso, no en todas las evaluaciones: por eso el dataset real no cambia ni en confianza.
- **rel = 0** (otra especialidad sin par) no genera factor; tampoco los duplicados.
- **Varias duplicadas** de la misma SIC van en una sola alerta `sic_duplicada` con todos los IDs más antiguos.
- `eventos.relacion_otra_especialidad` se conserva en v0.2.0 (copia de v0.1.0) pero no se usa cuando hay documento; queda comentado en el YAML.
- CIE-10: coincidencia exacta del código (el dataset usa 3 caracteres). No se agrupa I20.9 con I20.
- La especialidad de respaldo de eventos sin especialidad en `detalle` sigue siendo la de la primera SIC (marcada `especialidad_evento_inferida`).
- Bandeja: con v0.2.0 no hay análisis del copiloto; se muestra "Análisis IA pendiente" como hoy. Para 2026-10-13 la bandeja abre por defecto en v0.2.0; los análisis de Sonnet 5 están en v0.1.0 (seleccionable).
- Copiloto: sin cambios de lógica ni de prompts. Ojo: `uv run hlf-copiloto --fecha-corte 2026-10-13` ahora trabaja sobre v0.2.0 y volvería a llamar a Bedrock por esas propuestas; para seguir con v0.1.0, `--reglas src/hlf_priorizacion/motor/reglas/reglas-v0.1.0.yaml`.

## Preguntas abiertas para el equipo clínico (T3)

1. Reemplazar la plantilla por el documento del HLF: pares de especialidades (dirigidos) y de diagnósticos (simétricos), con sus factores.
2. ¿Pesos 8/5/3 y tope 10 para otras SIC? ¿Debe decaer el aporte de una SIC muy antigua?
3. Sin par, misma especialidad = 0,5 y otra especialidad = 0: ¿correcto?
4. Duplicado = misma especialidad y CIE-10 aunque cambie la subespecialidad: ¿se confirma? ¿Agrupar por categoría CIE-10 (I20 vs I20.9)?
5. ¿Una SIC `egresado` o `citado` debe dejar de aportar? Hoy solo se excluyen las de R3 (fallecido, atendido, atendido inferido).
6. Cuando hay varias SIC de la misma especialidad, una cita `asistio` de esa especialidad infiere el egreso de cualquiera que figure `atendido` en la extracción: ¿hace falta vincular la cita a una SIC concreta?
