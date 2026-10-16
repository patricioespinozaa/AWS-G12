# U2 — Copiloto (modo barrido): resumen de código

## Archivos

| Archivo | Contenido |
|---|---|
| `src/hlf_priorizacion/copiloto/config.py` | `ConfigModelo` desde `HLF_BEDROCK_MODEL_ID` (lista permitida), `HLF_COPILOTO_CONCURRENCIA` (1–8, por defecto 4), `HLF_BEDROCK_REGION`; timeout 60 s; `max_tokens` 8192; temperatura 0 solo para los modelos que la aceptan |
| `copiloto/prompts/copiloto-v1.0.0/`, `copiloto-v1.1.0/`, `copiloto-v1.2.0/` | `sistema.md` y `usuario.md` en español. v1.1.0 exige IDs en todo hallazgo `documentado` y hace obligatoria `nota_preconsulta`. v1.2.0 (por defecto, E-1 = C) agrega: no mencionar comuna, previsión ni NSE, e inasistencias solo como riesgo de no asistir o perder el seguimiento; su `usuario.md` es igual al de v1.1.0. v1.0.0 y v1.1.0 byte a byte sin cambios (sus huellas coinciden con las de los 74 y 21 análisis guardados; lo verifica una prueba) |
| `copiloto/prompt.py` | Carga de una versión, huella SHA-256 de ambos textos |
| `copiloto/fechas.py` | ISO estricto y reglas C2.3 |
| `copiloto/seleccion.py` | Plan puro por corte: `pendiente` / `omitida(motivo)`, `sin_cambio_en_rango`, `ya_analizada`, tope, salidas del lote faltantes con los comandos `hlf-lote` exactos |
| `copiloto/modelos.py` | `PaqueteBarrido`, `Correccion` (incluye `revision_equidad`), `FraseRevisionEquidad`, `RegistroAnalisis` (con `temperatura_enviada` y la marca del sistema `revision_equidad`, lista vacía por defecto para los registros anteriores), `AnalisisFallido` |
| `copiloto/paquete.py` | Reconstrucción del contexto con verificación de huella (`huella_distinta`), render JSON dentro de `<datos_clinicos>` (con `<` escapado), registros `descartar` marcados como error de registro |
| `copiloto/cliente.py` | `ClienteModelo`, `ClienteBedrock` (Converse, herramienta `registrar_analisis` = `analisis-v1` sin `metadatos`, `toolChoice` forzado), reintentos con espera exponencial y jitter, clasificación de errores (exit 4 con sugerencia del modelo de respaldo), `ClienteFalso` |
| `copiloto/validacion.py` | C6.1–C6.6 puras, con correcciones registradas. C6.5 determinista sin negaciones (E-1 = C): listas en `EQUIDAD_TERMINOS`; `atributo_no_disponible()` (regla 1, rechazo `equidad_atributo_no_disponible`) y `frases_revision_equidad()` (regla 2, marca) |
| `copiloto/barrido.py` | Orquestación: `ThreadPoolExecutor`, corte de circuito (>20 % de 10), un reintento de validación, escritura y auditoría incrementales por solicitud bajo un candado (C5.4) y Ctrl+C ordenado (C4.8, exit 130); `analisis_ia` lleva `revision_equidad` = cantidad de oraciones marcadas (nunca su texto) |
| `copiloto/persistencia.py` | `analisis.jsonl` / `fallidos.jsonl` (solo agregado), `copiloto_io/` (E/S completa por huella), `leer_analisis()` para U3 (expone `revision_equidad`: U3 debe mostrar una advertencia si no está vacía) |
| `copiloto/cli.py` | `hlf-copiloto`; códigos 0/1/2/3/4/130 (130 = Ctrl+C; 4 también para un modelo fuera de la lista local); `--max-llamadas` = presupuesto de invocaciones reales |
| Cambios en U1 | `auditoria/registro.py`: tipo `analisis_omitido`; `logs.py`: campos permitidos de U2 (IDs, tokens, latencia, códigos) |
| `pyproject.toml` / `uv.lock` | `boto3==1.43.114`, `botocore==1.43.114`, dev `boto3-stubs[bedrock-runtime]==1.43.114`; script `hlf-copiloto`; marcador `bedrock` excluido por defecto |
| `tests/estrategias/copiloto.py` | Paquetes, cohortes, respuestas del modelo (válidas, IDs inventados, documentado sin IDs, cifras distintas, malformadas, atributo no disponible, inasistencias con bajada), frases de C6.5 generadas (mayúsculas y tildes al azar, relleno y negaciones al azar), pares de fechas, lote en carpetas temporales |
| `tests/propiedades/test_prop_copiloto.py` | Las 14 propiedades (incluye oráculo secuencial/paralelo y máquina de estados del corte de circuito), más P15 (invocaciones ≤ presupuesto y un solo estado por solicitud) y P16a/b/c de C6.5 (atributo no disponible siempre se rechaza; inasistencia + bajada siempre se marca, con cualquier negación; validar dos veces = una y la marca no cambia los campos del modelo) |
| `tests/ejemplos/test_copiloto.py` | CLI extremo a extremo e idempotencia, rango con `sin_cambio_en_rango` y `--forzar`, cada error de C2.3, lote faltante, tope, huella distinta, permisos, reintentos, temperatura, D-1, idempotencia entre versiones de prompt, IC-HLF-00002 con cliente falso |
| `tests/ejemplos/test_copiloto_interrupcion.py` | Persistencia incremental y Ctrl+C (defecto 13): interrupción simulada con `vigia`, caída a mitad del barrido, espera acotada, re-ejecución que sigue |
| `tests/integracion/test_bedrock_real.py` | `@pytest.mark.bedrock`: IC-HLF-00002 al 2026-08-10 contra Bedrock real |

## Cómo ejecutar

```powershell
. .\scripts\entorno-demo.ps1
uv run hlf-lote --fecha-corte 2026-07-19          # el copiloto exige las salidas del lote de cada fecha
uv run hlf-copiloto --fecha-corte 2026-08-10
uv run hlf-copiloto --desde 2026-07-19 --hasta 2026-07-21 [--forzar] [--max-llamadas 300]
$env:HLF_BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"   # respaldo
uv run pytest -m bedrock -s                      # prueba real (consume tokens)
```

Resultados: `salidas/analisis/fecha_corte=…/version_reglas=…/analisis.jsonl` y `fallidos.jsonl`; E/S del modelo en `salidas/copiloto_io/`; eventos en `salidas/auditoria/eventos.jsonl`.

## Verificación (2026-10-15/16, comandos y resultados reales)

| Comando | Resultado |
|---|---|
| `uv run ruff check` | All checks passed (exit 0) |
| `uv run mypy src` | Success: no issues found in 39 source files |
| `uv run pytest` | 166 passed, 1 deselected (bedrock); las 107 de U1 siguen verdes |
| `uv run pip-audit` | No known vulnerabilities found (solo se salta el propio paquete local) |
| **Tras las correcciones de la revisión (2026-10-16), mismos comandos tras `. .\scripts\entorno-demo.ps1`:** | |
| `uv run ruff check` | All checks passed (exit 0) |
| `uv run mypy src` | Success: no issues found in 39 source files |
| `uv run pytest` | **183 passed, 1 deselected** (bedrock) en 47,6 s: las 166 anteriores + 17 nuevas (P15 presupuesto, P16/P16b negación por cláusula, 4 de ejemplo: presupuesto agotado a mitad y re-ejecución, peor caso sin abortar, `contexto_no_disponible`, modelo fuera de lista con exit 4; 10 frases nuevas de C6.5). No se llamó a Bedrock |
| `uv run pip-audit` | No known vulnerabilities found (solo se salta el propio paquete local) |
| C6.5 sobre los 95 análisis guardados (`motivo_prohibido`, solo lectura de `salidas/`) | 0 rechazados con la regla nueva |
| **Tras la re-revisión (`review-fixes.md`, 2026-10-16T01:59Z), mismos comandos tras `. .\scripts\entorno-demo.ps1`:** | |
| `uv run ruff check` | All checks passed (exit 0) |
| `uv run mypy src` | Success: no issues found in 39 source files (exit 0) |
| `uv run pytest` | **194 passed, 1 deselected** (bedrock) en 48,2 s (exit 0): las 183 anteriores + 11 nuevas (10 frases de C6.5: "sin <atributo>" y "no solo/sólo/solamente/únicamente" rechazadas, 2 negaciones con verbo de uso aceptadas; 1 de ejemplo con `threading.Barrier`: 3 llamadas abiertas a la vez agotan B = 3, la cuarta no llega al cliente y las tres terminan). P16 genera además las formas "sin {a}" y "no solo por {a}". No se llamó a Bedrock |
| `uv run pip-audit` | No known vulnerabilities found (exit 0; solo se salta el propio paquete local) |
| C6.5 sobre los 95 análisis guardados (solo lectura, imprime solo IDs) | 0 rechazados con la regla ajustada |
| **C6.5 reemplazada (decisión E-1 = C, 2026-10-16T02:27Z). Desde la raíz, tras `chcp 65001` y `. .\scripts\entorno-demo.ps1`:** | |
| `uv run ruff check` | All checks passed! (exit 0) |
| `uv run mypy src` | Success: no issues found in 39 source files (exit 0) |
| `uv run pytest` (marcadores por defecto, sin `-m bedrock`) | **205 passed, 1 deselected** (bedrock) en 51,8 s (exit 0). Se quitaron 28: `test_motivo_prohibido_respeta_la_negacion` (26 casos que afirmaban la negación por cláusula), `test_p16_negacion_ajena_no_oculta_un_motivo_prohibido` y `test_p16b_motivo_negado_directamente_se_acepta`. Se agregaron 39: `test_c65_regla_determinista_sin_negaciones` (33 frases: las de las tres revisiones, los 2 falsos positivos reales de Bedrock ahora marcados, inasistencias sin bajada, bajada sin atributo, palabra completa), `test_c65_atributo_en_cualquier_campo_de_texto`, `test_c65_marca_se_guarda_y_se_lee_sin_texto_en_auditoria`, `test_prompt_v1_2_0_por_defecto_y_versiones_anteriores_intactas` y P16a/P16b/P16c. Actualizadas: P08 y P10 (la marca se recalcula igual), `test_dos_validaciones_fallidas_dejan_analisis_fallido` (motivo `equidad_atributo_no_disponible`), las de versión por defecto (v1.2.0) y `test_prompt_v1_1_0_…` (carga v1.1.0 explícitamente). 194 − 28 + 39 = 205. No se llamó a Bedrock |
| `uv run pip-audit` | No known vulnerabilities found (exit 0; solo se salta el propio paquete local) |
| C6.5 nueva sobre los 95 análisis guardados (solo lectura; detalle en `revision-equidad-guardados.md`) | 0 rechazados (regla 1); 1 marcado (regla 2): IC-HLF-00349, 2026-07-19, `resumen`. Hashes de los `.jsonl` iguales antes y después |
| **Tras `review-equidad.md` (hallazgos 1 y 2: formas separadas y derivadas que se colaban en la regla 1). Desde la raíz, tras `chcp 65001` y `. .\scripts\entorno-demo.ps1`:** | |
| `uv run ruff check` | All checks passed! (exit 0) |
| `uv run mypy src` | Success: no issues found in 39 source files (exit 0) |
| `uv run pytest` (marcadores por defecto, sin `-m bedrock`) | **211 passed, 1 deselected** (bedrock) en 49,1 s (exit 0). 205 + 6 frases nuevas en `test_c65_regla_determinista_sin_negaciones`: "nivel socio-económico …", "nivel socio económico …", "Situación previsional …", "Consultorio comunal …" y "Grupo N.S.E. C3." rechazadas; "Evolución previsible; se comunicó el resultado." sin rechazo ni marca. P16a genera además "comunal(es)", "previsional(es)", "nivel socio-económico", "socio económico", "socio-económica", "N.S.E." y "N. S. E.". No se quitó ninguna prueba. No se llamó a Bedrock |
| `uv run pip-audit` | exit 0; sin vulnerabilidades conocidas (solo se salta el propio paquete local) |
| C6.5 ampliada sobre los 95 guardados (solo lectura) | Igual que antes: 0 rechazados, 1 marcado (IC-HLF-00349, `resumen`). Hashes de los cinco `.jsonl` sin cambios |
| **Tras `review-equidad.md`, segunda pasada (hallazgos 1–4: separadores, `_`, afijos, "Fondo Nacional de Salud", "N S E", GSE y ancho completo). Desde la raíz, tras `chcp 65001` y `. .\scripts\entorno-demo.ps1`:** | |
| `uv run ruff check` | All checks passed! (exit 0) |
| `uv run mypy src` | Success: no issues found in 39 source files (exit 0) |
| `uv run pytest -q` (marcadores por defecto, sin `-m bedrock`) | **223 passed, 1 deselected** (bedrock) en 51,3 s (exit 0). 211 + 12 filas nuevas en `test_c65_regla_determinista_sin_negaciones`: rechazadas "Nivel socio - económico bajo.", "socio—económico" (U+2014), "socio/económica", "comuna_residencia", "prevision_salud", "intercomunal", "Previsionalmente", "Fondo Nacional de Salud", "Grupo GSE C3.", "Grupo N S E bajo." y "ＦＯＮＡＳＡ" (ancho completo); "Control comunitario; revisar insensible a cambios." sin rechazo ni marca. P16a genera además esas formas e "imprevisión" y "socioeconómicamente". No se quitó ninguna prueba. No se llamó a Bedrock |
| `uv run pip-audit` | exit 0; sin vulnerabilidades conocidas (solo se salta el propio paquete local) |
| C6.5 normalizada sobre los 95 guardados (solo lectura) | Igual: 0 rechazados, 1 marcado (IC-HLF-00349, `resumen`). Hashes de los cinco `.jsonl` sin cambios |
| **Tras la tercera pasada (el workflow se detuvo por máximo de iteraciones; 5 de 22 frases nuevas se colaban: "FONASAs", "NSEs", "socioeconomía", "F.O.N.A.S.A.", "I.S.A.P.R.E."). Cambio de enfoque hecho por el orquestador:** la regla 1 agrega un segundo filtro: raíces largas (`RAICES_ATRIBUTO_SUBCADENA`: comuna, prevision, fonasa, isapre, fondonacionaldesalud, socioeconom) buscadas como **subcadena** en el texto reducido a solo letras; siglas cortas NSE/GSE (con plural) como token tras unir letras sueltas. Rechaza ante la duda y deja de depender de enumerar formas | |
| `uv run ruff check` / `uv run mypy src` | All checks passed! / Success: no issues found in 39 source files |
| `uv run pytest -q` | **230 passed, 1 deselected** (bedrock): 223 + 7 filas (las 5 que se colaban, rechazadas; "Pensé que el ingreso…" y "Se comunicó con el CESFAM…" sin rechazo ni marca). P16a genera además esas 5 formas. No se llamó a Bedrock |
| C6.5 con subcadena sobre los 95 guardados (solo lectura) | 0 rechazados, 1 marcado (IC-HLF-00349). Hashes sin cambios. Prueba manual adicional: "N.S.E.s", "I S A P R E", "Comunas vecinas" rechazadas; "ninguna sesion", "Gestion de citas", "ya se comunico" aceptadas |
| `uv run hlf-lote --fecha-corte 2026-07-21` / `2026-08-10` | exit 0; 469 y 488 solicitudes, cobertura 100 % |
| `uv run pytest -m bedrock -s` | 1 passed, 39 s. IC-HLF-00002 al 2026-08-10: `critica`, de acuerdo con el motor, 0 correcciones; 6.834 tokens de entrada / 3.426 de salida; 33 s de latencia |
| Ejecución 1: `hlf-copiloto --desde 2026-07-19 --hasta 2026-07-21` (prompt v1.0.0, max_tokens 4096) | exit 1. 95 estimadas, 148 invocaciones (95 + 53 reintentos de validación), **74 analizadas, 21 fallidas**; omitidas: exclusion 117, gestion 47, sin_alerta 984, sin_cambio_en_rango 162; 1.035.363 / 539.429 tokens; 1.324 s; sin limitación |
| Ejecución 2: igual, `--max-llamadas 25` (v1.1.0, D-1 aplicada) | exit 1. 21 estimadas (solo los fallidos), 25 invocaciones, 18 analizadas, 3 fallidas (`nota_preconsulta` ausente por truncado: `stop_reason = max_tokens`); `ya_analizada` 74; 185.243 / 95.614 tokens; 261 s |
| Ejecución 3: igual, `--max-llamadas 5` (max_tokens 8192) | exit 0. 3 invocaciones, 3 analizadas, 0 fallidas; 23.062 / 13.144 tokens; 44 s |
| Ejecución 4: igual | exit 0. **0 estimadas, 0 invocaciones**, `ya_analizada` 95; 1,2 s |

Total real del rango: 176 invocaciones, 1.243.668 tokens de entrada y 648.187 de salida, ~27 min. Resultado final: 95 de 95 `priorizacion` pendientes analizadas (74 con v1.0.0, 21 con v1.1.0), sin duplicados; prioridad sugerida crítica 34, alta 37, media 23, baja 1; 2 discrepancias con el motor; 11 correcciones (6 `hallazgo_a_inferido`, 5 `riesgo_poblacional_reemplazado`). No se corrió el corte completo 2026-10-13.

### Criterio de aceptación IC-HLF-00002

- Al 2026-08-10 (prueba `bedrock`): válido; los `documentado` citan EV-000005 y las mediciones de presión sistólica (MED-43528798179b38e0, MED-668054b16785a1c7, MED-6f2b6169b009dc9b, MED-372ba075aa3128b4); el resumen menciona EV-000004 y EV-000005; `prioridad_sugerida = critica`; `riesgo_poblacional` = cohorte de U1 (n = 13, k = 0, p = 0,0, IC95 0–0,228). **Cumple.**
- Rango: 07-19 omitida (`sin_alerta`); 07-20 analizada en el primer intento, `critica`, con `evaluacion_anterior` del 07-19 en el paquete y cohorte igual a la de U1; 07-21 omitida `sin_cambio_en_rango` con referencia al 07-20. **Cumple.**

### Extracto (datos sintéticos; IC-HLF-00002 al 2026-07-20, Sonnet 5, v1.0.0, request 8710e541-…)

> Hallazgo documentado [EV-000004]: "Visita de urgencia con triage ESI 2 el mismo día del corte (2026-07-20), de especialidad Cardiología, que activó la bandera roja BR_EVENTO_GRAVE_30D en el motor."
>
> Hallazgo documentado [MED-43528798179b38e0, MED-668054b16785a1c7, MED-6f2b6169b009dc9b, MED-372ba075aa3128b4]: "Tendencia ascendente sostenida de presión sistólica en las últimas 4 mediciones (112 -> 97 -> 100 -> 167 mmHg …)."
>
> Acción sugerida: "Solicitar una medición de presión arterial actualizada (sistólica y diastólica conjuntas) para corroborar la tendencia ascendente observada."

## Desviaciones

| # | Desviación | Motivo |
|---|---|---|
| 1 | C1.1: solo `priorizacion` (la sección 8.2 incluía `exclusion`) | Decisión G-1 del diseño funcional |
| 2 | C4.2: a `us.anthropic.claude-sonnet-5` no se le envía temperatura; Haiku 4.5 y Nova Pro, temperatura 0; cada análisis guarda `temperatura_enviada` | Bedrock rechaza `temperature` para Sonnet 5 (ValidationException). Decisión T-1 = A |
| 3 | C6.2: `documentado` sin IDs pasa a `inferido` con corrección, en vez de rechazarse | 14 de 21 fallidos de la ejecución 1. Decisión D-1 = A |
| 4 | C5.1: sin `--forzar`, un análisis con cualquier `version_prompt` para el mismo `(id_solicitud, fecha_corte, version_reglas, model_id)` cuenta como `ya_analizada` | No recalcular los 74 análisis v1.0.0 al publicar v1.1.0. Decisión D-2 = C |
| 5 | Prompt por defecto `copiloto-v1.2.0` (antes `copiloto-v1.1.0`) | Decisión D-2 = C; v1.2.0 por la decisión E-1 = C. Los análisis v1.0.0 y v1.1.0 no se recalculan (`ya_analizada` entre versiones) |
| 6 | `max_tokens` 4096 → 8192. **Ratificada por el usuario** (C4.2) | 33 de 173 respuestas reales se truncaron (`max_tokens`); el campo final `nota_preconsulta` faltaba |
| 7 | **C6.5 reemplazada (decisión E-1 = C).** Sin interpretar negaciones. Regla 1: sobre el texto normalizado (NFKD, sin tildes, separadores y `_` como un espacio), mencionar comuna (cualquier palabra que la contenga: "comunal", "intercomunal"), previsión (ídem: "previsional", "previsionalmente"; FONASA, "Fondo Nacional de Salud", ISAPRE) o NSE ("socio-económico" con cualquier separador, "N.S.E.", "N S E", GSE) en cualquier campo de texto rechaza con `equidad_atributo_no_disponible` (fail-closed; C6.7 aplica). Regla 2: inasistencias + cualquier forma de bajar/rebajar/postergar/reducir/disminuir/degradar/relegar en la misma oración guarda el análisis con la marca del sistema `revision_equidad` (campo + oración) y una corrección; U3 muestra la advertencia y decide el médico. "Lugar de residencia" y "domicilio" salen de la lista. Se quitó toda la lógica de ventanas y cláusulas | Tres revisiones seguidas dejaron pasar frases nuevas con la negación por expresiones regulares. El copiloto nunca recibe comuna, previsión ni NSE (`ContextoPaciente` no los tiene); las inasistencias sí están en los datos. Sobre los 95 guardados: 0 rechazados, 1 marcado |
| 7 (histórica, reemplazada) | C6.5: el patrón ignora frases que niegan el uso del atributo ("no se usa para bajar la prioridad"). Tras la revisión, la negación solo vale dentro de su cláusula y si gobierna directamente el atributo o la bajada; ante la duda se rechaza | 2 falsos positivos reales en la ejecución 1 (siguen aceptados). La ventana de 60 caracteres dejaba pasar "no hay motivo clínico urgente y por su comuna conviene bajarla" (hallazgo 5). Con la regla nueva, 0 de los 95 análisis guardados se rechazarían. Re-revisión: "sin <atributo>" ya no exime (negar que el atributo exista no es negar su uso: se exige un verbo de uso) y "no solo por <atributo>" se rechaza (los adverbios de exclusividad dejaron de ser puente); "no por la comuna sino por …" también se rechaza (fail-closed). Siguen 0 de 95 |
| 8 | Sin Bedrock Guardrails | G-4; pendiente obligatorio con texto clínico real |
| 9 | Corte de circuito por solicitud: las fallas de validación no lo alimentan, solo las del servicio | Una respuesta mal formada no indica un servicio caído |
| 10 | C2.5: `--max-llamadas` es un presupuesto de invocaciones reales (incluye reintentos de validación y de servicio), compartido entre hilos; lo que no cabe queda `analisis_omitido(limite_llamadas)` y exit 1. Solo se aborta antes de llamar si las solicitudes pendientes superan el presupuesto. Excepción documentada a C4.3: con concurrencia > 1, cuáles solicitudes quedan como `limite_llamadas` al agotarse el presupuesto depende del orden de los hilos (con concurrencia 1 es determinista; el total nunca supera B) | Hallazgo 1 de la revisión (ejecución 1: 95 estimadas, 148 invocaciones). Aprobado por el usuario. Excepción: hallazgo 3 de la re-revisión |
| 11 | Nuevo motivo de falla `contexto_no_disponible` (solicitud ausente del dataset o contexto no armable); `huella_distinta` queda solo para la huella distinta | Hallazgo 3 de la revisión |
| 12 | Modelo fuera de la lista local: exit 4 (como un AccessDenied), con la sugerencia del modelo de respaldo; antes exit 2 | Hallazgo 4 de la revisión |
| 13 | **Defecto encontrado en uso real; corregido.** Persistencia incremental (C5.4) y Ctrl+C ordenado (C4.8): cada solicitud se escribe apenas termina (E/S, `llamada_modelo`, análisis o fallido, omisión, `analisis_ia` / `error_proceso`) bajo un solo candado; Ctrl+C cancela lo no empezado, espera hasta 70 s a lo que está en curso (un segundo Ctrl+C no espera), registra `analisis_omitido(interrumpido)`, imprime el resumen parcial y sale con 130. El orden de las líneas en los JSONL deja de ser fijo; lo determinista es el conjunto guardado | `uv run hlf-copiloto --fecha-corte 2026-10-13` (125 pendientes, Sonnet 5): Ctrl+C a los ~15 min dejó 0 análisis, 0 eventos `llamada_modelo` y nada en `salidas/analisis/fecha_corte=2026-10-13/`; solo los 375 `analisis_omitido` previos. `ejecutar_tareas` esperaba todo con `pool.map` y el paso 9 escribía al final. Violaba RF-09, RESILIENCY-10 y RESILIENCY-13 |

## Corrección del defecto 13: persistencia incremental y Ctrl+C (2026-10-16)

Cambios:

- `copiloto/barrido.py`: `ejecutar_tareas` usa `wait(FIRST_COMPLETED)` en tramos de 0,5 s y entrega cada resultado a `al_terminar` en el hilo principal, con Ctrl+C aplazado mientras escribe una solicitud (sin escrituras a medias). Nuevo `_Persistidor` (un `threading.Lock`, caché de claves por ruta para no releer `analisis.jsonl` / `fallidos.jsonl` en cada escritura) y los conteos del resumen. `KeyboardInterrupt` marca `detener` e `interrupcion`, `shutdown(wait=False, cancel_futures=True)`, espera acotada `ESPERA_INTERRUPCION = 70 s`; las tareas sin terminar vuelven como `interrumpida` (y `abandonada` si su llamada seguía en curso). Un Ctrl+C fuera de las llamadas registra las pendientes como `interrumpido` y se propaga. Cualquier otra excepción detiene el barrido y se propaga; lo ya entregado queda escrito. Gancho `vigia(n)` para simular Ctrl+C en pruebas sin señales.
- `copiloto/cli.py`: exit `130` (`SALIDA_INTERRUMPIDA`), línea "Interrumpidas" en el resumen parcial y mensaje para volver a ejecutar; si quedó una llamada abandonada, sale con `os._exit(130)` tras vaciar stdout/stderr para no esperar a ese hilo.
- `copiloto/modelos.py`: motivo de omisión `interrumpido`. `persistencia/salidas.py` y `copiloto/persistencia.py`: parámetro opcional `vistos_por_ruta` (las claves se agregan al caché solo después de escribir).
- Sin cambios en prompts, reglas de validación, semántica del presupuesto, corte de circuito, configuración del modelo ni U1/U3.

Pruebas nuevas (cliente falso, sin Bedrock):

- `tests/ejemplos/test_copiloto_interrupcion.py` (7): Ctrl+C tras k = 1 y 3 terminadas vía `cli.main` (las k están en `analisis.jsonl` con `llamada_modelo` y `analisis_ia`; el resto `interrumpido`; exit 130; la re-ejecución llama solo por las interrumpidas y deja cada solicitud con exactamente un análisis); `KeyboardInterrupt` lanzado por el cliente en un hilo; `RuntimeError` del cliente en una solicitud (las demás guardadas); caída `BaseException` a mitad del barrido (lo terminado ya está persistido, con su E/S; la re-ejecución llama solo por la que faltó); espera acotada con una llamada colgada (queda `interrumpido`, el CLI sale con 130 sin esperarla); Ctrl+C antes de las llamadas (130, todas `interrumpido`, 0 llamadas).
- `tests/propiedades/test_prop_copiloto.py::test_p17_…` (25 ejemplos): mezcla de respuestas falsas (válida, mal formada, error del modelo, error inesperado), concurrencia 1..8 y punto de interrupción 1..N+1: todo análisis persistido tiene su `llamada_modelo` con la misma `huella_salida`, su E/S y su `analisis_ia`; toda línea de `analisis.jsonl`, `fallidos.jsonl` y `eventos.jsonl` es un JSON completo; analizadas ∪ fallidas ∪ interrumpidas = plan, sin solapes; el resumen coincide con lo persistido.
- Se mantienen verdes P13 (secuencial y paralelo dan el mismo conjunto) y P15 (invocaciones ≤ presupuesto).
- Pruebas sensibles al orden modificadas: **ninguna**. Se revisaron todas las de U2: ninguna comparaba bytes ni el orden de líneas de `analisis.jsonl`, `fallidos.jsonl` o `eventos.jsonl` con más de una solicitud (las que listan eventos usan `sorted(...)`, conjuntos o un solo elemento), y `leer_analisis` ya ordena.

Verificación (Windows PowerShell 5.1, desde la raíz, tras `. .\scripts\entorno-demo.ps1`):

| Comando | Resultado |
|---|---|
| `uv run ruff check` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 44 source files |
| `uv run pytest` (marcadores por defecto; sin `bedrock`) | **280 passed, 1 deselected** en 85,8 s (antes 272 passed + 1 deselected; +8 nuevas). Sin advertencias en el resumen |
| `uv run pip-audit` | No known vulnerabilities found (`hlf-priorizacion` omitido por no estar en PyPI) |
| Las 8 pruebas nuevas, 5 veces seguidas | 8 passed las 5 veces (sin intermitencias) |

No se hicieron llamadas reales a Bedrock ni se ejecutó `hlf-copiloto` contra Bedrock; las pruebas usan carpetas temporales y no tocan `salidas/`. Falta comprobar con el comando real que un Ctrl+C deja los análisis y sale con 130 (no verificable sin Bedrock).
