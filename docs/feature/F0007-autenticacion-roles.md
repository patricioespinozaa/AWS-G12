# F0007 · Autenticación de la Administradora

**Estado:** Implementado y desplegado en `demo` · **Depende de:** F0004, F0005 · **Tamaño:** S

## Objetivo

Que solo la Administradora del HLF entre a la app, y que cada carga, decisión y validación quede asociada a la persona autenticada. Es obligatoria antes de usar datos reales.

El HLF definió **un solo rol**: la Administradora. No hay vistas ni permisos para médicos u otro personal: no revisan esta plataforma.

## Qué hace la Administradora

Tiene acceso a **todas las vistas** y es quien:

| Tarea | Vista | Rutas |
|---|---|---|
| Sube los datos de cada periodo (vista previa, confirmar o descartar) | Cargas | `POST /api/cargas`, `/confirmar`, `/descartar` |
| Revisa la cola priorizada y la ficha de cada paciente | Bandeja, Ficha, Agenda, KPIs | `GET /api/*` |
| Aprueba, ajusta o rechaza la prioridad propuesta, con motivo | Ficha | `POST /api/solicitudes/{id}/decisiones` |
| Edita el puntaje de orden de una solicitud (su lugar dentro de la cola de su nivel), con motivo | Ficha | `POST /api/solicitudes/{id}/decisiones` con `puntaje` |
| Valida o descarta la evidencia y las alarmas del canal del paciente | Canal | `POST /api/canal/*/revision` |
| Recalcula la historia completa (tras cambiar las reglas) | Consolidación nocturna | `POST /api/nocturno/ejecutar` |

El principio rector no cambia: sus ajustes se guardan como **decisión**, con motivo, fecha y versión de las reglas. La propuesta del motor nunca se sobrescribe.

### Edición del puntaje

El motor calcula dos puntajes: el **de nivel** (decide alta, media o baja) y el **de orden** (ordena la cola dentro del nivel; suma el contexto, como el riesgo basal). La Administradora puede editar el **de orden**. El nivel lo sigue decidiendo al aceptar, ajustar o rechazar.

| Regla | Por qué |
|---|---|
| La decisión guarda el puntaje que calculó el motor ese día (`puntaje_calculado`) y el **ajuste** (lo que fijó la Administradora menos lo del motor) | El cálculo del motor queda intacto y auditable |
| Desde la fecha de la decisión, **puntaje vigente = puntaje del motor de cada noche + ajuste**, hasta otra decisión que lo cambie. Una decisión sin puntaje mantiene el ajuste anterior; volver al del motor deja el ajuste en 0 | Los eventos clínicos nuevos siguen moviendo al paciente: un ajuste fijo lo congelaría |
| El puntaje vigente ordena la bandeja, la posición de la serie y la estimación de espera **dentro del nivel**. No cambia el nivel propuesto ni el puntaje de nivel | Cambiar de nivel es otra decisión, explícita |
| Editar el puntaje exige motivo. El ajuste está acotado a ±100 puntos (validado en la API y en la base) | Trazabilidad y prevención de errores de tipeo |
| La serie nocturna guarda el ajuste de cada noche (`ajuste_puntaje`) | La evolución muestra cuándo y cuánto se ajustó |

## Punto de partida (antes de F0007)

- La app no tiene autenticación: cualquiera que llegue a la URL de CloudFront entra.
- Desde F0005 la API ya **no recibe el autor en el cuerpo**: toda escritura se registra a nombre de `config.USUARIA` (`HLF_USUARIA`, por defecto `administradora`).
- RDS ya tiene el rol: `priorizacion.usuario` acepta `rol = 'administracion'` (migración `priorizacion/002_usuaria_unica.sql`). Todas las columnas `*_por` e `id_usuario` son FK a esa tabla.
- La consolidación nocturna (F0006) escribe como `consolidacion_nocturna` (`cargado_por`): es un proceso, no una persona, y no pasa por la API.
- El health check del ALB usa `GET /api/meta`, que devuelve datos (especialidades, casos de referencia).

## Alcance

**Entra:** Cognito User Pool con un grupo `administracion`, login en el frontend, validación del token en la API, que toda ruta `/api/*` exija ese grupo, sincronización de la persona en `priorizacion.usuario` y la persona autenticada como autor de toda escritura (reemplaza a `config.USUARIA`).

**No entra:** otros roles ni una matriz de permisos; el reemplazo de la Administradora (vacaciones, licencia); federación con el directorio del HLF (SAML u OIDC), que queda como opción documentada para un piloto.

## Diseño

| Pieza | Elección |
|---|---|
| Identidad | **Amazon Cognito User Pool** sin registro abierto: las cuentas las crea quien administra AWS. Una cuenta **por persona**, nunca una cuenta compartida: así cada decisión tiene autora. MFA opcional en la demo y obligatorio con datos reales |
| Rol | Un grupo de Cognito, `administracion`, igual a `priorizacion.usuario.rol`. Un usuario autenticado que no está en el grupo recibe 403 |
| Login | Hosted UI de Cognito con *authorization code* + PKCE (cliente público, sin secreto). El frontend guarda los tokens en memoria (no en `localStorage`) y renueva el ID token con el refresh token 5 minutos antes de que venza. Al recargar la página vuelve a pasar por Cognito, que recuerda la sesión y no pide la clave. Sesión de una jornada: refresh token de 12 h |
| Validación en la API | La API recibe el **ID token** (trae el nombre de la persona, que queda como autora) y verifica la firma RS256 con las claves públicas (JWKS, en caché), el emisor, la audiencia (`client_id`), la expiración y `token_use = id`. Un access token se rechaza. La dependencia `administradora()` se aplica a todos los routers, antes de tocar la base |
| Configuración | El app client se crea en FrontendStack (su URL de retorno es la de CloudFront, que existe después del backend). Su configuración queda en el parámetro de SSM `/hlf/<entorno>/cognito`, que la API lee en tiempo de ejecución (`HLF_COGNITO_PARAMETRO`). Así no hay dependencia circular entre stacks. Sin el parámetro, la API responde 503: **falla cerrada** |
| CloudFront | `/api/*` usa una política de caché propia: TTL 0, pero que nombra `Authorization`. Con la política administrada `CachingDisabled`, CloudFront no reenvía esa cabecera en los GET. Además, la API responde `Cache-Control: no-store` |
| Autoría | `id_usuario` = `sub` de Cognito. En la primera petición válida se crea su fila en `priorizacion.usuario` (rol `administracion`), y el nombre se actualiza si cambia. Una cuenta desactivada en la base (`python -m db usuarios --desactivar`) se rechaza aunque el token sea válido, en menos de 30 s (caché corta) |
| Rutas públicas | `GET /api/salud` (health check del ALB y del contenedor) y `GET /api/auth/config` (dominio del Hosted UI y `client_id`, que el frontend necesita antes del login). Ninguna devuelve datos de pacientes |
| Desarrollo local | Sin variables de Cognito la autenticación queda desactivada: todo se escribe como `config.USUARIA` y la barra lateral lo avisa. La API **se niega a arrancar** así si usa la RDS de AWS (`HLF_DB_SECRET_ID`): en AWS siempre hay login. Con un PostgreSQL local (`HLF_DATABASE_URL`) sí se permite, para desarrollo y pruebas |
| Cuentas | `bash infra/scripts/crear_cuenta.sh <usuario> "<Nombre>" [correo]` crea la cuenta y la agrega al grupo, con una clave temporal que Cognito pide cambiar en el primer ingreso. MFA (TOTP) opcional en `demo`; `mfa_obligatorio` en `infra/config/entornos.py` lo exige |

## Cambios por carpeta

```
infra/stacks/identidad.py        User Pool (sin registro abierto), grupo administracion, dominio del Hosted UI
infra/stacks/frontend.py         app client (PKCE, retorno = CloudFront), parámetro SSM, política de caché de /api/*
infra/stacks/backend.py          HLF_COGNITO_PARAMETRO y permiso de lectura; health check del ALB en /api/salud
infra/scripts/crear_cuenta.sh    crea una cuenta de Administradora con clave temporal
api/seguridad.py                 configuración, verificación del JWT (JWKS en caché), administradora() → Persona
api/rutas/publico.py             /api/salud y /api/auth/config, sin sesión
api/main.py                      la sesión en todos los routers; Cache-Control: no-store en /api
api/rutas/*.py                   cargas, decisiones y revisiones con el id_usuario autenticado
priorizacion/registro*.py        sincronizar_usuario, usuarios y activar_usuario, en SQLite y PostgreSQL
db/__main__.py                   python -m db usuarios [--desactivar ID | --activar ID]
web/src/auth/                    sesion.ts (PKCE, tokens en memoria, renovación) y ProveedorSesion.tsx
web/src/api.ts                   Authorization: Bearer en cada fetch; 401 → login; descargas con la sesión
web/src/App.tsx                  nombre de la persona y "Cerrar sesión" en la barra lateral
docker/backend/Dockerfile        HEALTHCHECK a /api/salud
db/sql/priorizacion/004_ajuste_puntaje.sql
                                 decision_clinica.puntaje_calculado y ajuste_puntaje; serie_nocturna.ajuste_puntaje
priorizacion/motor.py            Decision.ajuste_puntaje, ajuste_vigente(), Resultado.puntaje_vigente
priorizacion/nocturno.py         la serie guarda el ajuste; la posición dinámica usa el puntaje vigente
priorizacion/estimacion.py       la posición vigente se ordena por nivel vigente y luego puntaje vigente
api/rutas/solicitudes.py         `puntaje` opcional en la decisión (motivo obligatorio si cambia)
web/src/paginas/Ficha.tsx, Bandeja.tsx
                                 campo de puntaje en la decisión, "volver al del motor", ✎ en la bandeja
tests/test_seguridad.py          tokens firmados en la prueba (válido, vencido, otro cliente, sin grupo, desactivada)
tests/test_ajuste_puntaje.py     ajuste vigente, orden dentro del nivel, estimación y API
```

## Tareas

1. Stack de identidad y una cuenta de demo en el grupo `administracion`.
2. `api/seguridad.py` con sus pruebas, con claves generadas en el test (sin llamar a Cognito).
3. Aplicar la dependencia a todos los routers y crear `/api/salud`. Una prueba recorre todas las rutas y falla si alguna responde sin token (salvo `/api/salud`).
4. Reemplazar `config.USUARIA` por la persona del token en cargas, decisiones y revisiones del canal; sincronizar `priorizacion.usuario`.
5. Login en el frontend y token en cada llamada.
6. Modo local sin Cognito, con aviso visible.
7. Documentación: `docs/mvp.md` (quitar la limitación "sin autenticación"), `infra/README.md` (crear cuentas y desactivarlas) y CLAUDE.md.

## Criterios de aceptación

- Sin token, toda ruta `/api/*` responde 401, salvo `/api/salud`, que no devuelve datos.
- Un usuario autenticado que no está en el grupo `administracion` recibe 403 en cualquier ruta, aunque haga la petición sin usar la interfaz.
- Una carga confirmada, una decisión y una validación del canal quedan con el `sub` de quien las hizo (`raw.carga_lote.cargado_por`, `priorizacion.decision_clinica.id_usuario`, `revisado_por`), y su nombre está en `priorizacion.usuario`.
- Una cuenta desactivada no entra, aunque su token no haya vencido.
- El token no queda en `localStorage` ni en cookies accesibles desde JavaScript.
- El despliegue no se corta: el ALB sigue sano con `/api/salud`.

## Riesgos y decisiones abiertas

- **Directorio del HLF:** para un piloto, federar con el proveedor de identidad del hospital en vez de crear cuentas en Cognito.

## Resultado

Implementado, probado en local y desplegado en `demo` el 16-10-2026.

| Criterio | Cómo se comprobó | Resultado |
|---|---|---|
| Sin token, 401 | `tests/test_seguridad.py` recorre todas las rutas de `/api` del esquema OpenAPI; en AWS, `curl` por CloudFront | Todas responden 401 salvo `/api/salud` y `/api/auth/config`, que no devuelven datos |
| Sin el grupo, 403 | Prueba con un token firmado sin el grupo; en AWS, con una cuenta temporal de Cognito | 403 aunque la petición sea válida |
| Autoría | Prueba de la decisión con token; en AWS, `/api/meta` con un token real | La decisión queda con el `sub` de Cognito y la persona aparece en `priorizacion.usuario` con su nombre |
| Cuenta desactivada | Prueba en SQLite y PostgreSQL; en AWS, `python -m db usuarios --desactivar` como tarea ECS | 403 "Tu cuenta está desactivada"; la cuenta no se reactiva sola al volver a entrar |
| Tokens rechazados | Pruebas puras de `verificar_token` | Vencido, de otro cliente, de otro User Pool, access token, firmado con otra clave, sin `sub` y HS256 |
| Token fuera de `localStorage` | Revisión de `web/src/auth/sesion.ts` | Tokens en memoria; en sessionStorage solo el verificador PKCE y el `state` durante la redirección |
| Despliegue sin corte | Despliegue en `demo` | El ALB quedó sano con `/api/salud`; la web sigue en la misma URL |
| En AWS nunca sin login | Prueba de `validar_arranque` y la imagen con `HLF_DB_SECRET_ID` sin Cognito | La API no arranca |

También se verificó en AWS que CloudFront reenvía `Authorization` (un token inválido recibe "sesión no válida", no "inicia sesión"), que el Hosted UI rechaza una URL de retorno ajena (`redirect_mismatch`) y que el canje del código admite CORS desde CloudFront.

**Edición del puntaje** (`tests/test_ajuste_puntaje.py` y paridad en `tests/test_persistencia_rds.py`): al fijar un puntaje, la solicitud sube en su cola sin cambiar de nivel, el puntaje del motor queda intacto, la decisión guarda el puntaje calculado y el ajuste, la serie registra el ajuste, y "volver al del motor" lo deja en 0. Sin motivo o con un ajuste mayor a ±100, la API responde 422. Desplegado en `demo` (migración `004` aplicada al arrancar la API).

Suite: 120 pruebas con PostgreSQL y el dataset; 41 en modo CI (sin dataset ni base); 28 de infraestructura.

**Diferencias con el plan:**
- No existe la variable `HLF_AUTH`: el modo desactivado es simplemente la ausencia de configuración de Cognito, y se bloquea en AWS por `HLF_DB_SECRET_ID`.
- Hay dos rutas públicas en vez de una: el frontend necesita `/api/auth/config` para saber a qué Hosted UI ir.
- La configuración del app client llega a la API por SSM y no por variables de entorno, para evitar la dependencia circular backend → CloudFront → app client.
- Se agregó la edición del puntaje de orden (decidido por el HLF después del plan).
- La estimación de espera ordena ahora cada nivel por puntaje vigente (antes, por orden de llegada), para que la edición del puntaje se refleje también en el tiempo estimado.

