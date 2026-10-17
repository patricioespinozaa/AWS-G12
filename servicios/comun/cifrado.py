"""Teléfonos de los pacientes (F0002, F0010): cifrados con KMS y buscados por HMAC; nunca en texto plano en la base.

- `hmac_telefono(e164)`: HMAC-SHA256 con un *pepper* (Secrets Manager en AWS). Es la llave de búsqueda
  (canal.contacto_paciente.valor_hash) y la base de la clave de sesión de WhatsApp.
- `cifrar(e164)` / `descifrar(bytes)`: KMS con la clave del entorno (HLF_KMS_KEY_ID). Sin clave configurada (solo
  desarrollo local y pruebas) se usa un envoltorio reversible marcado `local:` que nunca debe llegar a producción:
  la API no arranca así con la RDS de AWS (ver api/seguridad.py, mismo criterio).
- `normalizar(numero)`: a E.164 chileno (+569XXXXXXXX). WhatsApp entrega el número sin "+".
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading

_lock = threading.Lock()
_pepper: bytes | None = None
LOCAL = b"local:"


class ErrorCifrado(RuntimeError):
    pass


def normalizar(numero: str) -> str:
    digitos = re.sub(r"\D", "", numero or "")
    if not digitos:
        raise ValueError("Número vacío")
    if len(digitos) == 9 and digitos.startswith("9"):          # 9XXXXXXXX → móvil chileno
        digitos = "56" + digitos
    if len(digitos) < 8 or len(digitos) > 15:
        raise ValueError("Número con largo inválido")
    return "+" + digitos


def _leer_pepper() -> bytes:
    if valor := os.environ.get("HLF_HMAC_PEPPER"):
        return valor.encode()
    if secreto := os.environ.get("HLF_HMAC_SECRET_ID"):
        import boto3
        cuerpo = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION")).get_secret_value(
            SecretId=secreto)["SecretString"]
        try:
            cuerpo = json.loads(cuerpo).get("pepper", cuerpo)
        except ValueError:
            pass
        return cuerpo.encode()
    if os.environ.get("HLF_DB_SECRET_ID"):                    # AWS sin pepper: nunca un valor por defecto
        raise ErrorCifrado("Falta HLF_HMAC_SECRET_ID: el HMAC de los teléfonos no puede usar un valor por defecto")
    return b"pepper-solo-desarrollo-local"


def pepper() -> bytes:
    global _pepper
    with _lock:
        if _pepper is None:
            _pepper = _leer_pepper()
        return _pepper


def hmac_texto(texto: str) -> str:
    return hmac.new(pepper(), texto.encode("utf-8"), hashlib.sha256).hexdigest()


def hmac_telefono(numero: str) -> str:
    return hmac_texto(normalizar(numero))


def cifrar(numero: str) -> bytes:
    e164 = normalizar(numero)
    if clave := os.environ.get("HLF_KMS_KEY_ID"):
        import boto3
        return boto3.client("kms", region_name=os.environ.get("AWS_REGION")).encrypt(
            KeyId=clave, Plaintext=e164.encode(), EncryptionContext={"uso": "telefono_paciente"})["CiphertextBlob"]
    if os.environ.get("HLF_DB_SECRET_ID"):
        raise ErrorCifrado("Falta HLF_KMS_KEY_ID: en AWS los teléfonos se cifran con KMS")
    return LOCAL + base64.b64encode(e164.encode())


def descifrar(blob: bytes) -> str:
    blob = bytes(blob)
    if blob.startswith(LOCAL):
        return base64.b64decode(blob[len(LOCAL):]).decode()
    import boto3
    return boto3.client("kms", region_name=os.environ.get("AWS_REGION")).decrypt(
        CiphertextBlob=blob, EncryptionContext={"uso": "telefono_paciente"})["Plaintext"].decode()
