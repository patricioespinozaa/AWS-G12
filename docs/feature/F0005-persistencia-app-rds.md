# F0005 · La app usa RDS en vez de CSV + SQLite

**Estado:** Plan · **Depende de:** F0004 · **Tamaño:** L

## Objetivo

Conectar la app a las tablas que ya existen en RDS (F0002 y F0003): que el motor lea `raw` desde PostgreSQL y que propuestas, decisiones, mensajes y evidencias se guarden en `priorizacion` y `canal`. Con eso las decisiones clínicas sobreviven a un reinicio, quedan auditadas por la base y el backend puede correr en más de una tarea.

## Qué existe hoy

- **Lectura:** `priorizacion/datos.py` → `leer_csv()` arma 6 DataFrames (`pacientes`, `lista`, `eventos`, `mediciones`, `agenda`, `citas`) y `Repositorio` construye las historias en memoria.
- **Escritura:** `priorizacion/registro.py` → clase `Registro` sobre SQLite, con 7 tablas y unos 20 métodos. La API usa sobre todo `decisiones`, `mensajes`, `evidencias`, `guardar_propuesta`, `registrar_decision`, `reemplazar_serie` y `version`.
- **En RDS, sin usar:** `raw` (cargado con `python -m db restaurar`), y `priorizacion` y `canal` con llaves foráneas, `CHECK`, triggers de auditoría y roles (`hlf_app`).
- **Archivos de evidencia:** se guardan en disco local (`config.EVIDENCIA_DIR`).
- `api/main.py` tiene 528 líneas con todas las rutas, y usa un `threading.Lock` y un caché en memoria cuya llave es `registro.version()`.

## Alcance

**Entra:** origen de datos PostgreSQL para el motor, registro en PostgreSQL con la misma interfaz que el de SQLite, archivos de evidencia en S3, separar `api/main.py` en routers y que el backend funcione con varias tareas.

**No entra:** cambios al motor ni a las reglas; autenticación (F0007; mientras tanto, el usuario se registra como hoy y se asocia a `priorizacion.usuario`).

## Diseño

**Dos implementaciones con la misma interfaz**, elegidas por configuración:

| Pieza | Local (se mantiene como respaldo de la demo) | AWS |
|---|---|---|
| Datos fuente | `Repositorio.desde_csv()` | `Repositorio.desde_postgres(conn)`: los mismos 6 DataFrames, leídos de `raw` |
| Registro | `RegistroSQLite` (el actual) | `RegistroPostgres`: esquemas `priorizacion` y `canal` |
| Archivos de evidencia | Disco local | S3 `canal/evidencias/<id_paciente>/<id>.<ext>`, con sha256 en `canal.evidencia_externa` |

Se elige con `HLF_DATABASE_URL` o `HLF_DB_SECRET_ID` (las mismas variables de `db/conexion.py`). Sin ellas, la app funciona como hoy.

**Diferencias que el adaptador debe resolver** (el modelo de F0002 es más estricto que el de SQLite):

| En SQLite | En RDS | Qué hace el adaptador |
|---|---|---|
| `id_evidencia` = `EXT-00001` (COUNT+1) | `bigint identity` | La API devuelve el ID numérico. El frontend lo trata como texto opaco |
| `decision_clinica.usuario` en texto libre | `id_usuario` FK a `priorizacion.usuario` | Hasta F0007, mapear el nombre del formulario a un usuario de demo (o crearlo con rol `medico`) |
| `serie_nocturna` con `especialidad` y `prioridad_inicial` | Se obtienen de `raw.lista_espera` | `serie()` y `serie_resumen()` hacen el join |
| `decision_clinica` admite cualquier combinación | `CHECK decision_coherente` | Validar en la API antes de insertar y devolver 422 con un mensaje claro |
| Borrar propuestas nocturnas con `DELETE` | Permitido solo a `hlf_app` en `serie_nocturna`, `propuesta_prioridad` y `factor_propuesta` | Sin cambios |
| `version()` = conteos de filas | Varias tareas | Una secuencia o un contador en una tabla de estado que suba con cada escritura. Cada tarea refresca su caché y su repositorio en memoria cuando cambia |

**Varias tareas:** el repositorio en memoria es de solo lectura (sale de `raw`). Lo que cambia con el uso (evidencias validadas y mensajes) se vuelve a aplicar cuando la versión del registro sube. El `threading.Lock` deja de proteger el estado compartido: las transacciones de PostgreSQL lo reemplazan.

**Routers:** `api/main.py` se separa en `api/rutas/{meta,bandeja,solicitudes,agenda,canal,kpis,nocturno}.py`, más `api/dependencias.py` (repositorio, registro y caché) y `api/serializacion.py` (`a_json`). El comportamiento no cambia; las pruebas de `tests/test_api.py` lo garantizan.

## Cambios por carpeta

```
priorizacion/datos.py              Repositorio.desde_postgres(conn) (consultas a raw → mismos DataFrames)
priorizacion/registro.py           Protocolo Registro + RegistroSQLite (código actual) + fábrica según config
priorizacion/registro_postgres.py  RegistroPostgres (priorizacion + canal)
priorizacion/archivos.py           Almacenamiento de evidencias: disco local o S3
priorizacion/config.py             HLF_DATABASE_URL / HLF_DB_SECRET_ID, HLF_S3_BUCKET para evidencias
api/main.py                        Solo crea la app e incluye los routers
api/rutas/*.py, api/dependencias.py, api/serializacion.py
infra/stacks/backend.py            desired_count configurable (2 en demo), despliegue sin corte (min 100 %)
tests/test_registro_postgres.py    La misma batería de pruebas para las dos implementaciones (parametrizada)
```

## Tareas

1. Definir el protocolo `Registro` a partir de los métodos que usan la API y el motor (la tabla de "Qué existe hoy").
2. Mover el código actual a `RegistroSQLite` sin cambiar su comportamiento. Toda la suite debe seguir pasando.
3. Escribir pruebas del protocolo parametrizadas por implementación (SQLite siempre, PostgreSQL si hay `HLF_TEST_DATABASE_URL`).
4. Implementar `RegistroPostgres` hasta que pase la misma batería.
5. `Repositorio.desde_postgres()`, con una prueba de que produce los mismos DataFrames que `desde_csv()` (mismos conteos y tipos).
6. Evidencias en S3 detrás de `priorizacion/archivos.py`.
7. Separar `api/main.py` en routers. `tests/test_api.py` sin cambios debe pasar.
8. Contador de versión compartido y refresco del caché por tarea.
9. Infraestructura: variables de RDS en la tarea, permiso de lectura del secreto, regla de SG backend → RDS, dos tareas y despliegue sin corte.
10. Migración de la demo: correr el proceso nocturno contra RDS (o importar la serie desde SQLite) y verificar que la bandeja muestra lo mismo que en local.

## Criterios de aceptación

- Con `HLF_DATABASE_URL` definido, la app no lee CSV ni escribe SQLite. Sin la variable, funciona igual que hoy.
- Una decisión registrada desde la bandeja aparece en `priorizacion.decision_clinica` con su `id_usuario`, y sigue ahí después de reiniciar el servicio.
- Con dos tareas detrás del ALB, una decisión hecha en una se refleja en la otra en la siguiente petición.
- La bandeja al 2026-10-13 tiene las mismas posiciones y niveles en modo CSV + SQLite que en modo RDS.
- `python -m db verificar` sigue en verde con datos de uso real en la base.

## Pruebas

- Batería del protocolo `Registro` sobre ambas implementaciones.
- `tests/test_api.py` contra las dos configuraciones.
- Prueba de concurrencia: dos procesos registran decisiones a la vez y no se pierde ninguna.

## Riesgos y decisiones abiertas

- **Rendimiento del cálculo nocturno completo contra RDS:** la serie tiene unas 150 mil filas. Escribir con `COPY` (como `db/carga.py`), no fila por fila.
- **Usuarios antes de F0007:** decidir si se crea un usuario por nombre escrito o se usa un único usuario de demo.
- **IDs de evidencia y mensaje:** pasan de texto a número. Revisar que el frontend no asuma el prefijo `EXT-` ni `MSG-`.
