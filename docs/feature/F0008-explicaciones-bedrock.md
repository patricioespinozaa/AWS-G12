# F0008 · Explicaciones con IA generativa conectadas a Bedrock

**Estado:** Implementado y desplegado en `demo` · **Depende de:** F0004 · **Tamaño:** S

## Objetivo

Activar en AWS la explicación redactada por Claude que ya está implementada, con permisos mínimos, un modelo disponible en la región, Guardrails y registro de uso, sin cambiar el principio de que el LLM solo redacta y nunca decide.

## Restricción: solo IA del ecosistema AWS

El hackatón exige usar **únicamente IA dentro del ecosistema de AWS**. En este proyecto eso significa:

- Todo modelo se invoca a través de **Amazon Bedrock**, con las credenciales IAM de la tarea (firma SigV4). Claude se usa como modelo de Bedrock, nunca por la API de Anthropic ni de otro proveedor.
- No existen claves de API de proveedores externos (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` u otras) en el código, en las variables de la tarea ni en Secrets Manager.
- El cliente es el SDK de AWS (`boto3`, `bedrock-runtime`), no el SDK de un proveedor de modelos.
- `LLM_PROVEEDOR` solo admite `bedrock`; cualquier otro valor deja la plantilla determinista.
- Lo mismo rige para las demás features con IA: F0009 (Bedrock Knowledge Bases), F0010 (Bedrock), F0011 (Lex, Polly y el reconocimiento de voz de Amazon Connect) y F0012 (Textract y Bedrock).

## Punto de partida (antes de F0008)

- `priorizacion/explicacion.py`:
  - `explicacion_plantilla()` es la explicación determinista que se usa por defecto.
  - `explicacion_llm()` llama a Claude en Bedrock con `AnthropicBedrockMantle` (paquete `anthropic[bedrock]`) cuando `LLM_PROVEEDOR=bedrock`. La llamada ya va al endpoint de Bedrock con credenciales de AWS, pero usa el SDK de Anthropic: se reemplaza por `boto3` (ver Diseño).
  - `validar_texto_llm()` descarta el texto si menciona fechas, referencias o niveles que no están en los factores.
  - Ante cualquier error, la función vuelve a la plantilla y deja un aviso.
- Configuración (`priorizacion/config.py`): `LLM_PROVEEDOR`, `AWS_REGION` y `BEDROCK_MODEL_ID` (por defecto `anthropic.claude-opus-5-5`).
- Endpoint `POST /api/solicitudes/{id}/explicacion-ia`. `propuesta_prioridad.fuente_explicacion` distingue `plantilla` de `llm`.
- `docs/mvp.md`: "La explicación con Bedrock está implementada pero no se probó contra el servicio".

## Alcance

**Entra:** cambiar el cliente a `boto3` (`bedrock-runtime`, API Converse), acceso al modelo en la cuenta, permisos IAM de la tarea, Guardrails, elección de modelo por costo y latencia, registro de cada llamada, una prueba que impida volver a introducir proveedores externos y una prueba contra el servicio real.

**No entra:** cambiar el contenido del prompt. La validación no se relaja; se **endureció** (ver Resultado).

## Diseño

| Pieza | Elección | Por qué |
|---|---|---|
| Cliente | `boto3.client("bedrock-runtime").converse(...)`, con `inferenceConfig` (`maxTokens`) y `guardrailConfig`. Se quita `anthropic[bedrock]` de `requirements/base.txt` | SDK de AWS de punta a punta: deja claro que todo pasa por Bedrock. Converse da el mismo contrato para cualquier modelo de Bedrock, trae el uso de tokens en la respuesta y aplica el guardrail en la misma llamada |
| Modelo | **Claude Sonnet 4.5** por el perfil `us.anthropic.claude-sonnet-4-5-20250929-v1:0`, en `BEDROCK_MODEL_ID` (`infra/config/entornos.py`) | Está en la lista de modelos permitidos de la cuenta del hackatón (`ws-bedrock-model-allowlist`, que bloquea los Claude 5.5) y fue el que más textos aceptó en la prueba de humo |
| Permisos | Política administrada del stack `ia`: `bedrock:InvokeModel` solo sobre ese perfil y su modelo base en las tres regiones a las que enruta (`us-east-1`, `us-east-2`, `us-west-2`), y `bedrock:ApplyGuardrail` sobre el guardrail. Se adjunta al rol de la tarea solo si el entorno activa Bedrock | Mínimo privilegio |
| Guardrails | Guardrail de nivel **Standard** (evalúa español; el clásico solo inglés), con el perfil entre regiones `us.guardrail.v1:0`. Filtros de contenido en la salida y dos temas denegados **solo en la salida**: "Indicar tratamiento" y "Especular diagnóstico o pronóstico". La entrada no se filtra, porque contiene legítimamente diagnósticos y cambios de tratamiento. La API usa una versión fija, que cambia sola al cambiar la configuración | Defensa adicional a `validar_texto_llm`, que sigue siendo la validación principal |
| Datos enviados | Solo los factores y niveles de la propuesta (`_carga_llm`), sin nombre ni RUT | Minimización de datos personales |
| Registro | Una línea JSON por pedido en CloudWatch (`evento: explicacion_ia`): solicitud, fecha de corte, huella, modelo, guardrail, resultado (`aceptado`, `descartado`, `guardrail`, `error`, `cache`), motivo, tokens y latencia. Nunca el texto clínico | Medir costo y cuántas veces se descarta el texto |
| Costo | `maxTokens` = 900 y caché en la base (`priorizacion.explicacion_ia`) por huella de los datos, modelo y versión del prompt. Solo se guardan textos aceptados | La misma propuesta con los mismos datos no vuelve a llamar al modelo, desde cualquier tarea |
| Alternativa de modelo | **Amazon Nova Pro** (`us.amazon.nova-pro-v1:0`): aceptó todos los casos en ~1,5 s y cuesta menos, con una redacción más mecánica. Se cambia solo `BEDROCK_MODEL_ID` en `infra/config/entornos.py` | Converse no depende del proveedor del modelo; sigue dentro de AWS |

## Cambios por carpeta

```
priorizacion/explicacion.py     cliente boto3 (Converse), guardrail, caché por huella, log JSON, validación de fechas en
                                prosa y limpieza de markdown
priorizacion/config.py          BEDROCK_MODEL_ID, BEDROCK_REGION, BEDROCK_MAX_TOKENS, BEDROCK_GUARDRAIL_ID/VERSION
priorizacion/registro*.py       explicacion_guardada / guardar_explicacion (SQLite y PostgreSQL)
db/sql/priorizacion/005_explicacion_ia.sql   caché de textos aceptados
requirements/base.txt           sin anthropic[bedrock] (boto3 ya estaba)
api/rutas/solicitudes.py        la explicación con IA recibe la huella y la caché
api/main.py                     los logs de la app (hlf.*) llegan a CloudWatch
infra/stacks/ia.py              guardrail (Standard, temas solo en la salida) y política IAM de invocación
infra/stacks/backend.py         variables del guardrail y la política, solo si el entorno activa Bedrock
infra/config/entornos.py        demo: llm_proveedor=bedrock, bedrock_model_id=Claude Sonnet 4.5
scripts/prueba_bedrock.py       prueba de humo: casos de referencia contra Bedrock real, por modelo
tests/test_explicacion.py       cliente simulado: aceptado, descartados, guardrail, incompleto, error, caché, log
tests/test_solo_aws.py          falla si aparece un SDK, endpoint o clave de IA fuera de AWS
```

## Tareas

1. Habilitar el acceso al modelo en la consola de Bedrock de la cuenta y anotar el ID del perfil de inferencia.
2. Reemplazar `AnthropicBedrockMantle` por `boto3` (Converse) y quitar `anthropic[bedrock]` de las dependencias. Agregar `tests/test_solo_aws.py`.
3. Stack `ia` con guardrail y política IAM. Adjuntar la política al rol de la tarea del backend.
4. Log estructurado y caché por `huella_datos`.
5. Pruebas con el cliente simulado.
6. Prueba de humo en AWS: explicar los seis casos de referencia de `docs/casos-ejemplo.md` y revisar cuántos textos se aceptan.
7. Actualizar `docs/mvp.md` (la limitación ya no aplica; la instalación ya no pide `anthropic[bedrock]`) y documentar el costo observado.

## Criterios de aceptación

- En la app desplegada, "Explicación con IA" muestra un texto con `fuente = bedrock` para los casos de referencia.
- **Solo AWS:** las dependencias no incluyen SDKs de proveedores de modelos, no hay claves de API externas y `tests/test_solo_aws.py` pasa. El rol de la tarea solo permite `bedrock:InvokeModel` (y `bedrock:ApplyGuardrail`) sobre el perfil y el guardrail elegidos.
- Si se quita el permiso IAM, la app sigue funcionando con la plantilla y muestra el aviso. Nunca muestra un error 500.
- Los logs muestran tokens y latencia por llamada. La segunda solicitud de la misma propuesta no llama a Bedrock.

## Riesgos y decisiones abiertas

- **Disponibilidad del modelo en la región:** si no está, usar el perfil `us.` (enruta entre regiones de EE. UU.) o cambiar de región solo para Bedrock; los datos enviados no incluyen identificadores directos. El perfil `global.` también queda dentro de AWS, pero puede procesar en cualquier región del mundo: preferir `us.` salvo que no haya otra opción.
- **Modelo no habilitado en la cuenta del hackatón:** usar otro modelo de Bedrock (ver "Alternativa de modelo"); nunca un proveedor externo.
- **Tasa de descarte:** si `validar_texto_llm` descarta muchos textos, ajustar el prompt; nunca relajar la validación.

## Resultado

Implementado, probado y desplegado en `demo` el 16-10-2026.

**Elección del modelo** (`scripts/prueba_bedrock.py`, casos de referencia activos a dos fechas de corte, con la validación endurecida):

| Modelo (perfil `us.`) | Aceptados | Latencia mediana | Comentario |
|---|---|---|---|
| Claude Sonnet 4.5 | 9 de 9 | 5,4–6,5 s | Mejor redacción. **Elegido** |
| Amazon Nova Pro | 9 de 9 | 1,5–1,7 s | Más barato y rápido; redacción más mecánica. Alternativa |
| Claude Sonnet 5 | 8 de 9 | 4,4–8,2 s | Un texto cortado por `maxTokens` |
| Claude Haiku 4.5 | 8 de 9 | 2,6–3,5 s | Antes de endurecer la validación, **inventó una fecha** ("4 de agosto" por el 6) y fue aceptada |

Los Claude 5.5 no están permitidos en la cuenta del hackatón (política `ws-bedrock-model-allowlist`).

**Validación endurecida.** La prueba de humo mostró que la validación solo revisaba fechas ISO: Haiku escribió "4 de agosto" para una hospitalización del 6 y pasó. Ahora también se validan fechas en prosa ("6 de agosto", "6 de agosto de 2026") y con barras (06/08/2026), y antes de validar se quita el markdown (títulos y negritas) que algunos modelos agregan aunque el prompt pide prosa.

**Guardrail.** Con la primera definición del tema "Diagnosticar", bloqueó 2 de 10 textos legítimos que nombraban el diagnóstico registrado ("angina de pecho, riesgo de infarto"). Con la definición actual: 0 de 20 bloqueos en textos legítimos; con `ApplyGuardrail` bloquea "Se recomienda iniciar un betabloqueador…" (Indicar tratamiento) y "Es probable que esté cursando un infarto…" (Especular diagnóstico o pronóstico), y deja pasar un texto que menciona el diagnóstico registrado y un aumento de dosis ya ocurrido. El guardrail suma unos 2 a 3 s por llamada.

**En AWS** (cuenta temporal de Cognito, eliminada al terminar): la ficha de `IC-HLF-00002` devolvió `fuente = bedrock` con Claude Sonnet 4.5 en 7,6 s (incluye el guardrail); la segunda petición salió de la caché en 0,5 s. El rol de la tarea invoca el modelo con la política del stack `ia`.

| Criterio | Resultado |
|---|---|
| "Explicación con IA" con `fuente = bedrock` en la app desplegada | Sí |
| Solo AWS | Sin `anthropic[bedrock]` ni otros SDKs; `tests/test_solo_aws.py` pasa; política solo sobre el perfil, su modelo base y el guardrail |
| Sin permiso o con error de AWS, plantilla y aviso, nunca 500 | Prueba con el cliente simulado; probado también localmente con el modelo bloqueado (AccessDenied → plantilla) |
| Tokens y latencia por llamada; la segunda no llama a Bedrock | Log JSON por pedido; caché en la base |

**Costo observado:** unos 1.000 tokens de entrada y 300 de salida por explicación. Con los precios de Claude Sonnet 4.5 bajo demanda, del orden de USD 0,01 por explicación nueva; las repetidas salen de la caché.

Suite: 142 pruebas con PostgreSQL y el dataset; 62 en modo CI; 30 de infraestructura.

