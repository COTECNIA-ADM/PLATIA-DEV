"""MFA con TOTP (app de autenticación) y códigos de respaldo (Capítulo 6, ADR-009).

- El secreto TOTP se guarda cifrado con Fernet (cifrado autenticado).
- Los códigos de respaldo se guardan como SHA-256 con una sal distinta por código
  y son de un solo uso. Se muestran una vez y nunca se guardan en claro.
"""
import hashlib
import hmac
import secrets

import pyotp
from cryptography.fernet import Fernet
from flask import current_app

from ..models import User, utcnow

BACKUP_CODES = 10


def _fernet() -> Fernet:
    return Fernet(current_app.config["MFA_ENCRYPTION_KEY"].encode())


def new_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=current_app.config["MFA_ISSUER"])


def verify_totp(secret: str, code: str) -> bool:
    # valid_window=1: tolera 30 s de desfase de reloj
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


def generate_backup_codes() -> tuple[list[str], list[dict]]:
    codes, stored = [], []
    for _ in range(BACKUP_CODES):
        code = secrets.token_hex(5).upper()  # 10 caracteres
        salt = secrets.token_hex(16)
        stored.append({"salt": salt, "hash": _hash(salt, code), "used_at": None})
        codes.append(code)
    return codes, stored


def _hash(salt: str, code: str) -> str:
    return hashlib.sha256((salt + code).encode()).hexdigest()


def consume_backup_code(user: User, code: str) -> bool:
    """Marca el código como usado si es válido. Recorre todos sin cortar antes."""
    code = code.strip().upper().replace("-", "").replace(" ", "")
    match = None
    entries = [dict(e) for e in (user.mfa_backup_codes or [])]
    for entry in entries:
        if hmac.compare_digest(entry["hash"], _hash(entry["salt"], code)) and not entry["used_at"]:
            match = entry
    if match is None:
        return False
    match["used_at"] = utcnow().isoformat()
    user.mfa_backup_codes = entries  # reasignar para que SQLAlchemy detecte el cambio
    return True


def verify_second_factor(user: User, code: str) -> str | None:
    """Devuelve "totp", "backup" o None."""
    if not user.mfa_enabled or not user.mfa_secret_encrypted or not code:
        return None
    if verify_totp(decrypt_secret(user.mfa_secret_encrypted), code):
        return "totp"
    if consume_backup_code(user, code):
        return "backup"
    return None
