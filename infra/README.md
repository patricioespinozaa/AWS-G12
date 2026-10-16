# Infraestructura en AWS (CDK)

Despliega la app completa: frontend en S3 + CloudFront, backend en ECS Fargate detrás de un ALB interno, bucket de datos, workgroup de Athena y RDS PostgreSQL. Diseño y decisiones en [docs/feature/F0004-despliegue-frontend-backend.md](../docs/feature/F0004-despliegue-frontend-backend.md).

```
infra/
├── app.py                 punto de entrada: arma los 4 stacks del entorno elegido
├── cdk.json               "python app.py" y entorno por defecto (dev)
├── config/entornos.py     parámetros de dev y demo (NAT, RDS, CPU, memoria, retención)
├── stacks/
│   ├── red.py             VPC 2 AZ y security groups (ALB → backend → RDS)
│   ├── datos.py           bucket de datos, workgroup de Athena, RDS opcional
│   ├── identidad.py       Cognito: User Pool de la Administradora, grupo administracion, Hosted UI (F0007)
│   ├── ia.py              Bedrock: guardrail y política de invocación del modelo (F0008)
│   ├── consulta.py        Knowledge Bases (equipo clínico y preguntas del paciente) en S3 Vectors (F0009, F0010)
│   ├── asistente.py       KMS de teléfonos y exámenes, secretos, WhatsApp (F0010) y escaneo de exámenes (F0012)
│   ├── voz.py             Amazon Connect, bot de Lex V2 y Lambda de voz (F0011)
├── connect/flujo_entrante.json  flujo de contacto versionado
│   ├── backend.py         ECS Fargate (imagen docker/backend), ALB interno
│   ├── seguridad.py       WAF en CloudFront, CloudTrail, AWS Backup (por flag, F0013)
│   ├── observabilidad.py  tablero, alarmas a SNS, filtros de logs y presupuesto (F0013)
│   ├── nocturno.py        consolidación nocturna: EventBridge Scheduler → tarea ECS (solo con RDS)
│   └── frontend.py        bucket web, CloudFront (S3 con OAC + /api/* por VPC origin), app client de Cognito
├── scripts/crear_cuenta.sh  crea la cuenta de una Administradora
├── scripts/simulacro.sh     simulacros de alarma, caída del backend y WAF (F0013)
└── tests/test_stacks.py   garantías de seguridad sobre los templates sintetizados
```

| Stack | Contiene | Depende de |
|---|---|---|
| `Hlf<Entorno>-Red` | VPC, subredes, endpoint S3, security groups | — |
| `Hlf<Entorno>-Datos` | Bucket de datos, workgroup `hlf-priorizacion-<entorno>`, RDS (solo demo) | Red |
| `Hlf<Entorno>-Identidad` | User Pool, grupo `administracion`, dominio del login | — |
| `Hlf<Entorno>-Ia` | Guardrail de Bedrock (versión fija) y política IAM de invocación del modelo | — |
| `Hlf<Entorno>-Consulta` | Bucket e índice de S3 Vectors, Knowledge Base (Titan V2), fuente de datos `kb/equipo/`, políticas de consulta (KB y Athena) y de preparación | Datos |
| `Hlf<Entorno>-Asistente` | Clave KMS de teléfonos, pepper del HMAC y secreto de servicio (Secrets Manager), tema SNS de WhatsApp entrante y su Lambda; clave KMS de exámenes y, con `examenes_guardduty`, GuardDuty Malware Protection sobre `canal/evidencias/`, regla de EventBridge y Lambda del resultado (F0012) | Datos |
| `Hlf<Entorno>-Voz` | Instancia de Connect, horario, cola, flujo, bot de Lex `es_US` y su Lambda (solo con `voz=True`) | Asistente, Datos |
| `Hlf<Entorno>-Seguridad` | WAF (`waf`), CloudTrail con bloqueo de objetos (`cloudtrail`), plan de AWS Backup de RDS (`respaldo`); vacío en dev y demo | Datos |
| `Hlf<Entorno>-RespaldoCopia` | Bóveda de AWS Backup en `respaldo_region_copia` (solo piloto) | — |
| `Hlf<Entorno>-Observabilidad` | Tablero `hlf-<entorno>`, tema SNS de alarmas (correo de `HLF_CORREO_ALARMAS`), alarmas, filtros de la corrida nocturna, presupuesto | Datos, Backend, Asistente, Voz |
| `Hlf<Entorno>-Backend` | Cluster ECS, tarea, servicio, ALB interno, logs; en demo, la tarea nocturna y su programación | Red, Datos |
| `Hlf<Entorno>-Frontend` | Bucket web, CloudFront, función SPA, regla CloudFront → ALB, app client de Cognito y parámetro SSM `/hlf/<entorno>/cognito` | Red, Backend, Identidad |

**Entornos** (`-c entorno=…`): `dev` (sin RDS; `cdk destroy` borra todo) y `demo` (con RDS; los datos sobreviven a un destroy: bucket `RETAIN`, RDS con snapshot y protección contra borrado).

## Requisitos

- AWS CLI v2 con credenciales de la cuenta (en el hackatón, las variables de `.env`: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_DEFAULT_REGION`).
- Node.js 20 o superior (para la CLI de CDK, vía `npx aws-cdk@2`).
- Python 3.11 con `pip install -r infra/requirements.txt`.
- Docker corriendo (CDK construye la imagen del backend al desplegar).

```bash
set -a; . ./.env; set +a                 # en Git Bash; en PowerShell, definir las variables a mano
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=$AWS_DEFAULT_REGION
```

## Primer despliegue (cuenta vacía)

El orden importa: el backend descarga los CSV de S3 al arrancar, así que deben estar publicados antes.

```bash
cd infra
npx aws-cdk@2 bootstrap                                     # una vez por cuenta y región

# 1. Red y datos (RDS tarda entre 5 y 10 minutos)
npx aws-cdk@2 deploy HlfDemo-Red HlfDemo-Datos -c entorno=demo --outputs-file salidas.json

# 2. Publicar el dataset en S3 (CSV + Parquet + tablas de Athena), desde la raíz del repo
cd ..
export HLF_S3_BUCKET=<salida Bucket>  HLF_ATHENA_WORKGROUP=hlf-priorizacion-demo
python -m db athena publicar

# 3. Frontend compilado, backend y CloudFront
(cd web && npm ci && npm run build)
cd infra && npx aws-cdk@2 deploy --all -c entorno=demo --outputs-file salidas.json
```

La URL de la app es la salida `Url` del stack Frontend (`https://xxxx.cloudfront.net`).

### Cargar RDS (solo `demo`)

RDS está en una subred aislada, sin acceso desde internet. La carga se corre **dentro de la VPC** como una tarea puntual con la misma imagen del backend: el `entrypoint` descarga los CSV de S3 y después ejecuta el comando.

```bash
# Valores de las salidas del stack HlfDemo-Backend
aws ecs run-task --cluster <SalidaCluster> --task-definition <SalidaDefinicionTarea> --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<SalidaSubredes>],securityGroups=[<SalidaSecurityGroup>],assignPublicIp=<SalidaIpPublica>}" \
  --overrides '{"containerOverrides":[{"name":"api","command":["python","-m","db","restaurar"]}]}'
```

El mismo patrón sirve para `python -m db permisos`, `python -m db verificar` o `python -m db reloj --fijar 2026-06-01`. El resultado queda en los logs del backend.

## Operación

| Tarea | Comando |
|---|---|
| Desplegar un cambio de código o de infraestructura | `npx aws-cdk@2 deploy --all -c entorno=demo` (reconstruye la imagen si cambió) |
| Ver qué va a cambiar | `npx aws-cdk@2 diff -c entorno=demo` |
| Ver logs del backend | `aws logs tail <SalidaGrupoLogs> --follow` |
| Reiniciar el backend | `aws ecs update-service --cluster <SalidaCluster> --service <SalidaServicio> --force-new-deployment` |
| Sumar los datos de un periodo nuevo | Vista **Cargas** de la app (subir, vista previa, confirmar). Desde la línea de comandos, como tarea ECS: `python -m db cargar --incremental --periodo DESDE:HASTA --datos <carpeta> --confirmar` |
| Dejar una exportación para la consolidación nocturna (F0006) | `aws s3 cp <carpeta> s3://<bucket>/hlf/entrada/<AAAA-MM-DD>/ --recursive` (CSV y `periodo.json` opcional). A las 02:00 (Santiago) se suma a `raw` y se consolida; queda en Cargas como versión nueva, o `fallida` con archivo y línea |
| Sincronizar la Knowledge Base (F0009) | Botón "Sincronizar" de la vista Consulta, o `aws ecs run-task` con `<SalidaTareaNocturna>` y el comando `python -m servicios.preparacion_kb`. La noche lo hace sola cuando entran datos nuevos |
| Correr la consolidación nocturna ahora | `aws ecs run-task` con `<SalidaTareaNocturna>`, las subredes y el SG de las salidas (`--launch-type FARGATE`) |
| Reconstruir `raw` desde la historia completa | `python -m db restaurar` como tarea ECS (borra lo que no venga en los CSV publicados: solo para reconstruir) |
| Probar los templates | `cd infra && python -m pytest tests -q` |
| Destruir | `npx aws-cdk@2 destroy --all -c entorno=dev` (en `demo`, el bucket de datos y la RDS se conservan) |

**Consolidación (F0006):** confirmar una carga responde de inmediato y el recálculo corre en segundo plano (la app muestra el aviso hasta que termina). La tarea nocturna (`servicios.nocturno`) hace lo mismo con lo que haya en el buzón y, al terminar, publica en S3 el Parquet de `raw` y las noches tocadas del historial para Athena. Si no hay nada nuevo, igual deja una corrida en la bitácora.

**Primer arranque del backend:** calcula la serie nocturna completa (unos 20 s en un portátil; puede ser varias veces más en Fargate con 1 vCPU). El health check espera 6 minutos antes de marcar la tarea como fallida.

**Dónde vive el estado (F0005):**
- `demo` (con RDS): la API lee `raw` de la base y guarda decisiones, propuestas, serie y canal en `priorizacion` y `canal`. Sobrevive a reinicios y redespliegues. Corren **2 tareas** y el despliegue no tiene corte; las tareas se sincronizan por la versión que guarda la base. Al arrancar, la API **aplica las migraciones pendientes** (idempotentes, bajo un candado), así una versión nueva nunca corre sobre un esquema viejo.
- `dev` (sin RDS): la API guarda en SQLite dentro del contenedor y se pierde al reiniciar. Corre una sola tarea con reemplazo con corte.

## Cuentas (F0007)

Solo entra la Administradora. Una cuenta por persona, nunca compartida: cada carga y decisión queda a su nombre.

| Tarea | Comando |
|---|---|
| Crear una cuenta | `ENTORNO=demo bash infra/scripts/crear_cuenta.sh <usuario> "<Nombre Apellido>" [correo]`. Imprime una clave temporal; Cognito pide cambiarla en el primer ingreso |
| Ver las cuentas que ya entraron | `python -m db usuarios` (como tarea ECS, igual que `restaurar`) |
| Quitar el acceso | `aws cognito-idp admin-disable-user --user-pool-id <SalidaUserPool> --username <usuario>` (no puede volver a iniciar sesión) y `python -m db usuarios --desactivar <sub>` (corta en menos de 30 s, aunque su sesión siga abierta) |

## Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El despliegue del backend se revierte solo | El contenedor no arrancó (circuit breaker) | `aws logs tail <SalidaGrupoLogs>`. Si dice "No hay datos", falta `python -m db athena publicar` |
| La web carga pero `/api/*` responde 502 o 504 | CloudFront no llega al ALB | Revisar que el SG del ALB tenga la regla desde la prefix list `com.amazonaws.global.cloudfront.origin-facing`. Si no basta, permitir el SG `CloudFront-VPCOrigins-Service-SG` que crea CloudFront |
| `cdk deploy` falla al construir la imagen | Docker no está corriendo | Iniciar Docker Desktop |
| La app responde 503 "La autenticación no está disponible" | La API no pudo leer el parámetro `/hlf/<entorno>/cognito` (p. ej. justo después del primer despliegue, antes de que termine el stack Frontend) | Esperar a que termine `cdk deploy`; la API vuelve a leerlo cada 5 minutos |
| Una exportación del buzón quedó `fallida` | Errores de validación (ver Cargas, con archivo y línea) | Corregir los CSV en la misma carpeta del buzón: con archivos distintos se vuelve a procesar la noche siguiente. Las entregas posteriores esperan a que se corrija |

## Runbook (F0013)

Las alarmas llegan al tema `hlf-<entorno>` de SNS y, si se desplegó con `HLF_CORREO_ALARMAS=<correo>`, por correo (confirmar la suscripción en el primer correo de AWS). El tablero `hlf-<entorno>` de CloudWatch muestra en una pantalla la API, el backend, la base, la corrida nocturna, las Lambdas, Bedrock, Athena y el costo del mes (el costo requiere activar "Receive Billing Alerts" en la consola de facturación).

| Alarma | Qué significa | Qué hacer |
|---|---|---|
| `api-5xx` | Más del 5 % de las peticiones con 5xx durante 5 minutos | `aws logs tail <SalidaGrupoLogs> --since 15m --filter-pattern '{ $.nivel = "ERROR" }'`. Cada línea trae `id_correlacion`: seguirlo con `--filter-pattern '{ $.id_correlacion = "<id>" }'`. Si es la base, revisar la alarma de RDS; si es Bedrock, la app sigue con las explicaciones por reglas |
| `backend-tareas` | Menos tareas sanas que las deseadas durante 2 de 3 minutos | ECS reemplaza la tarea solo. Si sigue: `aws ecs describe-services` (eventos) y los logs del arranque. Un despliegue fallido se revierte solo (circuit breaker) |
| `rds-almacenamiento` | Menos del 20 % libre | El almacenamiento crece solo hasta 50 GB; si llega ahí, subir `max_allocated_storage` en `stacks/datos.py` y desplegar |
| `nocturno-fallido` o el aviso "la consolidación nocturna terminó con error" | Entrega rechazada, error de la corrida o tarea muerta (memoria, imagen) | Vista **Cargas** (archivo y línea del error) y `aws logs tail <SalidaGrupoLogs> --log-stream-name-prefix nocturno`. Corregir y volver a correr (ver Operación) |
| `lambda-whatsapp`, `lambda-voz`, `lambda-escaneo-examenes` | Errores de la Lambda (casi siempre: la API no responde o falta el secreto) | `aws logs tail /aws/lambda/<función>`. Los mensajes de WhatsApp perdidos no se reintentan: revisar la vista Derivaciones |
| Presupuesto al 50/80/100 % | Gasto real del mes sobre `presupuesto_usd` | Revisar Cost Explorer por servicio. Para cortar: `--desired-count 0`, `aws rds stop-db-instance`, desactivar la programación nocturna (`aws scheduler update-schedule … --state DISABLED`) |

**Simulacros** (criterios de aceptación): `bash infra/scripts/simulacro.sh alarma` (llega el correo), `… tarea` (detiene una tarea: la alarma llega antes de 10 minutos) y, en piloto, `… waf` (una inyección SQL vuelve 403 sin llegar al backend).

**Restaurar RDS** (probar una vez antes de datos reales y anotar el tiempo):
1. `aws rds describe-db-snapshots --db-instance-identifier <instancia>` (automáticos: 7 días en demo, 35 en piloto; en piloto también los puntos de AWS Backup y su copia en `us-west-2`).
2. `aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier <instancia> --target-db-instance-identifier hlf-restaurada --use-latest-restorable-time --db-subnet-group-name <grupo> --vpc-security-group-ids <SG de RDS>` (o `restore-db-instance-from-db-snapshot`).
3. Verificar la copia con `HLF_DB_HOST=<endpoint nuevo> python -m db verificar` desde una tarea ECS.
4. Para cambiar a la copia: apuntar `HLF_DB_HOST` del backend a ella (o renombrar instancias) y desplegar. La copia no la administra CDK: importarla o reemplazar la original con calma.

**Logs:** JSON de una línea (`servicios/comun/logs.py`) con `id_correlacion` (viene de la Lambda, de CloudFront o se crea), sin nombres, RUT, teléfonos ni correos: se enmascaran aunque alguien los registre por descuido. Retención: 7 días en dev, 30 en demo y 365 en piloto.

## Entorno `piloto` (datos reales, F0013)

`-c entorno=piloto` activa lo que la lista de verificación exige: NAT y tareas en subred privada, claves KMS propias para datos y logs, WAF (reglas administradas, inyección SQL, límite por IP y solo Chile), CloudTrail multirregión con bloqueo de objetos, AWS Backup diario con copia a otra región, backups de RDS de 35 días, rotación del secreto de RDS cada 30 días, MFA obligatorio, logs de un año, sin voz y sin estimación publicable. Debe desplegarse en `us-east-1` (el WAF de CloudFront vive ahí) o en otra región solo si se mueve el WAF. Lo que no es código queda en la lista de `docs/feature/F0013-observabilidad-seguridad-costos.md` (SSO, OIDC para CI, Lake Formation, acuerdos con el HLF).

## Costo aproximado (us-east-1, demo, 24 h al día)

Fargate (1 vCPU, 3 GB) ~US$ 36/mes; ALB ~US$ 18/mes; RDS `db.t4g.micro` ~US$ 15/mes; CloudFront, S3 y Athena, centavos con este volumen. Sin NAT Gateway (ahorra ~US$ 32/mes). Para no pagar fuera de la demo: `aws ecs update-service … --desired-count 0` y `aws rds stop-db-instance`.
