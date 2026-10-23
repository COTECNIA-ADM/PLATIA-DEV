"""Administración mínima de usuarios y auditoría (app ``admin``).

Todas las rutas exigen ``X-App-Code: admin`` y el permiso correspondiente.
"""
from flask import Blueprint, g, jsonify, request

from ..extensions import db
from ..models import App, AppRole, AuditAction, AuditLog, User, UserAppMembership
from ..security import sessions
from ..security.audit import audit
from ..security.context import invalidate_permissions, platform_guard, require_permission
from ..security.passwords import WeakPasswordError, hash_password, validate_password_policy
from ..security.ratelimit import rate_limit

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _admin_app_only(fn):
    """Estas rutas solo existen dentro de la app admin."""
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.security.app_code != "admin":
            audit(AuditAction.ACCESS_DENIED, "WARNING", user_id=g.security.user_id,
                  details={"path": request.path, "app": g.security.app_code})
            return jsonify(error="Usa la aplicación admin (cabecera X-App-Code: admin)."), 403
        return fn(*args, **kwargs)

    return wrapper


def _user_dict(user: User) -> dict:
    memberships = db.session.execute(
        db.select(App.code, AppRole.code, UserAppMembership.is_active)
        .join(App, App.id == UserAppMembership.app_id)
        .join(AppRole, AppRole.id == UserAppMembership.role_id)
        .where(UserAppMembership.user_id == user.id)
    ).all()
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "status": user.status,
        "is_active": user.is_active,
        "mfa_enabled": user.mfa_enabled,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "memberships": [{"app": a, "role": r, "is_active": act} for a, r, act in memberships],
    }


@admin_bp.get("/users")
@platform_guard
@_admin_app_only
@require_permission("users", "read")
@rate_limit()
def list_users():
    users = db.session.scalars(db.select(User).order_by(User.id)).all()
    return jsonify(users=[_user_dict(u) for u in users])


@admin_bp.post("/users")
@platform_guard
@_admin_app_only
@require_permission("users", "write")
@rate_limit()
def create_user():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    full_name = str(data.get("full_name", "")).strip()
    if "@" not in email or not full_name:
        return jsonify(error="Faltan email o nombre."), 400
    if db.session.scalar(db.select(User).filter_by(email=email)):
        return jsonify(error="Ya existe un usuario con ese email."), 409
    try:
        validate_password_policy(str(data.get("password", "")))
    except WeakPasswordError as exc:
        return jsonify(error=str(exc)), 400
    user = User(email=email, full_name=full_name, password_hash=hash_password(data["password"]),
                created_by=g.security.user_id)
    db.session.add(user)
    db.session.commit()
    audit(AuditAction.USER_CREATED, user_id=g.security.user_id, resource_type="user", resource_id=user.id)
    return jsonify(user=_user_dict(user)), 201


@admin_bp.put("/users/<int:user_id>/memberships/<app_code>")
@platform_guard
@_admin_app_only
@require_permission("roles", "write")
@rate_limit()
def set_membership(user_id: int, app_code: str):
    user = db.session.get(User, user_id)
    app = db.session.scalar(db.select(App).filter_by(code=app_code))
    if user is None or app is None:
        return jsonify(error="Usuario o aplicación no encontrados."), 404
    role_code = str((request.get_json(silent=True) or {}).get("role", ""))
    role = db.session.scalar(db.select(AppRole).filter_by(app_id=app.id, code=role_code))
    if role is None:
        return jsonify(error="Rol no válido para esta aplicación."), 400
    membership = db.session.scalar(db.select(UserAppMembership).filter_by(user_id=user.id, app_id=app.id))
    if membership is None:
        membership = UserAppMembership(user_id=user.id, app_id=app.id, role_id=role.id,
                                       created_by=g.security.user_id)
        db.session.add(membership)
    membership.role_id, membership.is_active = role.id, True
    db.session.commit()
    invalidate_permissions(user.id)
    audit(AuditAction.ROLE_ASSIGNED, user_id=g.security.user_id, resource_type="user",
          resource_id=user.id, details={"app": app_code, "role": role_code})
    return jsonify(user=_user_dict(user))


@admin_bp.post("/users/<int:user_id>/deactivate")
@platform_guard
@_admin_app_only
@require_permission("users", "write")
@rate_limit()
def deactivate_user(user_id: int):
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify(error="Usuario no encontrado."), 404
    if user.id == g.security.user_id:
        return jsonify(error="No puedes desactivar tu propia cuenta."), 400
    user.soft_delete()
    db.session.commit()
    sessions.revoke_user_sessions(user.id, "user_deactivated")
    invalidate_permissions(user.id)
    audit(AuditAction.USER_DEACTIVATED, "WARNING", user_id=g.security.user_id,
          resource_type="user", resource_id=user.id)
    return jsonify(user=_user_dict(user))


@admin_bp.get("/audit")
@platform_guard
@_admin_app_only
@require_permission("audit", "read")
@rate_limit()
def list_audit():
    limit = min(max(request.args.get("limit", 50, type=int), 1), 200)
    rows = db.session.scalars(db.select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    return jsonify(entries=[
        {"id": r.id, "action": r.action, "severity": r.severity, "user_id": r.user_id,
         "ip_address": r.ip_address, "details": r.details, "created_at": r.created_at.isoformat()}
        for r in rows
    ])
