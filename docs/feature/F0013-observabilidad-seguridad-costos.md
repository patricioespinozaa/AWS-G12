# F0013 · Observabilidad, seguridad y control de costos

**Estado:** Plan · **Depende de:** F0004 (se amplía con cada feature que agrega servicios) · **Tamaño:** M

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
