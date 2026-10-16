# U3 — Reglas de negocio

## B1 Solo lectura (H-2)

| Regla | Detalle |
|---|---|
| B1.1 | La interfaz no ejecuta `hlf-lote` ni `hlf-copiloto` y no llama a Bedrock |
| B1.2 | Si un corte no tiene propuestas, se muestra el comando exacto: `uv run hlf-lote --fecha-corte AAAA-MM-DD` |
| B1.3 | Si una solicitud no tiene análisis, se muestra "Análisis IA pendiente" y el comando `uv run hlf-copiloto --fecha-corte AAAA-MM-DD`. Si tiene un análisis fallido, se muestra el motivo |
| B1.4 | El único archivo que escribe la interfaz es `salidas/decisiones/decisiones.jsonl` (y su evento `decision_medica` en la auditoría) |

## B2 Bandeja

| Regla | Detalle |
|---|---|
| B2.1 | Por defecto se listan las solicitudes con `tipo_resultado ∈ {priorizacion, gestion, exclusion}`. Las `sin_alerta` se pueden mostrar con un filtro |
| B2.2 | Orden: primero `crítica`; luego por magnitud del cambio descendente (subidas antes que bajadas); luego puntaje descendente; luego `id_solicitud`. Determinista |
| B2.3 | Filtros: especialidad, nivel propuesto, tipo de resultado, "solo con análisis", "solo con marca de equidad", estado de decisión |
| B2.4 | Una bajada de nivel se destaca igual que una subida: bajar una prioridad requiere revisión (sección 6.8 del contexto técnico) |
| B2.5 | Indicadores en cada fila: bandera roja, análisis disponible, **advertencia de equidad**, decisión ya tomada |

## B3 Detalle

| Regla | Detalle |
|---|---|
| B3.1 | Siempre visibles: prioridad inicial, nivel calculado, nivel propuesto, puntaje, confianza y `estado_revision` |
| B3.2 | Cada factor muestra su aporte y los IDs citados. Al elegir un ID se resalta el registro en la línea de tiempo |
| B3.3 | La línea de tiempo muestra solo registros con fecha ≤ corte (los del contexto reconstruido) |
| B3.4 | El análisis IA se muestra separado de la evaluación del motor y rotulado "Sugerencia del copiloto — no es una decisión". Hallazgos `documentado` con sus IDs; `inferido` marcados como tales; correcciones del validador visibles |
| B3.5 | Si `revision_equidad` no está vacío, se muestra **antes del análisis** una advertencia con cada frase marcada y su campo: "El análisis menciona inasistencias junto a una bajada de prioridad. La inasistencia no baja la prioridad clínica: revise antes de decidir" |
| B3.6 | Si el modelo discrepa del motor, se muestra el motivo de la discrepancia |
| B3.7 | Nunca se muestran comuna, previsión, nivel socioeconómico ni nombre del paciente (no están en el contexto) |

## B4 "¿Qué cambió?" (H-1)

| Regla | Detalle |
|---|---|
| B4.1 | Se eligen dos cortes con propuestas: `corte_a` estrictamente anterior a `corte_b` |
| B4.2 | Se listan las solicitudes presentes en ambos cortes cuyo nivel propuesto, banderas o pisos cambiaron. Las que solo aparecen en `corte_b` (ingresaron después) y las que pasan a `exclusion` van en secciones aparte |
| B4.3 | Para cada una: nivel antes → después, puntaje antes → después, banderas nuevas y registros nuevos (fecha en (corte_a, corte_b]) con su ID |
| B4.4 | Orden igual que B2.2, usando el nivel de `corte_b` |

## B5 Decisiones (H-4)

| Regla | Detalle |
|---|---|
| B5.1 | El médico se elige de una lista fija de nombres ficticios. Sin médico elegido no se puede decidir |
| B5.2 | Opciones: aceptar, ajustar (exige prioridad final distinta de la propuesta y motivo) o rechazar (exige motivo). La validación la hace `Decision` (Pydantic); el formulario muestra el error sin guardar |
| B5.3 | `motivo` hasta 1000 caracteres, sin HTML (se muestra como texto plano) |
| B5.4 | Cada decisión es un registro nuevo con `id_decision` (ULID), `timestamp` UTC, `id_analisis` si había. Nunca se edita ni borra; una nueva decisión sobre la misma solicitud queda como la vigente y las anteriores como historial |
| B5.5 | Al guardar se agrega un evento `decision_medica` a la auditoría con IDs, decisión y prioridad final, sin el texto del motivo en los logs |
| B5.6 | Las decisiones no modifican propuestas, análisis ni `prioridad_inicial` |

## B6 Cobertura y alertas

Por corte: total evaluadas, cobertura, exclusiones por código, cambios de nivel (sube/baja), alertas de gestión por código, cuarentena, análisis guardados, fallidos y marcados por equidad, y decisiones tomadas frente a pendientes.

## B7 Seguridad (demo local)

| Regla | Detalle |
|---|---|
| B7.1 | Streamlit solo en `localhost` (`server.address = 127.0.0.1`), sin login: declarado en la presentación como demo local. SECURITY-08/12 quedan para la versión desplegada con Cognito |
| B7.2 | Errores de lectura se muestran con un mensaje genérico; el detalle va a los logs sin datos clínicos (SECURITY-15) |
| B7.3 | Sin `unsafe_allow_html` para textos que vengan del modelo o de los datos |
| B7.4 | Streamlit con versión exacta en `pyproject.toml`/`uv.lock`; `pip-audit` limpio |
| B7.5 | Telemetría de Streamlit desactivada (`browser.gatherUsageStats = false`) |
