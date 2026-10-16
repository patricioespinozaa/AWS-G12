# F0014 · Configuración de las reglas, versionada

**Estado:** Implementado · **Depende de:** F0005, F0006, F0007 · **Tamaño:** M

## Objetivo

Una vista **Reglas** donde la Administradora ve todas las reglas del puntaje con sus parámetros, los cambia, simula el efecto antes de guardar y guarda cada cambio como una **versión nueva** con motivo, autora y fecha. Toda propuesta queda atada a la versión con que se calculó, y se puede volver a una versión anterior.

## Qué existe hoy

- **Reglas en código:** `priorizacion/reglas.py` tiene todos los pesos, umbrales, ventanas y rangos como constantes. Cambiarlos exige un despliegue y subir `VERSION_REGLAS` a mano.
- **Trazabilidad por versión:** cada fila de la serie, cada propuesta y cada corrida guarda `version_reglas` (`motor.py`, `nocturno.py`, `registro*.py`).
- **Vista de solo lectura:** la vista Nocturno lista las reglas vigentes (`R.tabla_reglas()` en `/api/nocturno`).
- **Recálculo completo:** `consolidar(..., desde_cero=True)` rehace la historia "tras cambiar las reglas" (`priorizacion/consolidacion.py`), y la API lo lanza en segundo plano (`E.consolidar_en_segundo_plano`).
- **Sincronización:** toda escritura sube `priorizacion.estado_app.version`, y cada tarea del backend refresca lo suyo al verlo (`E.sincronizar`).

## Alcance

**Entra:**
- Catálogo de parámetros editables, con grupo, nombre en español, descripción, unidad, mínimo y máximo.
- Validación de cada valor y entre valores (por ejemplo, umbral de media < umbral de alta).
- Tabla `priorizacion.version_reglas` (solo inserción) en RDS y SQLite.
- Vista **Reglas** con los parámetros agrupados, la diferencia contra la versión vigente, una simulación (cuántos pacientes cambian de nivel y cuáles) y el historial de versiones, con la opción de restaurar una versión.
- Recálculo completo al guardar, y la versión en el texto de `VERSION_REGLAS` de cada resultado.

**No entra:**
- Crear reglas nuevas o cambiar su forma (la fórmula sigue en código).
- Editar los nombres visibles, las unidades, el canal de origen o el requisito de examen por especialidad: se listan como información, sin edición.
- Aprobación por una segunda persona: hay un solo rol (F0007).

## Diseño

| Pieza | Qué | Por qué |
|---|---|---|
| **Catálogo** | `priorizacion/parametros.py`: un `Parametro` por valor editable (clave estable como `evento.hospitalizacion.ingreso_uci` o `nivel.umbral_alta`), que apunta a una constante o a una entrada de un diccionario de `reglas.py` | `reglas.py` sigue siendo la fuente de los valores por defecto y la fórmula no cambia. El catálogo solo agrega metadatos y límites |
| **Valores por defecto** | Se toma una foto de `reglas.py` al importar el módulo (versión 0) | Siempre se puede volver al valor de fábrica |
| **Aplicar** | `parametros.aplicar(valores, numero)` reemplaza los atributos de `reglas` (diccionarios nuevos, nunca mutados) y deja `VERSION_REGLAS = "reglas-v0.1+c<n>"` | Todo el motor lee `R.X` al calcular, así el cambio llega sin tocar el resto. Los pocos `from .reglas import X` pasan a `R.X` |
| **Edad** | `puntos_edad` usa dos umbrales y dos puntajes nuevos (`EDAD_*`) en vez de números fijos | Era la única regla con valores escritos dentro del código |
| **Versiones** | `version_reglas(numero, version, valores, cambios, motivo, autora, creada_en)`, solo inserción. La vigente es la de número mayor. Restaurar crea una versión nueva con los valores de una anterior | Nada se borra: queda quién cambió qué, cuándo y por qué. `cambios` guarda el valor anterior y el nuevo de cada clave |
| **Guardar** | `POST /api/reglas/versiones` valida, inserta, aplica y lanza el recálculo completo en segundo plano. Responde 409 si ya hay un recálculo corriendo | La serie, las propuestas y la estimación quedan calculadas con la versión nueva. Las decisiones de la Administradora no se tocan |
| **Varias tareas** | Al ver otra versión de la app, `sincronizar` lee la versión vigente y la aplica si cambió. La corrida nocturna la aplica al arrancar | Las dos tareas de ECS y la noche calculan siempre con la misma versión |
| **Simulación** | `POST /api/reglas/simulacion` calcula la bandeja de la fecha de corte con los valores propuestos, sin guardar. Devuelve cuántos suben y bajan de nivel, y los 20 con más cambio en el puntaje | La herramienta propone y explica: la Administradora ve el efecto antes de decidir |
| **Aislamiento** | Un candado de lectura y escritura (`parametros.lectura()` y `parametros.escritura()`): las peticiones y la consolidación toman el de lectura; simular y aplicar toman el de escritura | Los valores son globales del proceso: una simulación no debe mezclarse con una petición en curso. Hay una sola usuaria, así que la espera es breve |

## Cambios por carpeta

```
priorizacion/parametros.py          catálogo, validación, aplicar, simular, candado
priorizacion/reglas.py              umbrales de edad como constantes
priorizacion/{explicacion,estimacion,datos}.py   leer R.X al calcular
priorizacion/motor.py               version_reglas por defecto al crear el resultado, no al importar
priorizacion/registro.py            tabla y métodos en SQLite (versiones_reglas, guardar_version_reglas)
priorizacion/registro_postgres.py   lo mismo en PostgreSQL
db/sql/priorizacion/006_version_reglas.sql   tabla de solo inserción
api/rutas/reglas.py                 catálogo, versiones, simulación y guardar
api/estado.py                       aplicar la versión vigente al iniciar y al sincronizar
servicios/nocturno/                 aplicar la versión vigente antes de consolidar
web/src/paginas/Reglas.tsx          la vista
tests/test_parametros.py            catálogo, validación, aplicar, versiones, simulación y API
```

## Tareas

1. Catálogo y valores por defecto, con la prueba de que los valores de fábrica dan exactamente el mismo resultado que hoy.
2. Leer `R.X` en todo el motor, y la edad parametrizada.
3. Tabla y registro (SQLite y PostgreSQL, con las mismas columnas).
4. Rutas: catálogo, versiones, simulación, guardar y restaurar.
5. Sincronización entre tareas y en la corrida nocturna.
6. Vista Reglas.
7. Documentación (`docs/mvp.md`, `CLAUDE.md`).

## Criterios de aceptación

- La vista lista todas las reglas. Los valores editables muestran su valor vigente, el de fábrica, la unidad y los límites. Lo no editable se muestra sin control de edición.
- Guardar exige un motivo y un cambio real. Un valor fuera de límites, o una combinación inválida, se rechaza con un mensaje que nombra el parámetro.
- Después de guardar, las propuestas nuevas llevan `reglas-v0.1+c<n>` y la bandeja refleja los valores nuevos.
- El historial muestra cada versión con autora, fecha, motivo y cambios (anterior → nuevo), y restaurar una versión crea una versión nueva.
- La simulación no guarda nada: después de simular, la versión vigente y la bandeja son las mismas.
- Con los valores de fábrica, el resultado es idéntico al de hoy.

## Pruebas

- **Automáticas:**
  - catálogo completo (cada clave apunta a un valor de `reglas.py`);
  - límites y validaciones cruzadas;
  - aplicar y volver a fábrica dan el mismo resultado que hoy;
  - un cambio de peso mueve el puntaje como se espera;
  - versiones de solo inserción en SQLite y PostgreSQL con las mismas columnas;
  - la simulación no persiste;
  - la API: autora desde la sesión, 422 con motivo vacío, 409 durante un recálculo.
- **Manual:** cambiar el peso de "Hospitalización · ingreso UCI" y ver la simulación, guardar, ver el recálculo terminar y el caso de don Manuel con la versión nueva, y restaurar la versión de fábrica.

## Riesgos y decisiones abiertas

- **Recalcular la historia con reglas nuevas** cambia cómo se ve el pasado simulado. Cada fila guarda su versión, y las decisiones de la Administradora no cambian. Queda por decidir con el HLF si conviene recalcular solo desde la fecha del cambio.
- **Cambios clínicos sin revisión:** los valores son una propuesta para calibrar con el equipo clínico. La vista muestra el valor de fábrica y el motivo es obligatorio. Con datos reales podría exigirse una segunda aprobación.
- **Tiempo del recálculo** en Fargate: unos minutos, con el mismo aviso que una carga.

## Resultado

Implementado y probado en local (SQLite y PostgreSQL); pendiente de desplegar (`cdk deploy HlfDemo-Backend HlfDemo-Frontend`, que aplica la migración `006` al arrancar).

| Pieza | Implementación |
|---|---|
| Catálogo | `priorizacion/parametros.py`: 89 parámetros editables en 7 grupos (niveles, eventos clínicos, riesgo basal, edad y espera, mediciones, patrones, gestión del box), cada uno con nombre, descripción, unidad y límites. Los nombres, unidades, el canal de origen y el examen requerido por especialidad se listan sin edición |
| Validación | Tipo, límites y reglas entre parámetros (umbral de media < alta, tramo de edad intermedio < mayor, mínimo normal < máximo). El error nombra cada parámetro |
| Aplicar | Reemplaza los atributos de `reglas.py` con diccionarios nuevos (la foto de fábrica no se toca) y deja `VERSION_REGLAS = "reglas-v0.1+c<n>"`. El motor lee `R.X` al calcular; `explicacion.py`, `estimacion.py`, `datos.py` y la versión por defecto de `Resultado` dejaron de copiar valores al importar. La edad pasó a cuatro constantes (`EDAD_*`) |
| Versiones | `priorizacion.version_reglas` (migración `006`, solo inserción, autora con llave foránea, motivo obligatorio y al menos un cambio). La vigente es la de número mayor; restaurar crea una versión nueva que apunta a la restaurada (`restaura`). Mismas columnas y tipos en SQLite y PostgreSQL |
| Recálculo | Guardar aplica la versión y recalcula la historia completa en segundo plano (corrida con origen `reglas`). Con un recálculo en curso, simular y guardar responden 409 |
| Varias tareas | `sincronizar` aplica la versión vigente cuando cambia la versión de la app; la API al iniciar, la corrida nocturna y `python -m priorizacion.nocturno` también |
| Simulación | `POST /api/reglas/simulacion`: bandeja de la fecha de corte con los valores propuestos, sin guardar. Cuántos suben y bajan de nivel, conteo por nivel y los 20 con más cambio de puntaje |
| Aislamiento | Candado de lectura y escritura: las rutas que calculan toman el de lectura (dependencia `E.calculando`), y también la consolidación en segundo plano y el precalentado. Simular y aplicar toman el de escritura |
| Vista | **⚙️ Reglas**: parámetros por grupo con buscador, valor vigente, de fábrica y límites; los cambios se marcan y validan en el navegador; motivo obligatorio; simular, guardar o descartar; volver a fábrica por parámetro; historial con autora, fecha, motivo y cambios (anterior → nuevo), y "Volver a esta versión" |

**Pruebas** (`tests/test_parametros.py`): catálogo completo y dentro de sus límites; validación con el parámetro nombrado; aplicar y volver a fábrica sin tocar la foto; pesos mayores suben el puntaje de don Manuel y la fábrica da el mismo puntaje de hoy; la simulación vuelve a la vigente aunque falle; una simulación espera a un cálculo en curso; versiones en SQLite y en PostgreSQL con las mismas columnas, solo inserción, llave foránea de la autora y la corrida con origen `reglas`; API completa (catálogo, simulación que no guarda, 422 sin motivo, fuera de límites o sin cambios, guardar con recálculo, 409 durante un recálculo, restaurar a fábrica y versión inexistente).
