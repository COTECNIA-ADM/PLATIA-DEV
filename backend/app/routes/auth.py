"""Autenticación: login, segundo factor, refresco, logout, perfil y MFA (Capítulo 6)."""
from datetime import timedelta

from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import (
    decode_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_refresh_cookies,
    unset_refresh_cookies,
)

from ..extensions import db
from ..models import App, AuditAction, User, UserAppMembership, utcnow
from ..security import mfa, sessions
from ..security.audit import audit
from ..security.context import platform_guard, resolve_role
from ..security.passwords import (
    WeakPasswordError,
    hash_password,
    validate_password_policy,
    verify_password,
)
from ..security.ratelimit import rate_limit

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

INVALID = "Email o contraseña incorrectos."


def _json() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _register_failure(user: User | None, email: str, reason: str) -> None:
    details = {"email": email[:255], "reason": reason}
    if user is None:
        audit(AuditAction.LOGIN_FAILED, "WARNING", details=details)
        return
    user.failed_login_count += 1
    if user.failed_login_count >= current_app.config["LOGIN_MAX_FAILURES"]:
        user.locked_until = utcnow() + timedelta(minutes=current_app.config["LOGIN_LOCK_MINUTES"])
        user.failed_login_count = 0
        audit(AuditAction.ACCOUNT_LOCKED, "WARNING", user_id=user.id, details=details)
    db.session.commit()
    audit(AuditAction.LOGIN_FAILED, "WARNING", user_id=user.id, details=details)


def _is_locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until > utcnow())


def _login_response(user: User):
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    access, refresh = sessions.start_session(user)
    audit(AuditAction.LOGIN_SUCCESS, user_id=user.id)
    resp = jsonify(access_token=access, user=_user_payload(user))
    set_refresh_cookies(resp, refresh)
    return resp


def _user_payload(user: User) -> dict:
    apps = []
    rows = db.session.execute(
        db.select(App.code, App.name)
        .join(UserAppMembership, UserAppMembership.app_id == App.id)
        .where(UserAppMembership.user_id == user.id, UserAppMembership.is_active.is_(True))
    ).all()
    codes = {code: name for code, name in rows}
    if user.is_superadmin:
        codes = dict(db.session.execute(db.select(App.code, App.name).where(App.is_active.is_(True))).all())
    for code, name in sorted(codes.items()):
        role = resolve_role(user, code)
        if role:
            apps.append({"code": code, "name": name, "role": role["role"], "is_admin": role["is_admin"]})
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "mfa_enabled": user.mfa_enabled,
        "is_superadmin": user.is_superadmin,
        "apps": apps,
    }


@auth_bp.post("/login")
@rate_limit("RATE_LIMIT_LOGIN", period=60, scope="ip")
def login():
    data = _json()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    user = db.session.scalar(db.select(User).filter_by(email=email)) if email else None
    # Siempre se calcula bcrypt, exista o no el usuario (no revela qué emails existen)
    password_ok = verify_password(password, user.password_hash if user else None)

    if user is None or not user.is_active or user.status != "active":
        _register_failure(None if user is None else user, email, "unknown_or_inactive")
        return jsonify(error=INVALID), 401
    if _is_locked(user):
        audit(AuditAction.LOGIN_FAILED, "WARNING", user_id=user.id, details={"reason": "locked"})
        return jsonify(error=INVALID), 401
    if not password_ok:
        _register_failure(user, email, "bad_password")
        return jsonify(error=INVALID), 401

    if user.mfa_enabled:
        return jsonify(mfa_required=True, mfa_token=sessions.mfa_pending_token(user))
    return _login_response(user)


@auth_bp.post("/mfa/verify")
@rate_limit("RATE_LIMIT_LOGIN", period=60, scope="ip")
def mfa_verify():
    data = _json()
    try:
        claims = decode_token(str(data.get("mfa_token", "")))
    except Exception:  # noqa: BLE001 - caducado, mal firmado o mal formado
        claims = {}
    if not claims.get("mfa_pending") or sessions.is_revoked({**claims, "type": "access"}):
        return jsonify(error="Token de segundo factor no válido o caducado."), 401
    user = db.session.get(User, int(claims["sub"]))
    if user is None or not user.is_active or user.status != "active" or _is_locked(user):
        return jsonify(error="Código no válido."), 401
    method = mfa.verify_second_factor(user, str(data.get("code", "")))
    if method is None:
        audit(AuditAction.MFA_FAILED, "WARNING", user_id=user.id)
        _register_failure(user, user.email, "bad_mfa_code")
        return jsonify(error="Código no válido."), 401
    sessions.revoke_access_token(claims["jti"])  # el token de segundo factor es de un solo uso
    if method == "backup":
        remaining = sum(1 for c in user.mfa_backup_codes or [] if not c["used_at"])
        audit(AuditAction.MFA_BACKUP_CODE_USED, "WARNING", user_id=user.id, details={"remaining": remaining})
    return _login_response(user)


@auth_bp.post("/refresh")
@jwt_required(refresh=True, locations=["cookies"])
def refresh():
    tokens = sessions.rotate(int(get_jwt_identity()), get_jwt()["jti"])
    if tokens is None:
        resp = jsonify(error="Sesión caducada. Vuelve a iniciar sesión.")
        unset_refresh_cookies(resp)
        return resp, 401
    access, new_refresh = tokens
    resp = jsonify(access_token=access)
    set_refresh_cookies(resp, new_refresh)
    return resp


@auth_bp.post("/logout")
@jwt_required(locations=["headers"])
def logout():
    claims = get_jwt()
    sessions.revoke_access_token(claims["jti"])
    if claims.get("fid"):
        sessions.revoke_family(claims["fid"], "logout")
    audit(AuditAction.LOGOUT, user_id=int(get_jwt_identity()))
    resp = jsonify(status="ok")
    unset_refresh_cookies(resp)
    return resp


@auth_bp.get("/me")
@platform_guard
def me():
    ctx = g.security
    return jsonify(
        user=_user_payload(g.current_user),
        active_app={"code": ctx.app_code, "role": ctx.role_code, "is_admin": ctx.is_admin,
                    "permissions": ctx.permissions},
    )


@auth_bp.post("/password")
@platform_guard
@rate_limit("RATE_LIMIT_LOGIN", period=60, scope="user")
def change_password():
    data = _json()
    user: User = g.current_user
    if not verify_password(str(data.get("current_password", "")), user.password_hash):
        audit(AuditAction.ACCESS_DENIED, "WARNING", user_id=user.id, details={"reason": "bad_current_password"})
        return jsonify(error="La contraseña actual no es correcta."), 400
    try:
        validate_password_policy(str(data.get("new_password", "")))
    except WeakPasswordError as exc:
        return jsonify(error=str(exc)), 400
    user.password_hash = hash_password(str(data["new_password"]))
    user.password_changed_at = utcnow()
    db.session.commit()
    sessions.revoke_user_sessions(user.id, "password_changed")
    sessions.revoke_access_token(get_jwt()["jti"])
    audit(AuditAction.PASSWORD_CHANGED, user_id=user.id)
    resp = jsonify(status="ok", detail="Contraseña cambiada. Vuelve a iniciar sesión.")
    unset_refresh_cookies(resp)
    return resp


@auth_bp.post("/mfa/setup")
@platform_guard
def mfa_setup():
    """Genera un secreto nuevo (aún no activo) y devuelve el URI para la app."""
    user: User = g.current_user
    if user.mfa_enabled:
        return jsonify(error="MFA ya está activado."), 400
    secret = mfa.new_secret()
    user.mfa_secret_encrypted = mfa.encrypt_secret(secret)
    db.session.commit()
    return jsonify(secret=secret, otpauth_uri=mfa.provisioning_uri(secret, user.email))


@auth_bp.post("/mfa/enable")
@platform_guard
@rate_limit("RATE_LIMIT_LOGIN", period=60, scope="user")
def mfa_enable():
    user: User = g.current_user
    code = str(_json().get("code", ""))
    if user.mfa_enabled or not user.mfa_secret_encrypted:
        return jsonify(error="Primero genera el secreto con /api/auth/mfa/setup."), 400
    if not mfa.verify_totp(mfa.decrypt_secret(user.mfa_secret_encrypted), code):
        audit(AuditAction.MFA_FAILED, "WARNING", user_id=user.id, details={"step": "enable"})
        return jsonify(error="Código no válido."), 400
    codes, stored = mfa.generate_backup_codes()
    user.mfa_backup_codes = stored
    user.mfa_enabled = True
    db.session.commit()
    audit(AuditAction.MFA_ENABLED, user_id=user.id)
    # Se muestran una sola vez; no se guardan en claro
    return jsonify(status="ok", backup_codes=codes)


@auth_bp.post("/mfa/disable")
@platform_guard
@rate_limit("RATE_LIMIT_LOGIN", period=60, scope="user")
def mfa_disable():
    user: User = g.current_user
    data = _json()
    if not user.mfa_enabled:
        return jsonify(error="MFA no está activado."), 400
    if not verify_password(str(data.get("password", "")), user.password_hash) or not mfa.verify_second_factor(
        user, str(data.get("code", ""))
    ):
        audit(AuditAction.MFA_FAILED, "WARNING", user_id=user.id, details={"step": "disable"})
        return jsonify(error="Contraseña o código no válidos."), 400
    user.mfa_enabled = False
    user.mfa_secret_encrypted = None
    user.mfa_backup_codes = None
    db.session.commit()
    audit(AuditAction.MFA_DISABLED, "WARNING", user_id=user.id)
    return jsonify(status="ok")
