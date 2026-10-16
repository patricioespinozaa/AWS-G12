# U2 — Entidades de dominio

Base: sección 8 de `docs/contexto-tecnico.md` y los contratos ya implementados en `src/hlf_priorizacion/modelos.py` (U1). U2 **no** redefine `AnalisisIA`, `Evaluacion` ni `ContextoPaciente`: los usa.

## Entrada

| Entidad | Contenido | Origen |
|---|---|---|
| `SolicitudCopiloto` | Modo (`corte` o `rango`), `fecha_corte` o `desde`/`hasta`, `model_id`, `concurrencia`, `max_llamadas`, `forzar` | CLI `hlf-copiloto` |
| `PaqueteBarrido` | `id_solicitud`, `fecha_corte`, `contexto` (`ContextoPaciente` completo hasta el corte, G-5), `evaluacion` (`Evaluacion` del motor), `evaluacion_anterior` (`Evaluacion` del corte previo del rango o `None`), `hallazgos_dq`, `cohorte` (`ResultadoCohorte` o `None`), `version_reglas` | Archivos de `salidas/` que dejó `hlf-lote` |

`PaqueteBarrido` hereda de `ContextoPaciente` la ausencia de `comuna`, `prevision`, `nivel_socioeconomico` y nombre. U2 no tiene acceso a esos campos.

## Configuración

| Entidad | Contenido |
|---|---|
| `Prompt` | `version_prompt` (semver), `huella` (SHA-256 del texto), `sistema` (instrucciones), `plantilla_usuario`; archivos en `src/hlf_priorizacion/copiloto/prompts/` |
| `ConfigModelo` | `model_id` (por defecto `us.anthropic.claude-sonnet-5`; respaldo `us.anthropic.claude-haiku-4-5-20251001-v1:0`), `temperatura = 0`, `max_tokens`, `timeout_s = 60`, `region = us-east-1` |
| `ClienteModelo` (interfaz) | `converse(sistema, mensajes, herramienta, config) -> RespuestaModelo`. Dos implementaciones: Bedrock real y una falsa para pruebas |

## Salida

| Entidad | Contenido | Dónde se guarda |
|---|---|---|
| `AnalisisIA` | Esquema `analisis-v1` (ya en `modelos.py`); `metadatos` los rellena el sistema: `model_id`, `version_prompt`, `request_id`, `fecha_corte`, `id_ejecucion`, `estado = pendiente_revision_medica` | `salidas/analisis/fecha_corte=…/version_reglas=…/analisis.jsonl` |
| `ResultadoValidacion` | `valido`, `correcciones[]` (hallazgo pasado a `inferido`, cifra reemplazada), `motivo_rechazo` | Dentro del evento de auditoría |
| `AnalisisFallido` | `id_solicitud`, `fecha_corte`, `motivo`, `intentos` | `salidas/analisis/…/fallidos.jsonl` |
| Eventos de auditoría | `llamada_modelo`, `analisis_ia`, `analisis_omitido`, `error_proceso` | `salidas/auditoria/eventos.jsonl` (solo agregar, el mismo de U1) |

## Clave de idempotencia

`(id_solicitud, fecha_corte, version_reglas, version_prompt, model_id)`. Si ya existe un `AnalisisIA` con esa clave, no se vuelve a llamar al modelo (Aclaración 3).
