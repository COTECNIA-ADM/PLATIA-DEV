"""Contraseñas con bcrypt (Capítulo 5: mínimo 12 rondas en producción)."""
import bcrypt
from flask import current_app

# Hash de relleno: si el email no existe se compara igualmente contra él, para
# que la respuesta tarde lo mismo y no revele qué usuarios existen.
_DUMMY_HASH = bcrypt.hashpw(b"no-es-una-clave-real", bcrypt.gensalt(rounds=4)).decode()


class WeakPasswordError(ValueError):
    pass


def validate_password_policy(password: str) -> None:
    min_len = current_app.config["PASSWORD_MIN_LENGTH"]
    if len(password) < min_len:
        raise WeakPasswordError(f"La contraseña debe tener al menos {min_len} caracteres.")
    if password.lower() == password or password.upper() == password or not any(
        c.isdigit() for c in password
    ):
        raise WeakPasswordError("La contraseña debe combinar mayúsculas, minúsculas y números.")
    # bcrypt solo usa los primeros 72 bytes: más largo daría una falsa sensación de seguridad
    if len(password.encode()) > 72:
        raise WeakPasswordError("La contraseña no puede superar 72 bytes.")


def hash_password(password: str) -> str:
    rounds = current_app.config["BCRYPT_ROUNDS"]
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    candidate = password_hash or _DUMMY_HASH
    try:
        ok = bcrypt.checkpw(password.encode()[:72], candidate.encode())
    except ValueError:
        return False
    return ok and password_hash is not None
