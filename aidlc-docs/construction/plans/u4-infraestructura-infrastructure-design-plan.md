# Plan de Infrastructure Design — U4 Infraestructura y lote en AWS

Base: secciones 3, 10, 13, 14 y 15 de `docs/contexto-tecnico.md`; la definición de U4 en `aidlc-docs/inception/application-design/unit-of-work.md`; y el código de U1–U3, que ya funciona en local.

U4 no agrega lógica de negocio. Toma las mismas funciones (`evaluar`, el copiloto, la lectura de la bandeja) y cambia **dónde corren** y **dónde se guardan**. Por eso no hay diseño funcional: esta etapa es diseño de infraestructura, seguida de generación de código (plantillas SAM, manejadores Lambda y adaptador de persistencia) y pruebas.

## Hechos verificados (2026-10-16, solo lectura)

- Cuenta `<ID_CUENTA_AWS>`, rol `WSParticipantRole` del workshop, región `us-east-1`. Políticas: `ws-default-policy`, `ws-bedrock-model-allowlist-policy-1`, `ws-dont-modify-policy-0`.
- La simulación de IAM **permite** CloudFormation, crear roles IAM y pasarlos, Lambda, Step Functions, DynamoDB, S3, API Gateway, Cognito, CloudFront, Glue, EventBridge Scheduler, Firehose, KMS y VPC. Bedrock sigue limitado a la lista de modelos permitidos.
- La simulación no evalúa condiciones por recurso. Algún recurso concreto podría fallar al desplegar; se sabrá con el primer `sam deploy`.
- **La cuenta es temporal y compartida.** Las cuentas de workshop suelen borrarse al terminar el evento. Todo lo que se despliegue ahí se puede perder.
- SAM CLI 1.169 y AWS CLI 2.38 instalados.

## Checklist

- [ ] Responder las preguntas
- [ ] Generar `aidlc-docs/construction/u4-infraestructura/infrastructure-design/infrastructure-design.md` (servicio por componente, IAM, cifrado, red, observabilidad, respaldo)
- [ ] Generar `aidlc-docs/construction/u4-infraestructura/infrastructure-design/deployment-architecture.md` (pilas SAM, parámetros por entorno, despliegue, rollback, desmontaje, costo estimado)
- [ ] Revisar cumplimiento de Security, Resiliency y PBT

---

## Preguntas

Responde con la letra después de `[Answer]:` y avisa con "listo".

### Pregunta I-1 — ¿Dónde se despliega?

A) **En la cuenta del workshop**, como entorno `dev`, solo con datos sintéticos. Se acepta que puede desaparecer al terminar el evento.

B) **En una cuenta AWS propia del equipo o del HLF.** Necesitas darme acceso y credenciales para esa cuenta.

C) **Solo generar y validar las plantillas** (`sam validate`, `cfn-lint`, `checkov`) **sin desplegar.** El despliegue se hace después en la cuenta definitiva.

X) Other (describe después de `[Answer]:`)

[Answer]: 

> Recomendación: **C** si la cuenta del workshop se cierra pronto, o **A** si quieres mostrar el sistema corriendo en AWS mientras dure el evento. Desplegar en una cuenta compartida es un cambio real de infraestructura y te voy a pedir confirmación antes de cada `sam deploy`.

### Pregunta I-2 — Alcance del despliegue

A) **Solo el lote:** motor + copiloto en Step Functions + Lambda, programados con EventBridge Scheduler; datos en S3 y salidas en DynamoDB; auditoría en S3 con Object Lock. La bandeja sigue en local, pero lee de AWS.

B) **Lote + bandeja publicada:** A más la bandeja accesible por navegador con login.

C) **Todo el diseño de la sección 3:** A + B + VPC privada con endpoints, WAF, CloudFront, Glue para la ingesta y KMS por dominio.

X) Other (describe después de `[Answer]:`)

[Answer]: 

> Recomendación: **A**. Es la parte que da valor real (el lote nocturno corriendo solo, con trazabilidad) y no expone ningún endpoint a internet. B y C agregan autenticación, red y costo fijo; se pueden sumar después sin rehacer A.

### Pregunta I-3 — Si la bandeja se publica (solo si I-2 = B o C)

A) **Streamlit en ECS Fargate** detrás de un ALB con autenticación de Cognito en el ALB. Reutiliza `app/bandeja.py`.

B) **React + API Gateway + Lambda + Cognito**, como dice el diseño (D6). Implica reescribir la interfaz.

C) No aplica (I-2 = A).

X) Other (describe después de `[Answer]:`)

[Answer]: 

> Recomendación: **C** si elegiste A en I-2. Si publicas, **A**: es mucho menos trabajo y mantiene la interfaz que ya probaste. React queda para la versión productiva.

### Pregunta I-4 — Red

A) **Sin VPC** en `dev`: las Lambdas usan los endpoints públicos de AWS sobre TLS, con IAM de mínimo privilegio. Sin costo fijo de red.

B) **VPC privada con endpoints de interfaz**, como en la sección 3.2 del diseño. Unos 10 endpoints, cerca de USD 7–8 al mes cada uno más tráfico, aunque no se use.

X) Other (describe después de `[Answer]:`)

[Answer]: 

> Recomendación: **A** para `dev` con datos sintéticos, documentado como desviación de SECURITY-07. **B** pasa a ser obligatorio antes de cargar datos reales.

### Pregunta I-5 — Cómo se despliega

A) **`sam deploy` manual** desde tu máquina, con confirmación de cada cambio (`--confirm-changeset`).

B) **GitHub Actions con OIDC**, como en la sección 15.2 del diseño. Requiere crear un proveedor OIDC y un rol en la cuenta, y configurar el repositorio de GitHub.

X) Other (describe después de `[Answer]:`)

[Answer]: 

> Recomendación: **A** ahora. B es lo correcto a largo plazo, pero en una cuenta temporal el proveedor OIDC se pierde con ella. Dejo el workflow de GitHub Actions escrito y validado, sin activarlo.

### Pregunta I-6 — Alertas operativas

A) **CloudWatch:** alarmas (lote sin terminar a las 06:00, errores, DLQ con mensajes, críticas sin revisar en 24 h) y un tema SNS con suscripción por correo. Necesito el correo destino.

B) **Solo métricas, logs y dashboard**, sin notificaciones.

X) Other (describe después de `[Answer]:`)

[Answer]: 

> Recomendación: **A**, con un correo del equipo. Si no quieres dar uno ahora, **B**, y el tema SNS queda creado sin suscriptores.

### Pregunta I-7 — Horario del lote y costo

El diseño programa el lote a las 01:00 (America/Santiago). En la cuenta del workshop, cada noche el copiloto analizaría las solicitudes que cambiaron, con Sonnet 5.

A) **Programado cada noche**, con `--max-llamadas` como tope diario (por ejemplo, 150).

B) **Programado pero deshabilitado**: se ejecuta a mano desde la consola o con un comando. Así no hay gasto sin que lo decidas.

X) Other (describe después de `[Answer]:`)

[Answer]: 

> Recomendación: **B** en `dev`. Con A, una cuenta olvidada sigue gastando tokens cada noche.

### Pregunta I-8 — Desmontaje

A) Incluir un comando documentado para **borrar todo** (`sam delete`, más vaciar los buckets). La auditoría con Object Lock no se puede borrar antes de su retención, así que en `dev` se usa una retención corta (1 día) en modo *governance*.

B) Retención como en producción (10 años, modo *compliance*) también en `dev`.

X) Other (describe después de `[Answer]:`)

[Answer]: 

> Recomendación: **A**. Con *compliance* y 10 años, ni siquiera un administrador puede borrar ese bucket. En una cuenta de prueba eso deja recursos que no se pueden limpiar.
