# F0013 · Observabilidad, seguridad y control de costos

**Estado:** Implementado · **Depende de:** F0004 (se amplía con cada feature que agrega servicios) · **Tamaño:** M

## Objetivo

Saber cuándo algo falla, quién hizo qué y cuánto cuesta, y cumplir lo mínimo de seguridad para pasar de datos sintéticos a datos reales del HLF.

## Qué existe hoy

- **En la base:** auditoría de solo inserción en decisiones, turnos, divulgaciones, consentimientos y preguntas; roles de mínimo privilegio; verificación con `python -m db verificar`.
- **En S3** (F0003 y F0004): buckets privados, versionados y cifrados; workgroup de Athena con límite de 1 GB por consulta.
- **No existen:** métricas, alarmas, WAF, trail de auditoría de AWS, presupuestos ni plan de respaldo.

## Alcance

**Entra:** tablero y alarmas, WAF en CloudFront, CloudTrail, presupuesto con alertas, respaldo de RDS, retención de logs, cifrado con KMS propio en el entorno con datos reales, y una lista de verificación previa a datos reales.

**No entra:** certificaciones formales (ISO 27001 u otras) ni integración con el SOC del hospital.

## Diseño

| Área | Qué | Detalle |
|---|---|---|
| **Métricas y tablero** | CloudWatch Dashboard `hlf-<entorno>` | 5xx y latencia p90 del ALB, CPU y memoria de ECS, conexiones y almacenamiento de RDS, errores de las Lambdas, tokens y latencia de Bedrock (log estructurado de F0008), bytes escaneados por Athena |
| **Alarmas** | SNS → correo del equipo | API con 5xx > 5 % durante 5 minutos, tarea del backend reiniciando, RDS con almacenamiento < 20 %, corrida nocturna fallida (F0006), Lambda del asistente con errores |
| **Logs** | CloudWatch Logs con retención de 30 días (demo) o 1 año (real) | Logs en JSON con `id_correlacion` por petición. Sin datos personales en los logs: identificadores sí, nombres y teléfonos no |
| **WAF** | AWS WAF en CloudFront | Reglas administradas (Core, Known Bad Inputs), límite de peticiones por IP y bloqueo geográfico opcional (solo Chile en un piloto) |
| **Auditoría de AWS** | CloudTrail multirregión → bucket con bloqueo de objetos | Quién cambió la infraestructura o leyó secretos |
| **Costos** | AWS Budgets con alertas al 50 %, 80 % y 100 %, y etiquetas `proyecto` y `entorno` en todo | Incluye apagar el schedule de la demo (F0006) y detener RDS fuera del horario |
| **Respaldo** | Backups automáticos de RDS (7 días en demo, 35 en real) + AWS Backup con copia a otra región en real | Restauración probada una vez y documentada |
| **Cifrado** | Datos sintéticos: SSE-S3 y cifrado de RDS por defecto. Datos reales: claves KMS propias (CMK) por dominio (datos, canal, logs) | Permite revocar acceso con la clave |
| **Accesos** | Sin usuarios IAM con llaves: SSO para personas y OIDC para GitHub Actions | Rotación del secreto de RDS cada 30 días |
| **Datos en S3** | Lake Formation sobre `hlf_raw` e `hlf_historial` en real | Permisos por columna y fila para Athena |

## Lista de verificación antes de usar datos reales del HLF

- [ ] Región y residencia de los datos acordadas por escrito con el HLF (`docs/feature/F0001`, consideraciones AWS)
- [ ] F0007 activa: sin acceso anónimo, MFA obligatorio
- [ ] NAT Gateway y tareas en subred privada (`nat_gateways: 1`, F0004)
- [ ] Claves KMS propias, CloudTrail y WAF activos
- [ ] Verificación de identidad del asistente separada en un servicio con rol propio (F0002, límite de la verificación)
- [ ] Logs revisados: sin nombres, RUT ni teléfonos
- [ ] Restauración de RDS probada
- [ ] Revisión del comité de ética del HLF (ver `docs/mvp.md`: QALY y otras métricas excluidas a propósito)

## Cambios por carpeta

```
infra/stacks/observabilidad.py   tablero, alarmas, tema SNS, retención de logs, presupuesto
infra/stacks/seguridad.py        WAF, CloudTrail, claves KMS (según el entorno), AWS Backup
infra/config/entornos.py         flags por entorno: waf, cmk, retención, nat_gateways
servicios/comun/logs.py          logging JSON con id de correlación (lo usan la API y los servicios)
api/main.py                      middleware de id de correlación
infra/README.md                  runbook: alarmas, cómo reaccionar, cómo restaurar
```

## Tareas

1. Logging JSON con id de correlación en la API y en los servicios.
2. Stack de observabilidad con tablero y alarmas, y una prueba que dispare una alarma a propósito.
3. Stack de seguridad: WAF, CloudTrail, Backup y KMS según el entorno.
4. Presupuesto y etiquetas.
5. Runbook y prueba de restauración de RDS.
6. Revisar la lista de verificación con el equipo y el HLF.

## Criterios de aceptación

- Detener la tarea del backend genera una alarma por correo en menos de 10 minutos.
- El tablero muestra en una pantalla el estado de la API, la base, el proceso nocturno y el costo del mes.
- Una petición con un patrón de inyección SQL conocido es bloqueada por WAF antes de llegar al backend.
- Un `cdk diff` sobre el entorno real no muestra recursos sin etiquetas `proyecto` y `entorno`.

## Riesgos y decisiones abiertas

- **Costo fijo de WAF y CloudTrail en la demo:** activarlos solo en el entorno real, con un flag.
- **Retención:** acordar con el HLF los plazos legales de retención de conversaciones y registros clínicos.

## Resultado

Implementado y probado en local (templates sintetizados); el despliegue queda pendiente porque las credenciales de la cuenta del hackatón vencieron durante la implementación.

| Pieza | Implementación |
|---|---|
| Logs | `servicios/comun/logs.py`: JSON de una línea en AWS (texto legible en local, o `HLF_LOG_FORMATO=json`), con `id_correlacion`. Los mensajes que ya eran JSON (Bedrock de F0008, OCR de F0012) suben sus campos al primer nivel. Enmascara RUT, teléfonos y correos, y omite los campos `nombre`, `telefono`, `rut`, `correo` y `texto` |
| Correlación | Middleware de `api/main.py`: toma `X-Correlation-Id` (las Lambdas mandan su `aws_request_id`) o `X-Amz-Cf-Id` de CloudFront, o crea uno; lo devuelve en la respuesta y escribe una línea por petición a `/api` (método, plantilla de la ruta, estado, ms; sin cuerpo ni query). La corrida nocturna escribe `{"evento": "nocturno", "resultado": …}` |
| Tablero y alarmas | `infra/stacks/observabilidad.py`: tablero `hlf-<entorno>` (estado de las alarmas, costo del mes, API, backend, RDS, corrida nocturna, Lambdas, Bedrock y Athena). Alarmas al tema SNS, con correo desde `HLF_CORREO_ALARMAS` (el correo no va en el repo): `api-5xx` (> 5 % durante 5 minutos, incluye los 503 del ALB sin tareas), `backend-tareas` (tareas sanas bajo lo deseado en 2 de 3 minutos), `rds-almacenamiento` (< 20 %), `nocturno-fallido` (filtro de métricas de la línea de log + regla de EventBridge si la tarea muere con código ≠ 0) y una por Lambda |
| Costos | Presupuesto mensual (`presupuesto_usd`: 150 en demo, 400 en piloto) con alertas al 50, 80 y 100 % al mismo tema. Etiquetas `proyecto` y `entorno` en todos los stacks, verificadas recurso por recurso |
| Seguridad | `infra/stacks/seguridad.py`, por flag: WAF en CloudFront (Core, Known Bad Inputs, SQLi, límite por IP y solo Chile; `SizeRestrictions_BODY` solo cuenta, porque la vista Cargas sube CSV por la API), CloudTrail multirregión con validación de archivos y bucket con bloqueo de objetos (modo gobernanza, 1 año), y AWS Backup diario de RDS con copia a otra región |
| Cifrado | `cmk`: clave propia para el bucket de datos, RDS, los resultados de Athena y los logs del backend; los permisos de la KB, la consulta y GuardDuty incluyen la clave. El canal ya tenía las suyas (teléfonos, F0010; exámenes, F0012) |
| Respaldo | Backups automáticos de RDS de 1/7/35 días (dev/demo/piloto) en una ventana posterior a la corrida nocturna; rotación del secreto de RDS cada 30 días (rotación alojada de Secrets Manager, en las subredes del backend) |
| Entorno `piloto` | Nuevo en `infra/config/entornos.py`: reúne todo lo de la lista de verificación. dev y demo no pagan WAF ni CloudTrail (decisión del plan) |
| Runbook | `infra/README.md`: qué hacer con cada alarma, cómo seguir un `id_correlacion`, cómo restaurar RDS, y simulacros con `infra/scripts/simulacro.sh` (alarma forzada, tarea detenida, inyección SQL contra el WAF) |

**Pruebas:** `tests/test_logs.py` (JSON con correlación, ids externos solo con forma de id, enmascarado sin tocar fechas ni ids de paciente, excepciones, cabecera y línea por petición de la API). Infraestructura: tablero, alarmas con acción, período de `backend-tareas` ≤ 10 minutos, presupuesto con sus tres umbrales y los filtros de la corrida nocturna en demo; ni WAF ni CloudTrail en dev y demo; el piloto cumple la lista (NAT, tareas sin IP pública, KMS en bucket, RDS y logs, 35 días, rotación, WAF con SQLi asociado a CloudFront, CloudTrail con bloqueo de objetos, copia del respaldo en otra región, MFA, correo de alarmas) y todos sus recursos llevan `proyecto` y `entorno`.

**Pendiente al desplegar:** `HLF_CORREO_ALARMAS=<correo> npx aws-cdk@2 deploy HlfDemo-Observabilidad HlfDemo-Seguridad HlfDemo-Backend HlfDemo-Frontend -c entorno=demo`, confirmar la suscripción, correr `bash infra/scripts/simulacro.sh alarma` y `… tarea` (medir el tiempo hasta el correo) y probar una restauración de RDS. Lo que no es código (fuera de CDK a propósito): SSO para personas, OIDC para GitHub Actions cuando exista el despliegue desde CI, Lake Formation sobre `hlf_raw` e `hlf_historial` y los acuerdos de la lista con el HLF.

**Estado de la lista** (lo que el código ya resuelve en `piloto`): MFA obligatorio; NAT y subred privada; KMS propias, CloudTrail y WAF; logs sin datos personales (filtro + prueba). Siguen abiertos: región acordada por escrito, verificación del asistente en un servicio aparte, restauración probada y comité de ética.
