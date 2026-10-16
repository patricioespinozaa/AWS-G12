"""Autenticación de la Administradora (F0007). Los tokens se firman con una clave RSA generada aquí: no se llama a
Cognito. Las pruebas de la verificación son puras; las de la API cargan la app (necesitan el dataset)."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from api import seguridad as S

CFG = S.ConfigAuth("cognito", "us-east-1", "us-east-1_Prueba", "cliente-hlf", "https://hlf.auth.us-east-1.amazoncognito.com")
CLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTRA_CLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SUB = "0f6c-administradora-prueba"


def token(clave=CLAVE, **cambios) -> str:
    ahora = int(time.time())
    claims = {"sub": SUB, "iss": CFG.emisor, "aud": CFG.client_id, "token_use": "id", "iat": ahora,
              "exp": ahora + 3600, "name": "Administradora de Prueba", "cognito:groups": [S.GRUPO]}
    claims.update(cambios)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, clave, algorithm="RS256",
                      headers={"kid": "prueba"})


@pytest.fixture
def clave_local(monkeypatch):
    monkeypatch.setattr(S, "resolver_clave", lambda cfg, tok: CLAVE.public_key())


# -- verificación del token (sin app) -----------------------------------------------------------------
def test_token_valido(clave_local):
    claims = S.verificar_token(token(), CFG)
    assert claims["sub"] == SUB and S.GRUPO in claims["cognito:groups"]


@pytest.mark.parametrize("caso, tok", [
    ("vencido", lambda: token(exp=int(time.time()) - 120, iat=int(time.time()) - 3720)),
    ("otro cliente", lambda: token(aud="otro-cliente")),
    ("otro user pool", lambda: token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Otro")),
    ("access token", lambda: token(token_use="access")),
    ("firmado con otra clave", lambda: token(clave=OTRA_CLAVE)),
    ("sin sub", lambda: token(sub=None)),
    ("HS256 con la clave pública", lambda: jwt.encode({"sub": SUB}, "secreto", algorithm="HS256")),
])
def test_tokens_rechazados(clave_local, caso, tok):
    with pytest.raises(jwt.PyJWTError):
        S.verificar_token(tok(), CFG)


def test_modo_segun_el_entorno(monkeypatch):
    for v in ("HLF_COGNITO_PARAMETRO", "HLF_COGNITO_USER_POOL_ID", "HLF_DB_SECRET_ID"):
        monkeypatch.delenv(v, raising=False)
    assert S.modo_declarado() == "desactivada" and S.configuracion().modo == "desactivada"
    S.validar_arranque()                                             # local: se permite, con aviso
    monkeypatch.setenv("HLF_DB_SECRET_ID", "arn:secreto")
    with pytest.raises(S.ErrorConfiguracionAuth):                    # en AWS nunca sin login
        S.validar_arranque()
    monkeypatch.setenv("HLF_COGNITO_PARAMETRO", "/hlf/demo/cognito")
    assert S.modo_declarado() == "cognito"
    S.validar_arranque()


def test_sin_configuracion_de_cognito_falla_cerrado(monkeypatch):
    monkeypatch.setenv("HLF_COGNITO_PARAMETRO", "/hlf/demo/cognito")
    monkeypatch.setattr(S, "_config", None)
    monkeypatch.setattr(S, "_leer_parametro", lambda nombre: (_ for _ in ()).throw(RuntimeError("ParameterNotFound")))
    with pytest.raises(Exception) as e:
        S.configuracion()
    assert getattr(e.value, "status_code", None) == 503


# -- la API con Cognito activado ------------------------------------------------------------------------
@pytest.fixture
def con_cognito(monkeypatch, clave_local):
    monkeypatch.delenv("HLF_COGNITO_PARAMETRO", raising=False)
    monkeypatch.setenv("HLF_COGNITO_USER_POOL_ID", CFG.user_pool_id)
    monkeypatch.setenv("HLF_COGNITO_CLIENT_ID", CFG.client_id)
    monkeypatch.setenv("HLF_COGNITO_REGION", CFG.region)
    monkeypatch.setenv("HLF_COGNITO_DOMINIO", CFG.dominio)
    monkeypatch.setattr(S, "_config", None)
    S.olvidar_cuentas()
    yield
    S.olvidar_cuentas()


@pytest.fixture(scope="module")
def cliente():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def _rutas_api(app):
    """Todas las rutas de /api, desde el esquema OpenAPI (incluye las de cada router incluido)."""
    import re
    for plantilla, operaciones in app.openapi()["paths"].items():
        if not plantilla.startswith("/api"):
            continue
        ruta = re.sub(r"\{(\w+)\}", lambda m: "1" if m.group(1) in ("id_carga", "id_propuesta") else "x", plantilla)
        for metodo in operaciones:
            yield metodo.upper(), ruta, plantilla


@pytest.mark.datos
def test_toda_ruta_exige_sesion_salvo_las_publicas(cliente, con_cognito):
    from api.main import app
    publicas, protegidas = set(), 0
    for metodo, ruta, plantilla in _rutas_api(app):
        r = cliente.request(metodo, ruta)
        if plantilla in ("/api/salud", "/api/auth/config"):
            assert r.status_code == 200, plantilla
            publicas.add(plantilla)
        elif plantilla.startswith("/api/interno/"):
            # Entrada de servicios (Lambda de WhatsApp): secreto de servicio, no sesión (sin configurar → 503)
            assert r.status_code in (401, 422, 503), f"{metodo} {plantilla} respondió {r.status_code} sin secreto"
        else:
            assert r.status_code == 401, f"{metodo} {plantilla} respondió {r.status_code} sin sesión"
            assert r.headers.get("www-authenticate") == "Bearer"
            protegidas += 1
    assert publicas == {"/api/salud", "/api/auth/config"} and protegidas > 20
    assert set(cliente.get("/api/salud").json()) == {"ok"}               # sin datos
    assert cliente.get("/api/auth/config").json() == {"modo": "cognito", "dominio": CFG.dominio,
                                                       "client_id": CFG.client_id, "region": CFG.region}


@pytest.mark.datos
def test_token_invalido_o_sin_grupo(cliente, con_cognito):
    assert cliente.get("/api/meta", headers={"Authorization": "Bearer basura"}).status_code == 401
    vencido = token(exp=int(time.time()) - 120, iat=int(time.time()) - 3720)
    r = cliente.get("/api/meta", headers={"Authorization": f"Bearer {vencido}"})
    assert r.status_code == 401 and "venció" in r.json()["detail"]
    sin_grupo = token(**{"cognito:groups": ["otro"]})
    r = cliente.post("/api/solicitudes/IC-HLF-00002/decisiones", json={"corte": "2026-07-21", "decision": "acepta"},
                     headers={"Authorization": f"Bearer {sin_grupo}"})
    assert r.status_code == 403                                           # aunque la petición sea válida


@pytest.mark.datos
def test_la_persona_autenticada_es_la_autora(cliente, con_cognito):
    from api import estado as E
    h = {"Authorization": f"Bearer {token()}"}
    meta = cliente.get("/api/meta", headers=h).json()
    assert meta["sesion"] == {"id_usuario": SUB, "nombre": "Administradora de Prueba", "autenticacion": "cognito"}
    r = cliente.post("/api/solicitudes/IC-HLF-00001/decisiones", headers=h,
                     json={"corte": "2026-07-21", "decision": "ajusta", "nivel_ajuste": "media", "motivo": "Prueba F0007"})
    assert r.status_code == 200, r.text
    d = E.registro.decisiones("IC-HLF-00001")
    assert d.iloc[-1]["usuario"] == SUB                                   # el sub de Cognito, no un texto libre
    usuarios = E.registro.usuarios()
    assert usuarios.set_index("id_usuario").loc[SUB, "nombre"] == "Administradora de Prueba"


@pytest.mark.datos
def test_cuenta_desactivada_no_entra(cliente, con_cognito):
    from api import estado as E
    h = {"Authorization": f"Bearer {token()}"}
    assert cliente.get("/api/meta", headers=h).status_code == 200
    E.registro.activar_usuario(SUB, False)
    S.olvidar_cuentas()                                                   # en producción: a lo más 30 s
    try:
        r = cliente.get("/api/meta", headers=h)
        assert r.status_code == 403 and "desactivada" in r.json()["detail"]
    finally:
        E.registro.activar_usuario(SUB, True)


@pytest.mark.datos
def test_entrada_interna_exige_el_secreto_de_servicio(cliente, monkeypatch):
    from api.rutas import asistente
    monkeypatch.setattr(asistente, "_secreto", "secreto-de-prueba-123")
    r = cliente.post("/api/interno/asistente/whatsapp", json={"evento_sns": "{}"})
    assert r.status_code == 401
    r = cliente.post("/api/interno/asistente/whatsapp", json={"evento_sns": "{}"}, headers={"X-HLF-Servicio": "otro"})
    assert r.status_code == 401
    r = cliente.post("/api/interno/asistente/whatsapp", json={"evento_sns": "{}"},
                     headers={"X-HLF-Servicio": "secreto-de-prueba-123"})
    assert r.status_code == 409                                         # pasa el secreto; local no tiene el esquema canal
