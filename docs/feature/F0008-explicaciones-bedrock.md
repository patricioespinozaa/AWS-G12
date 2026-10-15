# F0008 · Explicaciones con IA generativa conectadas a Bedrock

**Estado:** Plan (el código existe; falta conectarlo a AWS) · **Depende de:** F0004 · **Tamaño:** S

## Objetivo

Activar en AWS la explicación redactada por Claude que ya está implementada, con permisos mínimos, un modelo disponible en la región, Guardrails y registro de uso, sin cambiar el principio de que el LLM solo redacta y nunca decide.

## Qué existe hoy

- `priorizacion/explicacion.py`:
  - `explicacion_plantilla()` es la explicación determinista que se usa por defecto.
  - `explicacion_llm()` llama a Claude en Bedrock con `AnthropicBedrockMantle` (paquete `anthropic[bedrock]`) cuando `LLM_PROVEEDOR=bedrock`.
  - `validar_texto_llm()` descarta el texto si menciona fechas, referencias o niveles que no están en los factores.
  - Ante cualquier error, la función vuelve a la plantilla y deja un aviso.
- Configuración (`priorizacion/config.py`): `LLM_PROVEEDOR`, `AWS_REGION` y `BEDROCK_MODEL_ID` (por defecto `anthropic.claude-opus-5-5`).
- Endpoint `POST /api/solicitudes/{id}/explicacion-ia`. `propuesta_prioridad.fuente_explicacion` distingue `plantilla` de `llm`.
- `docs/mvp.md`: "La explicación con Bedrock está implementada pero no se probó contra el servicio".

## Alcance

**Entra:** acceso al modelo en la cuenta, permisos IAM de la tarea, Guardrails, elección de modelo por costo y latencia, registro de cada llamada, y una prueba contra el servicio real.

**No entra:** cambiar el contenido del prompt ni la lógica de validación (se mantienen).

## Diseño

| Pieza | Elección | Por qué |
|---|---|---|
| Modelo | Un perfil de inferencia de Claude disponible en la región (por ejemplo, el perfil `us.` o `global.` del modelo elegido), en `BEDROCK_MODEL_ID` | Los modelos recientes se invocan por perfil de inferencia. La disponibilidad depende de la región de la cuenta del hackatón |
| Permisos | Rol de la tarea con `bedrock:InvokeModel` solo sobre ese perfil y sus modelos de destino | Mínimo privilegio |
| Guardrails | Un guardrail de Bedrock con filtros de contenido y denegación de temas ("diagnóstico", "indicar tratamiento") | Defensa adicional a `validar_texto_llm`, que sigue siendo la validación principal |
| Datos enviados | Solo los factores y niveles de la propuesta (`_carga_llm`), sin nombre ni RUT | Minimización de datos personales |
| Registro | Log estructurado por llamada (`id_propuesta`, modelo, tokens, latencia, aceptado o descartado y motivo) | Medir costo y cuántas veces se descarta el texto |
| Costo | `effort: low` (ya en el código), `max_tokens` acotado y caché del texto por `huella_datos` | La misma propuesta con los mismos datos no vuelve a llamar al modelo |

## Cambios por carpeta

```
priorizacion/explicacion.py     guardrail opcional (BEDROCK_GUARDRAIL_ID), log estructurado, caché por huella
priorizacion/config.py          BEDROCK_GUARDRAIL_ID, BEDROCK_GUARDRAIL_VERSION
infra/stacks/ia.py              guardrail de Bedrock y política IAM de invocación (reutilizable por F0009 y F0010)
infra/stacks/backend.py         variables LLM_PROVEEDOR=bedrock, BEDROCK_MODEL_ID; adjuntar la política
tests/test_explicacion.py       llamadas simuladas: aceptado, descartado por validación, error → plantilla
scripts o README                prueba de humo manual contra Bedrock
```

## Tareas

1. Habilitar el acceso al modelo en la consola de Bedrock de la cuenta y anotar el ID del perfil de inferencia.
2. Stack `ia` con guardrail y política IAM. Adjuntar la política al rol de la tarea del backend.
3. Log estructurado y caché por `huella_datos`.
4. Pruebas con el cliente simulado.
5. Prueba de humo en AWS: explicar los seis casos de referencia de `docs/casos-ejemplo.md` y revisar cuántos textos se aceptan.
6. Actualizar `docs/mvp.md` (la limitación ya no aplica) y documentar el costo observado.

## Criterios de aceptación

- En la app desplegada, "Explicación con IA" muestra un texto con `fuente = bedrock` para los casos de referencia.
- Si se quita el permiso IAM, la app sigue funcionando con la plantilla y muestra el aviso. Nunca muestra un error 500.
- Los logs muestran tokens y latencia por llamada. La segunda solicitud de la misma propuesta no llama a Bedrock.

## Riesgos y decisiones abiertas

- **Disponibilidad del modelo en la región:** si no está, usar el perfil `global.` o cambiar de región solo para Bedrock (los datos enviados no incluyen identificadores directos).
- **Tasa de descarte:** si `validar_texto_llm` descarta muchos textos, ajustar el prompt; nunca relajar la validación.
