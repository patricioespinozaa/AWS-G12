# F0007 · Autenticación y roles del equipo clínico

**Estado:** Plan · **Depende de:** F0004 (y F0005 para asociar usuarios a las decisiones) · **Tamaño:** M

## Objetivo

Que solo personas autorizadas del HLF entren a la app, y que cada decisión, validación o pregunta quede asociada a una persona identificada y a su rol. Es obligatoria antes de usar datos reales.

## Qué existe hoy

- La app no tiene autenticación. El formulario de decisión envía un campo `usuario` en texto libre (`api/main.py`, `DecisionIn.usuario`, por defecto `"equipo_clinico"`), y las revisiones del canal usan `revisado_por` (por defecto `"tens"`).
- RDS ya tiene `priorizacion.usuario` (`id_usuario`, `rol`, `especialidad`, `activo`), y todas las columnas `*_por` y `id_usuario` son FK a esa tabla (F0002).
- `docs/mvp.md` lo lista como limitación: "Sin autenticación: la maqueta registra el nombre que se escribe en el formulario".

## Alcance

**Entra:** Cognito User Pool, login en el frontend, validación del token en la API, autorización por rol en cada ruta, sincronización del usuario con `priorizacion.usuario` y el usuario autenticado como autor de toda escritura.

**No entra:** federación con el directorio del HLF (SAML u OIDC). Queda como opción documentada para un piloto.

## Diseño

| Pieza | Elección |
|---|---|
| Identidad | **Amazon Cognito User Pool**. En la demo, usuarios creados por un administrador (sin registro abierto); MFA opcional en la demo y obligatorio con datos reales |
| Login | Hosted UI de Cognito con *authorization code* + PKCE. El frontend guarda el token en memoria (no en `localStorage`) y lo renueva con el refresh token |
| Validación en la API | FastAPI verifica la firma del JWT con las claves públicas (JWKS) del User Pool, el `aud` y la expiración. Una dependencia `usuario_actual()` lo inyecta en cada ruta |
| Roles | Grupos de Cognito = `priorizacion.usuario.rol` (`medico`, `enfermeria`, `tens`, `gestor_lista`, `administrativo`) |
| Sincronización | En el primer login válido se crea o actualiza la fila de `priorizacion.usuario` (`id_usuario` = `sub` de Cognito, nombre y rol). Si un usuario está desactivado en la base, se rechaza aunque el token sea válido |

**Matriz de permisos** (se aplica en la API, no solo ocultando botones):

| Acción | medico | enfermeria | tens | gestor_lista | administrativo |
|---|---|---|---|---|---|
| Ver bandeja, ficha, KPIs | ✔ | ✔ | ✔ | ✔ | ✔ (sin detalle clínico) |
| Registrar decisión clínica (aceptar, ajustar, rechazar) | ✔ | — | — | — | — |
| Validar evidencia externa y alarmas del canal | ✔ | ✔ | ✔ | — | — |
| Agenda: proponer y asignar cupos | ✔ | — | — | ✔ | ✔ |
| Ejecutar el proceso nocturno y cambiar el reloj | — | — | — | ✔ | — |
| Consulta en lenguaje natural (F0009) | ✔ | ✔ | — | ✔ | — |

## Cambios por carpeta

```
infra/stacks/identidad.py        User Pool, grupos, app client (PKCE), dominio de Hosted UI, URL de callback = CloudFront
api/seguridad.py                 verificación del JWT (JWKS en caché), usuario_actual(), requiere_rol(*roles)
api/rutas/*.py                   cada ruta declara su rol; escrituras con el id_usuario autenticado
priorizacion/registro*.py        sincronizar_usuario(); los métodos reciben id_usuario en vez de texto libre
web/src/auth/                    cliente OIDC (PKCE), contexto de sesión, ruta protegida, botón salir
web/src/api.ts                   cabecera Authorization: Bearer en cada fetch; 401 → volver al login
tests/test_seguridad.py          tokens firmados de prueba (válido, expirado, otro aud, sin grupo)
```

## Tareas

1. Stack de identidad y usuarios de demo, uno por rol.
2. `api/seguridad.py` con sus pruebas (con claves generadas en el test, sin llamar a Cognito).
3. Aplicar `requiere_rol` a todas las rutas. Agregar una prueba que recorra todas las rutas y falle si alguna no declara rol.
4. Reemplazar `usuario` y `revisado_por` del cuerpo de las peticiones por el usuario del token.
5. Login en el frontend y token en cada llamada.
6. Modo local sin Cognito (`HLF_AUTH=desactivada`) solo para desarrollo, con un aviso visible en la interfaz.

## Criterios de aceptación

- Sin token, toda ruta `/api/*` responde 401, salvo un health check sin datos.
- Un usuario `tens` que intenta registrar una decisión recibe 403, aunque fuerce la petición sin usar la interfaz.
- `priorizacion.decision_clinica.id_usuario` es el `sub` de quien decidió, y su nombre y rol están en `priorizacion.usuario`.
- El token no queda en `localStorage` ni en cookies accesibles desde JavaScript.

## Riesgos y decisiones abiertas

- **Directorio del HLF:** para un piloto, federar con el proveedor de identidad del hospital en vez de crear usuarios en Cognito.
- **Ver datos sin detalle clínico** (rol administrativo): definir qué campos se ocultan.
