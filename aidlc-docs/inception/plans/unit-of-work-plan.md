# Plan de Units Generation — MVP para la demo

Objetivo: partir el diseño de `docs/contexto-tecnico.md` en unidades de trabajo y decidir cuáles entran al MVP de la demo del 16 de octubre. Lo que no entre queda documentado como trabajo futuro, sin perderse.

## Hechos verificados (15-10-2026)

- **Dataset:** completo en `data/dataset_hlf_ambulatorio/` (500 pacientes, 786 eventos, 2.487 mediciones, 2.188 bloques de agenda, 257 citas, 500 perfiles). Ignorado por git.
- **Cuenta AWS:** `<ID_CUENTA_AWS>`, rol de participante del workshop (`WSParticipantRole`), región `us-east-1`. Credenciales temporales.
- **Bedrock:** funciona con salida forzada por herramienta (`toolChoice`), que es lo que exige el copiloto. Probado con Claude Sonnet 5 (~2,2 s), Claude Haiku 4.5 (~0,7 s) y Nova Pro (~0,9 s).
- **Restricción:** la cuenta tiene una lista de modelos permitidos. Por ejemplo, Claude Sonnet 5.5, Haiku 5.5 y Opus 5.5 están **denegados**. Los perfiles `us.*` pueden enrutar la inferencia a otras regiones de EE. UU.
- **Región:** en la práctica queda `us-east-1` para la demo (tema T1 resuelto para el hackatón; para producción sigue abierto).

## Unidades propuestas

| Unidad | Componentes del diseño | Contenido |
|---|---|---|
| U1 Núcleo de datos y motor | C1 contrato, C2 ingesta, C3 repositorio, C4 calidad, C5 motor | Cargar perfiles, validar, fecha de corte, hallazgos DQ, puntaje explicado, alertas de gestión. Python puro + pruebas de ejemplo y PBT |
| U2 Copiloto | C6 | Bedrock en modo barrido sobre solicitudes con cambio; esquema `analisis-v1` y validación de citas |
| U3 Bandeja y vistas | C8 bandeja, C11 web | API + interfaz del clínico: lista priorizada, detalle con línea de tiempo citada, selector de fecha de corte, aceptar/ajustar/rechazar |
| U4 Infraestructura y lote | Step Functions, SAM, DynamoDB, S3, auditoría (C9) | Despliegue del lote y de la API en AWS |
| U5 Box | C7 | Indicadores de ocupación, sobretiempo e inasistencia; propuesta de agenda |
| U6 FHIR | C10 | Exportación de RiskAssessment y Provenance |

Dependencias: U1 → (U2, U3, U5) → U4. U6 depende de U1 y U2. U1 no depende de nada y se puede empezar ya.

## Checklist

- [x] Responder las preguntas de abajo
- [x] Generar `aidlc-docs/inception/application-design/unit-of-work.md` (unidades, responsabilidades, organización del código)
- [x] Generar `aidlc-docs/inception/application-design/unit-of-work-dependency.md` (matriz de dependencias y orden)
- [x] Generar `aidlc-docs/inception/application-design/unit-of-work-story-map.md` (RF-01..RF-13 → unidades; sin User Stories)
- [x] Validar límites y dependencias; confirmar que todo RF quedó asignado o marcado fuera del MVP

---

## Preguntas

Responde con la letra después de `[Answer]:`. Cada una trae mi recomendación. Avísame con "listo".

### Pregunta U-1 — ¿Qué unidades entran al MVP?

A) U1 + U2 + U3, corriendo en local; U4, U5 y U6 fuera (se muestran con diagramas)

B) U1 + U2 + U3 + U4: lo mismo, pero desplegado en AWS

C) U1 + U2 + U3 + U5 en local (suma el eje box); U4 y U6 fuera

D) Solo U1 + U3 (sin IA generativa)

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. Es lo que se alcanza a terminar bien en un día y cubre lo que evalúa el desafío (detectar, reevaluar, explicar, que el médico decida) más la IA generativa. Si sobra tiempo, U4 en versión mínima.

### Pregunta U-2 — ¿Cuántas personas programan y cómo se reparten?

A) Una sola persona (o el agente): se construye en orden U1 → U2 → U3

B) 2–3 personas en paralelo: una en U1, otra en U3 contra datos de ejemplo del motor, otra en U2

C) 4 o más personas: una por unidad

X) Other (describe después de `[Answer]:`)

[Answer]: B

> Recomendación: depende del equipo. Si es **B**, primero se fija el formato de salida del motor (sección 6.8 del contexto técnico) para que U2 y U3 trabajen contra él sin esperar a U1.

### Pregunta U-3 — Modelo de Bedrock para el copiloto

A) Claude Sonnet 5 (`us.anthropic.claude-sonnet-5`): mejor calidad de análisis, ~2 s por llamada

B) Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`): más rápido y barato, calidad menor

C) Amazon Nova Pro (`us.amazon.nova-pro-v1:0`): modelo de Amazon, rápido

D) Configurable: Sonnet 5 por defecto, con cambio por variable de entorno

X) Other (describe después de `[Answer]:`)

[Answer]: D

> Recomendación: **D**. Sonnet 5 para la demo; Haiku 4.5 como respaldo si hay límites de cuota. El barrido solo corre sobre solicitudes con cambio, así que el volumen es bajo.

### Pregunta U-4 — Tecnología de la interfaz (U3)

A) React + TypeScript, como dice el diseño (más trabajo, más cercano a producción)

B) Streamlit (Python): mucho más rápido de construir para la demo; se reemplaza por React después

C) API (FastAPI) + HTML simple

X) Other (describe después de `[Answer]:`)

[Answer]: B

> Recomendación: **B** para el hackatón. Es otra desviación del diseño (D6), así que la dejaría documentada como decisión de demo. Si eliges B, las reglas de seguridad de cabeceras y CORS (SECURITY-04/08) se marcan N/A para la demo local y se exigen en la versión React.

### Pregunta U-5 — Persistencia en la demo

A) Archivos locales (Parquet/JSON) para propuestas, análisis y decisiones

B) DynamoDB y S3 reales en la cuenta del workshop

C) SQLite local

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A** si U-1 = A; **B** si U-1 = B. Con A, la auditoría inmutable (Object Lock) no se demuestra en vivo; se registra igual como archivos solo de agregado.

### Pregunta U-6 — Modos del copiloto en el MVP

A) Solo barrido (nocturno, sin herramientas, salida forzada)

B) Barrido + reactivo (desde la bandeja, con herramientas)

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. Es más simple y más fácil de controlar. El reactivo agrega el bucle de herramientas, que es lo más riesgoso de terminar a tiempo.

### Pregunta U-7 — Organización del código

A) Un solo repositorio con la estructura de la sección 15.1 del contexto técnico (`motor_reglas/`, `copiloto/`, `tests/`, etc.)

B) Un solo paquete Python `hlf_priorizacion/` con submódulos, más una carpeta `app/` para la interfaz

X) Other (describe después de `[Answer]:`)

[Answer]: B

> Recomendación: **B** para el MVP: un único paquete instalable es más simple de probar y de importar desde la interfaz. Se puede reorganizar según 15.1 al pasar a producción.

### Pregunta U-8 — Seguridad de las credenciales del workshop

Vi que agregaste `secret.txt` al `.gitignore` (está ignorado; no leí su contenido). La AWS CLI ya tiene credenciales en `~/.aws/credentials`.

A) Borrar `secret.txt` del proyecto: las credenciales ya están en la CLI y no hace falta tenerlas en el repo

B) Dejarlo; está ignorado por git

X) Other (describe después de `[Answer]:`)

[Answer]: A

> Recomendación: **A**. Aunque esté ignorado, un archivo con secretos dentro del proyecto se puede copiar, comprimir o compartir por accidente. Las credenciales son temporales, pero igual dan acceso a la cuenta.
