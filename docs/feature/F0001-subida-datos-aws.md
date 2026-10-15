# Feature: Subida de datos crudos a AWS (RDS PostgreSQL)

Esta feature traslada los datos crudos del proyecto desde los archivos CSV locales a una base de datos relacional administrada PostgreSQL en AWS. El objetivo es dejar de depender de archivos planos leídos con pandas y pasar a una única fuente de verdad consultable con SQL: los conjuntos de datos crudos viven como tablas, con integridad referencial explícita y acceso uniforme tanto para el motor de dominio como para futuras integraciones.

El modelo de datos de origen está documentado y verificado en `docs/modelo-datos-raw.md`.

## Decisión y alcance

**Servicio elegido: Amazon RDS for PostgreSQL** (instancia clásica, single-AZ, `db.t4g.micro`, 20 GB gp3, cifrado en reposo). La comparación con las alternativas está en [Decisión de servicio](#decisión-de-servicio).

La carga se hace con el módulo `db/` (`python -m db restaurar`): crea el esquema, carga los CSV y verifica en un solo comando, para poder reconstruir la base rápido si se borra. Ver [Script de carga](#script-de-carga-módulo-db).

Opcionalmente, los CSV originales se dejan también en un bucket S3 (`raw/`, con versionado y cifrado) como copia inmutable.

Dentro de la misma base, la información se separa en dos esquemas:

- Esquema `raw`: las tablas de datos crudos, inmutables y de solo lectura. Es el foco de este documento.
- Esquema `priorizacion`: las tablas que genera el sistema (serie nocturna, propuestas, factores, decisiones clínicas, evidencia del paciente). Se resume en [Esquema priorizacion](#esquema-priorizacion-siguiente-paso) y se detalla en una iteración posterior.

## Modelo relacional base (esquema raw)

El esquema `raw` contiene 7 tablas: las 6 que vienen como CSV más `box`, una dimensión derivada. La tabla maestra es `pacientes`; las tablas de paciente se relacionan con ella por `id_paciente`. `agenda_box` y `citaciones` se relacionan con `box` por `id_box`.

| Tabla | Filas | Grano (1 fila =) | Llave (PK/FK) |
|-------|-------|------------------|---------------|
| pacientes | 500 | un paciente | PK `id_paciente` |
| lista_espera | 500 | una solicitud en lista de espera | PK `id_solicitud`, FK `id_paciente` |
| eventos_clinicos | 786 | un evento clínico de un paciente | PK `id_evento`, FK `id_paciente` |
| mediciones | 2487 | una medición de un paciente | PK compuesta (`id_paciente`, `fecha_medicion`, `tipo_medicion`), FK `id_paciente` |
| box | 20 | un box del hospital (derivada) | PK `id_box` |
| agenda_box | 2188 | el bloque de un box en un día | PK compuesta (`id_box`, `fecha`), FK `id_box` → `box` |
| citaciones | 257 | una citación de un paciente a un box | PK `id_cita`, FK `id_paciente`, FK `id_box` → `box` |

Cobertura parcial esperada (relaciones 1:0..N): 381 de 500 pacientes tienen eventos clínicos, 451 de 500 tienen mediciones y 237 de 500 han sido citados. La integridad referencial fue verificada: 0 registros huérfanos en todas las llaves foráneas, y 0 duplicados en las llaves compuestas.

> **Por qué existe `box`.** En `agenda_box`, `id_box` se repite cada día, así que no puede ser destino de una llave foránea (PostgreSQL exige que la columna referenciada sea única). Tampoco sirve una FK de `citaciones` por (`id_box`, `fecha_cita`): 118 de 257 citas no tienen bloque para ese box ese día. `box` se deriva de los `id_box` distintos de `agenda_box`.

### pacientes

Tabla maestra. PK: `id_paciente`.

| Columna | Tipo PostgreSQL | Descripción / valores |
|---------|-----------------|-----------------------|
| id_paciente | text | **PK**. Identificador del paciente (`PAC-HLF-00001`..`PAC-HLF-00500`) |
| nombre_fantasia | text | Nombre ficticio, no real |
| edad | integer | Edad del paciente (19-90) |
| sexo | text | `F` o `M` |
| comuna | text | Red Sur Oriente, 7 comunas |
| prevision | text | FONASA A/B/C/D o ISAPRE |
| nivel_socioeconomico | text | `bajo` / `medio-bajo` / `medio` |
| fallecido | boolean | Indica si el paciente falleció |
| fecha_defuncion | date | Fecha de defunción; NULL si no falleció |

### lista_espera

PK: `id_solicitud`. FK: `id_paciente` -> `pacientes`. Relación `pacientes` 1:1 `lista_espera`.

| Columna | Tipo PostgreSQL | Descripción / valores |
|---------|-----------------|-----------------------|
| id_paciente | text | **FK** -> `pacientes.id_paciente` |
| id_solicitud | text | **PK**. Identificador de solicitud (`IC-HLF-#####`) |
| especialidad | text | 7 especialidades |
| sub_especialidad | text | 15 valores posibles |
| diagnostico_cie10 | text | 17 códigos CIE-10, todos de 3 caracteres (sin subcategoría ni punto) |
| diagnostico_texto | text | Descripción legible del diagnóstico |
| prioridad_inicial | text | `alta` / `media` / `baja` |
| fecha_ingreso_lista | date | Fecha de ingreso a la lista de espera (2025-04-21 a 2026-09-30) |
| origen_derivacion | text | CESFAM/APS, Urgencia, Hospitalización, Otro hospital red |
| estado | text | `en_espera` / `atendido` / `fallecido` (categorías posibles además: `citado`, `egresado`). Es solo el estado final: no trae fecha de egreso |

### eventos_clinicos

PK: `id_evento`. FK: `id_paciente` -> `pacientes`. Relación `pacientes` 1:0..N `eventos_clinicos`.

| Columna | Tipo PostgreSQL | Descripción / valores |
|---------|-----------------|-----------------------|
| id_paciente | text | **FK** -> `pacientes.id_paciente` |
| id_evento | text | **PK**. Identificador del evento (`EV-######`) |
| fecha_evento | date | Fecha del evento |
| tipo_evento | text | `cambio_farmaco`, `control_aps`, `examen_alterado`, `hospitalizacion`, `visita_urgencia` |
| subtipo | text | 13 valores posibles |
| severidad | text | `leve` / `moderada` / `grave` |
| detalle | text | Plantilla fija `"<subtipo> (<especialidad>)"`; no es texto libre clínico |

### mediciones

PK compuesta: (`id_paciente`, `fecha_medicion`, `tipo_medicion`), verificada sin duplicados. FK: `id_paciente` -> `pacientes`. Relación `pacientes` 1:0..N `mediciones`.

| Columna | Tipo PostgreSQL | Descripción / valores |
|---------|-----------------|-----------------------|
| id_paciente | text | **PK** (parte) y **FK** -> `pacientes.id_paciente` |
| fecha_medicion | date | **PK** (parte). Fecha de la medición |
| tipo_medicion | text | **PK** (parte). `HbA1c`, `PHQ9`, `escala_dolor_eva`, `glicemia`, `peak_flow`, `presion_diastolica`, `presion_sistolica`, `saturacion_o2` |
| valor | numeric | Valor numérico de la medición |
| unidad | text | `%`, `L/min`, `mg/dL`, `mmHg`, `puntos` |
| fuera_de_rango | boolean | Indica si el valor está fuera de rango |

### box

Dimensión derivada (no viene como CSV). PK: `id_box`.

| Columna | Tipo PostgreSQL | Descripción / valores |
|---------|-----------------|-----------------------|
| id_box | text | **PK**. `BOX-01`..`BOX-20` |

Cada box atiende siempre la misma especialidad en el dataset. Aun así, la especialidad se deja en `agenda_box` (por día), porque en la operación real un box puede cambiar de especialidad.

### agenda_box

PK compuesta: (`id_box`, `fecha`). Hay un solo bloque por box y día (siempre 08:30–13:30), verificado sin duplicados. FK: `id_box` -> `box`. Tabla del hospital: no tiene `id_paciente`.

| Columna | Tipo PostgreSQL | Descripción / valores |
|---------|-----------------|-----------------------|
| id_box | text | **PK** (parte) y **FK** -> `box.id_box` |
| fecha | date | **PK** (parte). Días hábiles, 2026-04-14 a 2026-10-13 |
| especialidad | text | 7 especialidades |
| bloque_inicio | time | Hora de inicio del bloque (08:30) |
| bloque_fin | time | Hora de fin del bloque (13:30) |
| capacidad_cupos | integer | Capacidad de cupos del bloque (8/10/12) |
| cupos_usados | integer | Cupos usados (<= `capacidad_cupos`) |
| minutos_sobretiempo | integer | Minutos de sobretiempo (0-124) |

### citaciones

PK: `id_cita`. FK: `id_paciente` -> `pacientes` y `id_box` -> `box`. Relación `pacientes` 1:0..N `citaciones`.

| Columna | Tipo PostgreSQL | Descripción / valores |
|---------|-----------------|-----------------------|
| id_paciente | text | **FK** -> `pacientes.id_paciente` |
| id_cita | text | **PK**. Identificador de la citación (`CT-######`) |
| id_box | text | **FK** -> `box.id_box` |
| fecha_cita | date | Fecha de la citación (2026-01-31 a 2026-10-10) |
| especialidad | text | 7 especialidades |
| estado_cita | text | `asistio` / `no_asistio` / `reprogramo` / `cancelo` |
| minutos_atencion_real | integer (nullable) | Minutos de atención real (15-55); NULL si no asistió (solo tiene valor cuando `estado_cita` = `asistio`) |

> **No cruzar citas con bloques por fecha.** De 257 citas, 118 no tienen bloque para ese box ese día, 121 caen en un box que ese día atiende otra especialidad y 27 son anteriores al inicio de la agenda. Capacidad (`agenda_box`) y uso (`citaciones`) se analizan por separado, agregados por especialidad y semana.

## Diagrama entidad-relación

```mermaid
erDiagram
    PACIENTES ||--|| LISTA_ESPERA : tiene
    PACIENTES ||--o{ EVENTOS_CLINICOS : registra
    PACIENTES ||--o{ MEDICIONES : registra
    PACIENTES ||--o{ CITACIONES : agenda
    BOX ||--o{ AGENDA_BOX : "bloque diario"
    BOX ||--o{ CITACIONES : usa_box

    PACIENTES {
        text id_paciente PK
        text nombre_fantasia
        integer edad
        text sexo
        text comuna
        text prevision
        text nivel_socioeconomico
        boolean fallecido
        date fecha_defuncion "null si no fallecio"
    }

    LISTA_ESPERA {
        text id_solicitud PK
        text id_paciente FK
        text especialidad
        text sub_especialidad
        text diagnostico_cie10
        text prioridad_inicial
        date fecha_ingreso_lista
        text origen_derivacion
        text estado
    }

    EVENTOS_CLINICOS {
        text id_evento PK
        text id_paciente FK
        date fecha_evento
        text tipo_evento
        text subtipo
        text severidad
        text detalle
    }

    MEDICIONES {
        text id_paciente PK, FK
        date fecha_medicion PK
        text tipo_medicion PK
        numeric valor
        text unidad
        boolean fuera_de_rango
    }

    BOX {
        text id_box PK
    }

    AGENDA_BOX {
        text id_box PK, FK
        date fecha PK
        text especialidad
        time bloque_inicio
        time bloque_fin
        integer capacidad_cupos
        integer cupos_usados
        integer minutos_sobretiempo
    }

    CITACIONES {
        text id_cita PK
        text id_paciente FK
        text id_box FK
        date fecha_cita
        text especialidad
        text estado_cita
        integer minutos_atencion_real "null si no asistio"
    }
```

## Mapeo CSV -> tabla

Cada tabla del esquema `raw` se carga desde su archivo CSV correspondiente. Al cargar, hay que cuidar las conversiones de tipo desde el texto plano del CSV hacia los tipos de PostgreSQL.

| Tabla raw | Archivo CSV | Conversiones de tipo a cuidar al cargar |
|-----------|-------------|------------------------------------------|
| pacientes | `pacientes.csv` | `edad` texto -> integer; `fallecido` `'true'`/`'false'` -> boolean; `fecha_defuncion` texto `AAAA-MM-DD` -> date, vacío -> NULL cuando no falleció |
| lista_espera | `lista_espera.csv` | `fecha_ingreso_lista` texto `AAAA-MM-DD` -> date |
| eventos_clinicos | `eventos_clinicos.csv` | `fecha_evento` texto `AAAA-MM-DD` -> date |
| mediciones | `mediciones.csv` | `fecha_medicion` texto `AAAA-MM-DD` -> date; `valor` texto -> numeric; `fuera_de_rango` `'true'`/`'false'` -> boolean |
| box | derivada de `agenda_box.csv` | `SELECT DISTINCT id_box`; se carga **antes** que `agenda_box` y `citaciones` |
| agenda_box | `agenda_box.csv` | `fecha` texto `AAAA-MM-DD` -> date; `bloque_inicio`/`bloque_fin` texto `HH:MM` -> time; `capacidad_cupos`/`cupos_usados`/`minutos_sobretiempo` texto -> integer |
| citaciones | `citaciones.csv` | `fecha_cita` texto `AAAA-MM-DD` -> date; `minutos_atencion_real` texto -> integer, vacío -> NULL cuando no asistió (solo con valor si `estado_cita` = `asistio`) |

Puntos transversales de conversión:

- Fechas: todo campo de fecha llega como texto `AAAA-MM-DD` y debe convertirse a `date`.
- Booleanos: `fallecido` y `fuera_de_rango` llegan como `'true'`/`'false'` y deben convertirse a `boolean`.
- Vacíos -> NULL: `fecha_defuncion` cuando el paciente no falleció y `minutos_atencion_real` cuando el paciente no asistió deben quedar como NULL, no como cadena vacía.
- Orden de carga (por las llaves foráneas): `pacientes` → `lista_espera`, `eventos_clinicos`, `mediciones` → `box` → `agenda_box`, `citaciones`.

## Script de carga: módulo `db/`

La carga está automatizada para que, si la base o la instancia se borran (por ejemplo, al limpiar la cuenta al final de cada día del hackatón), se pueda reconstruir todo en minutos con uno o dos comandos.

### Organización

```
db/
├── __init__.py
├── __main__.py              # línea de comandos: python -m db <comando>
├── conexion.py              # conexión: HLF_DATABASE_URL, Secrets Manager o variables PG*; SSL fuera de localhost
├── esquema.py               # aplica los scripts SQL en orden
├── carga.py                 # lee y convierte los CSV, y los carga con COPY en una transacción
├── verificacion.py          # conteos, huérfanos y propiedades conocidas del dataset
├── sql/
│   └── raw/
│       ├── 001_esquema_raw.sql   # DDL idempotente: 7 tablas, PK, FK, CHECK, índices, bitácora carga_lote
│       └── 900_permisos.sql      # rol de solo lectura hlf_lectura_raw (se aplica aparte)
└── infra/
    └── crear_rds.sh         # crea la instancia RDS con AWS CLI si no existe
tests/test_db.py             # conversión de CSV y, con base de prueba, carga real y rollback
```

Cuando se agregue el esquema `priorizacion`, su DDL va en `db/sql/priorizacion/` y se aplica con el mismo mecanismo.

### Recuperación rápida (si se borró todo)

```bash
pip install -r requirements.txt boto3

# 1. Solo si la instancia RDS ya no existe (5 a 10 minutos). Al final imprime las variables a exportar.
bash db/infra/crear_rds.sh

# 2. Exportar las variables que imprimió el paso 1 (o definir HLF_DATABASE_URL directamente)
export AWS_REGION=…  HLF_DB_HOST=…  HLF_DB_NAME=hlf  HLF_DB_SECRET_ID=…

# 3. Crear el esquema, cargar los CSV y verificar (menos de 1 segundo de carga)
python -m db restaurar
```

Si la instancia sigue viva y solo se borraron los datos, basta con el paso 3.

### Comandos

| Comando | Qué hace |
|---|---|
| `python -m db probar` | Prueba la conexión y muestra versión, base y usuario |
| `python -m db esquema` | Crea el esquema `raw` si no existe (idempotente) |
| `python -m db cargar` | Carga los CSV. Si `raw` ya tiene datos se detiene; con `--reemplazar` los vacía y recarga |
| `python -m db restaurar` | Esquema + carga reemplazando + verificación, todo de una vez. **Es el comando para el día a día** |
| `python -m db verificar` | Conteos contra la última carga, huérfanos, eventos posteriores a la defunción e indicadores informativos |
| `python -m db permisos` | Crea el rol `hlf_lectura_raw` (solo SELECT sobre `raw`). Requiere CREATEROLE |
| `python -m db borrar --confirmar` | Elimina el esquema `raw` completo |

Opciones: `--url` para indicar la conexión en el comando y `--datos <carpeta>` para cargar desde otra carpeta de CSV (por defecto `HLF_DATA_DIR`).

### Conexión y credenciales

En orden de prioridad:

1. `HLF_DATABASE_URL`, por ejemplo `postgresql://usuario:clave@host:5432/hlf`.
2. `HLF_DB_SECRET_ID` + `HLF_DB_HOST`: el secreto de Secrets Manager que crea RDS con `--manage-master-user-password` (requiere `boto3` y credenciales AWS). Opcionales: `HLF_DB_PORT`, `HLF_DB_NAME`.
3. Variables estándar de PostgreSQL: `PGHOST`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`.

Fuera de `localhost` la conexión exige SSL. Las claves nunca se imprimen ni se guardan en el repositorio.

### Garantías de la carga

- **Atómica:** todo ocurre en una transacción. Si un archivo falta, un valor no se puede convertir o se viola una restricción, la base queda exactamente como estaba.
- **Repetible:** `restaurar` se puede correr cuantas veces haga falta y siempre deja el mismo resultado.
- **Validada por la base:** además de PK y FK, el DDL incluye `CHECK` sobre los valores permitidos (sexo, prioridad, severidad, estado, tipos de evento y medición), la coherencia `fallecido` ↔ `fecha_defuncion`, `cupos_usados ≤ capacidad_cupos` y `minutos_atencion_real` solo cuando `estado_cita = 'asistio'`. Todas pasan con el dataset actual.
- **Trazable:** cada carga queda en `raw.carga_lote` con la fecha, la carpeta de origen, las filas por tabla y el sha256 de cada CSV.
- **No borra datos ajenos:** `--reemplazar` vacía las tablas sin `CASCADE`. Si otro esquema (por ejemplo `priorizacion`) referencia `raw`, la carga falla en vez de borrar esos datos en cascada.

### Probado

Contra PostgreSQL 18 local:
- **Carga:** 6.738 filas en 0,3 s.
- **Repetición:** la segunda carga sin `--reemplazar` se rechaza; `restaurar` repetido termina sin fallas.
- **Rollback:** con un CSV corrupto la transacción revierte todo.
- **Permisos:** el rol de solo lectura puede consultar pero no insertar.

`db/infra/crear_rds.sh` solo se revisó en sintaxis: no se ha ejecutado contra AWS.

## Flujo de la feature

```mermaid
flowchart LR
    A[CSV local] --> B["python -m db restaurar<br/>esquema + COPY + verificación"]
    A -. opcional .-> S[(S3 raw/<br/>versionado)]
    I["db/infra/crear_rds.sh<br/>si no existe la instancia"] -.-> C
    B --> C[(RDS PostgreSQL<br/>esquema raw, solo lectura)]
    C --> D[Motor priorizacion<br/>consulta vía SQL]
    D --> R[(esquema priorizacion<br/>lectura y escritura)]
```

La integración tocará principalmente tres puntos del código:

- `priorizacion/datos.py`: hoy `Repositorio.desde_csv()` lee los CSV con pandas; se agrega un origen PostgreSQL (consultas SQL contra el esquema `raw`). El resto del motor no cambia, porque trabaja sobre los mismos DataFrames.
- `priorizacion/registro.py`: el backend del registro (hoy SQLite) migra a PostgreSQL, esquema `priorizacion`.
- `priorizacion/config.py`: ya usa las variables de entorno `HLF_DATA_DIR` y `HLF_DB_PATH`. Se agrega una variable de conexión (por ejemplo `HLF_DATABASE_URL`) para conmutar entre local (CSV + SQLite) y AWS sin tocar la lógica del motor. **El modo local se mantiene como respaldo para la demo**, por si falla la red o AWS.

## Esquema priorizacion (siguiente paso)

Las tablas que hoy crea `priorizacion/registro.py` en SQLite pasan a este esquema, con llaves foráneas hacia `raw`:

| Tabla | Filas hoy | Llaves | Notas |
|-------|-----------|--------|-------|
| serie_nocturna | 147.563 | PK (`id_solicitud`, `fecha`), FK `id_solicitud` -> `raw.lista_espera` | Una fila por solicitud activa y noche. A escala HLF (~26 mil solicitudes) crece ~9,5 millones de filas al año: particionar por `fecha` |
| propuesta_prioridad | 517 | PK `id_propuesta`, FK `id_solicitud` | Nunca modifica `raw.lista_espera.prioridad_inicial` |
| factor_propuesta | 3.841 | FK `id_propuesta` | `ref_fuente` apunta a filas de `raw` (`EV-…`, `CT-…`, mediciones por clave compuesta) |
| decision_clinica | según uso | PK `id_decision`, FK `id_propuesta`, `id_solicitud` | Registro de auditoría: solo inserciones |
| evidencia_externa, mensaje_paciente | según uso | FK `id_paciente` -> `raw.pacientes` | Canal del paciente |
| corrida_nocturna | 1 por corrida | PK `id_corrida` | Bitácora del proceso nocturno |

Permisos: el rol de la aplicación tiene **solo lectura** sobre `raw` y lectura y escritura sobre `priorizacion`. Así la base misma garantiza que el sistema nunca modifica las fuentes.

## Consideraciones AWS

- La base vive dentro de una VPC. Hay que configurar el security group para permitir el acceso controlado desde tu máquina (solo tu IP, durante la carga y el desarrollo) y desde la API.
- Las credenciales se gestionan con AWS Secrets Manager; no se hardcodean en el código ni en el repositorio.
- Cifrado en reposo habilitado (KMS) y conexiones con SSL.
- Los CSV son inmutables: el esquema `raw` se puebla con `python -m db restaurar` y luego queda de solo lectura. Si la base se pierde, se repite el mismo comando.
- `crear_rds.sh` deja la instancia con acceso público **solo desde tu IP** (security group). Es aceptable para el dataset sintético; con datos reales la base debe ser privada y accederse desde la VPC.
- Para no pagar mientras no se usa: `aws rds stop-db-instance --db-instance-identifier hlf-priorizacion` (se reinicia sola a los 7 días).
- Región: la de la cuenta del hackatón. Para datos reales del HLF (no este dataset sintético), acordar con el hospital la región y la residencia de los datos antes de subir nada.

## Decisión de servicio

**Decisión: RDS for PostgreSQL clásico.**

| Opción | Evaluación |
|--------|------------|
| **RDS for PostgreSQL** (elegida) | Instancia fija y estándar. Costo bajo y predecible (del orden de US$ 12–15 al mes para `db.t4g.micro` más almacenamiento, precios aproximados de us-east-1). Sin arranque en frío: responde siempre igual durante la demo. Configuración simple |
| Aurora Serverless v2 | Compatible con PostgreSQL y escala con el uso. Para ser barato debe escalar a cero, y entonces la primera conexión tras una pausa tarda varios segundos: es un riesgo en plena demo. Con un mínimo de 0,5 ACU para evitarlo cuesta más que RDS (del orden de US$ 40 al mes). Sus ventajas (escalado, failover rápido, réplicas) no pesan con este volumen |
| Aurora DSQL | Descartada: no aplica llaves foráneas, y el modelo depende de ellas |
| S3 + Athena | Bueno para los archivos crudos a gran escala, pero el esquema `priorizacion` necesita escrituras transaccionales (decisiones, validaciones) |
| DynamoDB | Sin joins ni llaves foráneas; el modelo es relacional |

Motivos: el volumen es mínimo (~6.700 filas en `raw`, ~150 mil en `priorizacion`), el uso es intermitente pero la demo no tolera latencia de arranque, y el tiempo para configurar es corto. Si el piloto con el HLF necesita alta disponibilidad, un snapshot de RDS se migra a Aurora PostgreSQL sin cambiar el SQL.

Verificar los precios para la región elegida en la calculadora de AWS.

## Pendientes / decisiones abiertas

- ~~Estrategia de carga~~: **resuelta** con el módulo `db/` (script en Python con COPY). La importación desde S3 con la extensión `aws_s3` queda como alternativa si en el futuro los archivos viven solo en S3.
- **Detalle del esquema `priorizacion`**: definir el DDL en `db/sql/priorizacion/` y la migración de `registro.py` a PostgreSQL.
- **Lectura desde PostgreSQL en el motor**: agregar a `priorizacion/datos.py` un origen SQL (`Repositorio.desde_postgres()`), manteniendo el modo CSV como respaldo para la demo.
- **Probar `db/infra/crear_rds.sh` en la cuenta del hackatón**, que puede tener restricciones de servicios o regiones.
- **Convención CIE-10**: los códigos del dataset tienen 3 caracteres; la convención del proyecto (`E11.3`, con punto) aplica cuando lleguen códigos con subcategoría.
