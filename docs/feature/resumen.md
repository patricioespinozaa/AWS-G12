# Resumen de features

Detalle, dependencias y orden de implementación en [README.md](README.md).

| # | Plan | Qué cubre | Estado | Tamaño |
|---|---|---|---|---|
| [F0001](F0001-subida-datos-aws.md) | Datos crudos en RDS | Esquema `raw` en RDS PostgreSQL con llaves, `CHECK` y bitácora de cargas; módulo `db/` para crear, cargar (sincronizando por llave primaria), verificar y borrar de forma segura | Hecha (probada en AWS) | — |
| [F0002](F0002-modelo-datos-canales.md) | Modelo de datos de la app y de los canales | Esquemas `priorizacion` (propuestas, decisiones auditadas, agenda, estimación de espera) y `canal` (WhatsApp y voz: contacto cifrado, consentimiento, verificación, turnos, divulgación); vistas del asistente filtradas por el paciente verificado; roles | Hecha (DDL en RDS de AWS; la app aún no lo usa) | — |
| [F0003](F0003-flujos-aws-datos.md) | Estructura de datos de los flujos AWS | Reloj de la demo (fecha de corte única), esquema `consulta` (Knowledge Base y trazabilidad de preguntas) y capa S3 + Athena: `raw` en Parquet tipado e historial nocturno particionado por fecha | Hecha (probada en AWS) | — |
| [F0004](F0004-despliegue-frontend-backend.md) | Despliegue del frontend y el backend | CloudFront + S3 para el frontend; ECS Fargate detrás de un balanceador interno al que solo llega CloudFront; CDK en `infra/`; CI/CD | Hecha (desplegada en `demo`) | L |
| [F0005](F0005-persistencia-app-rds.md) | La app usa RDS y cargas por periodo | Fase A: el motor lee `raw` de RDS y el registro pasa de SQLite a PostgreSQL, con la Administradora como única usuaria; routers y varias tareas. Fase B: vista para subir los CSV de cada periodo, con vista previa, versiones e historial; los datos nuevos se suman a la historia de cada paciente | Hecha (desplegada en `demo`) | XL |
| [F0006](F0006-proceso-nocturno-reloj.md) | Consolidación nocturna, recálculo por carga e histórico | Un pipeline con dos entradas: la vista Cargas (manual) y una consolidación nocturna programada que toma las exportaciones de cada día desde un buzón en S3, para que el HLF pueda conectarse en el futuro sin cargar a mano. Fija la fecha de corte ("datos al …"), extiende la simulación histórica, calcula la estimación de espera y publica en Athena | Implementado | L |
| [F0007](F0007-autenticacion-roles.md) | Autenticación y roles | Cognito, token validado en la API y permisos por rol | Plan | M |
| [F0008](F0008-explicaciones-bedrock.md) | Explicaciones con Bedrock | El código ya existe; falta conectarlo a AWS (permisos, guardrail, costo) | Plan | S |
| [F0009](F0009-consulta-lenguaje-natural.md) | Consulta en lenguaje natural | Knowledge Base + SQL en Athena para el equipo clínico | Plan | L |
| [F0010](F0010-asistente-whatsapp.md) | Asistente por WhatsApp | Núcleo común a todos los canales, verificación de identidad y simulador en la app | Plan | L |
| [F0011](F0011-asistente-voz.md) | Asistente por voz | Amazon Connect + Lex + Polly, reutilizando el núcleo de F0010 | Plan | M |
| [F0012](F0012-examenes-externos-ocr.md) | Exámenes externos | Subida segura a S3 y lectura con Textract y Bedrock citando el texto, siempre validada por una persona | Plan | M |
| [F0013](F0013-observabilidad-seguridad-costos.md) | Observabilidad, seguridad y costos | Alarmas, WAF, CloudTrail, presupuesto, respaldos, y una lista de verificación antes de usar datos reales | Plan | M |

Tamaño: S (≤ ½ día), M (1 día), L (2 a 3 días).

Pendientes de las features implementadas y preguntas para el HLF: [pendientes.md](pendientes.md).
