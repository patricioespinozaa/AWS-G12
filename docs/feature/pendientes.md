# Pendientes

Lo que quedó abierto al cerrar F0001 a F0005 (2026-10-15). Cada pendiente indica de dónde viene y dónde se resuelve. Lo que ya tiene un plan propio (F0006 a F0013) solo se menciona si afecta a algo ya implementado.

Prioridad: **Alta** = afecta la demo o la seguridad con datos reales · **Media** = conviene antes de un piloto · **Baja** = mejora.

## 1. Técnicos

| # | Pendiente | Origen | Se resuelve en | Prioridad |
|---|---|---|---|---|
| T1 | **Usuario de base con mínimo privilegio.** La API se conecta a RDS con el usuario maestro (el secreto que crea CDK). Los roles `hlf_app` (escribe `priorizacion` y `canal`, solo lee `raw`) y `hlf_cargas` (suma a `raw` sin poder borrar) existen, pero falta un usuario de login con esos roles, su secreto propio y apuntar la tarea a él | F0005 | F0013 | Alta (antes de datos reales) |
| T2 | ~~**Publicar a Athena desde RDS.** `python -m db athena publicar` sube los CSV locales. Con cargas incrementales, `raw` en RDS es la fuente de verdad: publicar debe leer de ahí (y `exportar` el historial nocturno)~~ **Resuelto en F0006:** `python -m db athena publicar --desde-rds` y, tras cada consolidación, el Parquet de `raw` y las noches tocadas. | F0003, F0005 | F0006 | Resuelto |
| T3 | ~~**Estimación de espera.** `priorizacion.estimacion_espera` existe, pero nada la llena. Las vistas del asistente no informan tiempo estimado hasta entonces~~ **Resuelto en F0006:** `priorizacion/estimacion.py` (`throughput_8_semanas`); la consolidación la guarda a cada fecha de corte. | F0002, F0003 | F0006 | Resuelto |
| T4 | ~~**Fecha de referencia provisoria.** Con RDS, "hoy" es la última fecha con datos (`fecha_max_datos`). Debe pasar a ser la fecha de corte de la base, fijada por cada carga: el fin de su periodo (`priorizacion.fecha_corte()`)~~ **Resuelto en F0006:** "hoy" = `priorizacion.fecha_corte()`, fijada por `raw.carga_lote.fecha_corte` de cada versión. | F0005 | F0006 | Resuelto |
| T5 | ~~**Particiones de `serie_nocturna`.** Solo existe la partición `DEFAULT`. A escala HLF (~9,5 M filas/año) hay que crear particiones anuales o mensuales antes de cargar datos reales~~ **Resuelto en F0006:** particiones anuales 2025–2027 y `priorizacion.asegurar_particion_serie(año)`, que la escritura llama sola. | F0002 | F0006 | Resuelto |
| T6 | **Despliegue desde GitHub Actions.** `deploy.yml` necesita un rol IAM con confianza OIDC en GitHub (`secrets.AWS_DEPLOY_ROLE_ARN`). No se comprobó si el rol del hackatón (`WSParticipantRole`) permite crearlo. Mientras tanto se despliega desde una máquina con Docker (`infra/README.md`) | F0004 | — | Media |
| T7 | **Pruebas con datos en CI.** El dataset no se versiona, así que en CI las pruebas que lo necesitan se saltan (marcador `datos`): corren 28 de 99. Falta un dataset sintético reducido en `data/synthetic/` que sí se pueda versionar | F0004 | — | Media |
| T8 | **Scripts de infraestructura duplicados.** `db/infra/crear_rds.sh` y `crear_s3_athena.sh` quedaron reemplazados por los stacks de CDK y solo se revisaron en sintaxis. Decidir si se eliminan o se marcan como alternativa manual | F0001, F0003 | — | Baja |
| T9 | **Verificación de identidad en un servicio aparte.** El rol del asistente puede marcar una conversación como verificada; para cerrar esa puerta, la verificación debe tener su propio rol | F0002 | F0010 / F0013 | Alta (antes de datos reales) |
| T10 | **Subida de archivos grandes.** Cargas y exámenes viajan por la API en base64 (límite 20 MB y 10 MB). Si una exportación real lo supera, pasar a URLs prefirmadas de S3 | F0005 | F0012 | Baja |
| T11 | **Convención CIE-10.** Los códigos del dataset tienen 3 caracteres; la normalización con punto (`E11.3`) aplica cuando lleguen subcategorías | F0001 | Cuando lleguen datos reales | Baja |
| T12 | **Diccionario de F0002 desactualizado.** El diccionario generado de columnas no incluye los cambios de F0005 (`estado_app`, rol `administracion`, columnas de versión en `raw`). Hay una nota en F0002 que los lista; falta regenerar los diagramas y las tablas | F0005 | — | Baja |
| T13 | ~~**Ajustar el plan F0007.** Con una sola usuaria, la matriz de roles se reduce a `administracion`. El documento todavía describe cinco roles~~ **Resuelto:** el plan quedó con un solo rol, `administracion`. | F0005 | F0007 | Resuelto |

## 2. Operación de la demo en AWS

| # | Pendiente | Detalle |
|---|---|---|
| O1 | **Credenciales temporales.** Las del `.env` (`WSParticipantRole`) vencen. Para volver a desplegar hay que renovarlas desde el portal del hackatón |
| O2 | **Costo encendido.** El entorno `demo` cuesta unos US$ 105 al mes las 24 horas: 2 tareas Fargate (~US$ 72), ALB (~US$ 18) y RDS (~US$ 15). Fuera de la demo: `aws ecs update-service … --desired-count 0` y `aws rds stop-db-instance` (`infra/README.md`). Presupuesto y alertas: F0013 |
| O3 | **Datos de prueba en la demo.** Quedaron una decisión de prueba en `IC-HLF-00417` (motivo "Prueba de persistencia F0005") y la carga 2 descartada en el historial. Se pueden dejar como ejemplo o limpiar |
| O4 | **Docker Desktop.** Se necesita corriendo en la máquina que despliega (CDK construye la imagen del backend). Ver T6 para desplegar sin depender de una máquina local |

## 3. Preguntas para el HLF

| # | Pregunta | Por qué importa |
|---|---|---|
| H1 | **¿Los identificadores se mantienen entre exportaciones?** (`id_paciente`, `id_solicitud`, `id_evento`, `id_cita`) | Las cargas por periodo suman por esas llaves. Si cambian en cada exportación, hace falta otra llave de cruce (por ejemplo, RUT cifrado) |
| H2 | **¿Quién responde clínicamente por lo que decide la Administradora?** | El principio del proyecto es que el equipo clínico decide. Conviene dejar por escrito qué criterios clínicos aplica y quién los respalda |
| H3 | **Si una solicitud vuelve a `en_espera` después de egresar en una exportación nueva, ¿es una corrección o un error?** | Hoy se aplica y se muestra como advertencia en la vista previa |
| H4 | **¿Qué datos de contacto existen (teléfono, RUT, fecha de nacimiento)?** | Los canales de WhatsApp y voz (F0010, F0011) los necesitan para identificar y verificar al paciente |
| H5 | **¿Quién aprueba que se informe al paciente un tiempo estimado de espera?** | `estimacion_espera.publicable` arranca en `false` hasta esa aprobación (F0006) |
| H6 | **Región y residencia de los datos, y plazos de retención** | Obligatorio antes de subir datos reales (F0001, F0013) |

## Cómo se actualiza

Cuando una feature resuelve un pendiente, se marca aquí como resuelto (~~tachado~~) con la feature que lo cerró, y se agregan los pendientes nuevos que deje.
