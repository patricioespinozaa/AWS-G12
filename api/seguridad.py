"""Autenticación de la Administradora (F0007): Cognito User Pool con un solo grupo, `administracion`.

El frontend inicia sesión en el Hosted UI de Cognito (authorization code + PKCE) y envía el **ID token** en
`Authorization: Bearer …`. Se usa el ID token porque trae el nombre de la persona, que queda como autora de cada
carga, decisión y revisión. La API verifica:
- la firma RS256 con las claves públicas (JWKS) del User Pool, en caché;
- el emisor (el User Pool), la audiencia (el app client), la expiración y `token_use = id`;
- que la persona esté en el grupo `administracion` (si no, 403);
- que su cuenta esté activa en `priorizacion.usuario` (desactivarla ahí corta el acceso aunque el token siga vigente).

Configuración, en este orden:
1. `HLF_COGNITO_PARAMETRO`: nombre de un parámetro de SSM con {region, user_pool_id, client_id, dominio}. Es lo que
   usa AWS: el app client se crea junto con CloudFront (su URL de retorno es la de la distribución), después del
   backend, así que la API lo lee en tiempo de ejecución en vez de recibirlo al desplegar.
2. `HLF_COGNITO_USER_POOL_ID`, `HLF_COGNITO_CLIENT_ID`, `HLF_COGNITO_DOMINIO` y `HLF_COGNITO_REGION`.
3. Ninguna: modo **desactivado** (desarrollo local), todo se registra a nombre de `config.USUARIA` y la app lo avisa.
   La API se niega a arrancar así si usa la RDS de AWS (`HLF_DB_SECRET_ID`): en AWS siempre hay login.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

import jwt
from fastapi import HTTPException, Request

from priorizacion import config

log = logging.getLogger("hlf.seguridad")

GRUPO = "administracion"
ALGORITMOS = ["RS256"]
MARGEN_RELOJ_S = 30                   # diferencia de reloj tolerada entre Cognito y la tarea
TTL_CONFIG_S = 300
TTL_CUENTA_S = 30                     # cada cuánto se vuelve a mirar si la cuenta sigue activa


class ErrorConfiguracionAuth(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfigAuth:
    modo: str                          # "cognito" | "desactivada"
    region: str = ""
    user_pool_id: str = ""
    client_id: str = ""
    dominio: str = ""                  # https://<prefijo>.auth.<region>.amazoncognito.com

    @property
    def emisor(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    @property
    def jwks_url(self) -> str:
        return f"{self.emisor}/.well-known/jwks.json"

    def publica(self) -> dict:
        """Lo que necesita el frontend para iniciar sesión (nada secreto: es un cliente público con PKCE)."""
        return {"modo": self.modo, "dominio": self.dominio, "client_id": self.client_id, "region": self.region}


@dataclass(frozen=True)
class Persona:
    id_usuario: str                    # `sub` de Cognito (o config.USUARIA en modo desactivado)
    nombre: str


# -- configuración -------------------------------------------------------------------------------------
_config: tuple[float, ConfigAuth] | None = None
_config_lock = threading.Lock()


def modo_declarado() -> str:
    """Sin leer AWS: "cognito" si hay algo de Cognito configurado; si no, "desactivada"."""
    if os.environ.get("HLF_COGNITO_PARAMETRO") or os.environ.get("HLF_COGNITO_USER_POOL_ID"):
        return "cognito"
    return "desactivada"


def validar_arranque() -> None:
    """En AWS (RDS por secreto) la API nunca corre sin login."""
    if modo_declarado() == "desactivada" and os.environ.get("HLF_DB_SECRET_ID"):
        raise ErrorConfiguracionAuth("La API usa la RDS de AWS pero no tiene Cognito configurado "
                                     "(HLF_COGNITO_PARAMETRO): no se arranca sin autenticación.")
    if modo_declarado() == "desactivada":
        log.warning("Autenticación desactivada: todo se registra a nombre de %s (solo desarrollo local)", config.USUARIA)


def _leer_parametro(nombre: str) -> dict:
    import boto3
    valor = boto3.client("ssm", region_name=config.AWS_REGION).get_parameter(Name=nombre)["Parameter"]["Value"]
    return json.loads(valor)


def configuracion() -> ConfigAuth:
    global _config
    if modo_declarado() == "desactivada":
        return ConfigAuth("desactivada")
    with _config_lock:
        if _config and time.time() - _config[0] < TTL_CONFIG_S:
            return _config[1]
        try:
            if nombre := os.environ.get("HLF_COGNITO_PARAMETRO"):
                p = _leer_parametro(nombre)
            else:
                p = {"region": os.environ.get("HLF_COGNITO_REGION") or config.AWS_REGION,
                     "user_pool_id": os.environ["HLF_COGNITO_USER_POOL_ID"],
                     "client_id": os.environ.get("HLF_COGNITO_CLIENT_ID", ""),
                     "dominio": os.environ.get("HLF_COGNITO_DOMINIO", "")}
            cfg = ConfigAuth("cognito", p["region"], p["user_pool_id"], p["client_id"], p["dominio"].rstrip("/"))
        except Exception as e:  # noqa: BLE001 — sin configuración no se deja pasar a nadie (falla cerrado)
            log.error("No se pudo leer la configuración de Cognito: %s", e)
            raise HTTPException(503, "La autenticación no está disponible. Intenta en unos minutos.")
        if not (cfg.region and cfg.user_pool_id and cfg.client_id):
            raise HTTPException(503, "La autenticación no está configurada por completo.")
        _config = (time.time(), cfg)
        return cfg


# -- verificación del token ----------------------------------------------------------------------------
_jwks: dict[str, jwt.PyJWKClient] = {}


def _clave_desde_jwks(cfg: ConfigAuth, token: str):
    if cfg.jwks_url not in _jwks:
        _jwks[cfg.jwks_url] = jwt.PyJWKClient(cfg.jwks_url, cache_keys=True, lifespan=3600, timeout=10)
    return _jwks[cfg.jwks_url].get_signing_key_from_jwt(token).key


# Se reemplaza en las pruebas por una clave generada localmente (sin llamar a Cognito)
resolver_clave: Callable[[ConfigAuth, str], object] = _clave_desde_jwks


def verificar_token(token: str, cfg: ConfigAuth) -> dict:
    """Devuelve los claims del ID token, o lanza jwt.PyJWTError si no es válido para este User Pool y cliente."""
    claims = jwt.decode(token, resolver_clave(cfg, token), algorithms=ALGORITMOS, audience=cfg.client_id,
                        issuer=cfg.emisor, leeway=MARGEN_RELOJ_S,
                        options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    if claims.get("token_use") != "id":
        raise jwt.InvalidTokenError("Se esperaba un ID token")
    return claims


# -- cuenta activa -------------------------------------------------------------------------------------
_cuentas: dict[str, tuple[float, bool]] = {}


def _cuenta_activa(p: Persona) -> bool:
    """Crea o actualiza a la persona en la base y dice si puede entrar (con una caché corta)."""
    from . import estado as E
    visto = _cuentas.get(p.id_usuario)
    if visto and time.time() - visto[0] < TTL_CUENTA_S:
        return visto[1]
    activa = E.registro.sincronizar_usuario(p.id_usuario, p.nombre)
    _cuentas[p.id_usuario] = (time.time(), activa)
    return activa


def olvidar_cuentas() -> None:
    _cuentas.clear()


# -- dependencia de FastAPI ----------------------------------------------------------------------------
def _no_autenticado(mensaje: str) -> HTTPException:
    return HTTPException(401, mensaje, headers={"WWW-Authenticate": "Bearer"})


def administradora(request: Request) -> Persona:
    """La persona autenticada, que debe ser Administradora. Se aplica a todas las rutas de /api (api/main.py) y las
    que escriben la reciben como parámetro para registrarla como autora."""
    cfg = configuracion()
    if cfg.modo == "desactivada":
        return Persona(config.USUARIA, "Administradora (sin autenticación)")
    cabecera = request.headers.get("authorization", "")
    tipo, _, token = cabecera.partition(" ")
    if tipo.lower() != "bearer" or not token:
        raise _no_autenticado("Inicia sesión para continuar.")
    try:
        claims = verificar_token(token.strip(), cfg)
    except jwt.ExpiredSignatureError:
        raise _no_autenticado("La sesión venció. Vuelve a iniciar sesión.")
    except jwt.PyJWTError as e:
        log.info("Token rechazado: %s", e)
        raise _no_autenticado("La sesión no es válida. Vuelve a iniciar sesión.")
    if GRUPO not in (claims.get("cognito:groups") or []):
        raise HTTPException(403, "Tu cuenta no tiene acceso a esta plataforma (solo la Administradora).")
    persona = Persona(claims["sub"], claims.get("name") or claims.get("email") or claims.get("cognito:username")
                      or claims["sub"])
    if not _cuenta_activa(persona):
        raise HTTPException(403, "Tu cuenta está desactivada.")
    return persona
