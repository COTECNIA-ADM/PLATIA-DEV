"""Usuarios, roles y auditoría (app ``admin``).

Todas las rutas exigen ``X-App-Code: admin`` y el permiso correspondiente. Cada
cambio de acceso queda auditado y vacía la caché de permisos de quien lo recibe.
"""
from datetime import timedelta

from flask import Blueprint, g, jsonify, request

from ..api.common import check_version, iso, paginate, parse_body
from ..api.schemas import RolePermissionsIn, UserCreateIn, UserMembershipIn
from ..errors import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (
    App,
    AppRole,
    AuditAction,
    AuditLog,
    User,
    UserAppMembership,
    utcnow,
)
from ..security import registry, sessions
from ..security.audit import audit
from ..security.context import (
    invalidate_permissions,
    platform_guard,
    require_permission,
)
from ..security.passwords import (
    WeakPasswordError,
    hash_password,
    validate_password_policy,
)
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


# ------------------------------------------------------------------ Usuarios
def _user_dict(user: User) -> dict:
    memberships = db.session.execute(
        db.select(App.code, AppRole.code, AppRole.name, UserAppMembership.is_active)
        .join(App, App.id == UserAppMembership.app_id)
        .join(AppRole, AppRole.id == UserAppMembership.role_id)
        .where(UserAppMembership.user_id == user.id)
        .order_by(App.code)
    ).all()
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "status": user.status,
        "is_active": user.is_active,
        "is_superadmin": user.is_superadmin,
        "mfa_enabled": user.mfa_enabled,
        "locked_until": iso(user.locked_until),
        "last_login_at": iso(user.last_login_at),
        "created_at": iso(user.created_at),
        "memberships": [{"app": a, "role": r, "role_name": n, "is_active": act} for a, r, n, act in memberships],
    }


def _get_user(user_id: int) -> User:
    user = db.session.get(User, user_id)
    if user is None:
        raise NotFoundError("Usuario no encontrado.")
    return user


@admin_bp.get("/users")
@platform_guard
@_admin_app_only
@require_permission("users", "read")
@rate_limit("RATE_LIMIT_READ")
def list_users():
    stmt = db.select(User).order_by(User.full_name, User.id)
    if q := (request.args.get("q") or "").strip()[:100]:
        like = f"%{q.lower()}%"
        stmt = stmt.where(db.or_(db.func.lower(User.email).like(like), db.func.lower(User.full_name).like(like)))
    if request.args.get("status") in ("active", "inactive"):
        stmt = stmt.where(User.is_active.is_(request.args["status"] == "active"))
    if app_code := request.args.get("app"):
        stmt = stmt.where(User.id.in_(
            db.select(UserAppMembership.user_id).join(App, App.id == UserAppMembership.app_id)
            .where(App.code == app_code, UserAppMembership.is_active.is_(True))))
    return jsonify(paginate(stmt, _user_dict))


@admin_bp.get("/users/<int:user_id>")
@platform_guard
@_admin_app_only
@require_permission("users", "read")
@rate_limit("RATE_LIMIT_READ")
def get_user(user_id: int):
    return jsonify(user=_user_dict(_get_user(user_id)))


@admin_bp.post("/users")
@platform_guard
@_admin_app_only
@require_permission("users", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_user():
    data = parse_body(UserCreateIn)
    email = data.email.lower()
    if db.session.scalar(db.select(User).filter_by(email=email)):
        raise ConflictError("Ya existe un usuario con ese email.")
    try:
        validate_password_policy(data.password)
    except WeakPasswordError as exc:
        raise ValidationError(str(exc)) from exc
    user = User(email=email, full_name=data.full_name, password_hash=hash_password(data.password),
                created_by=g.security.user_id)
    db.session.add(user)
    db.session.commit()
    audit(AuditAction.USER_CREATED, user_id=g.security.user_id, resource_type="user", resource_id=user.id)
    return jsonify(user=_user_dict(user)), 201


@admin_bp.put("/users/<int:user_id>/memberships/<app_code>")
@platform_guard
@_admin_app_only
@require_permission("roles", "write")
@rate_limit("RATE_LIMIT_WRITE")
def set_membership(user_id: int, app_code: str):
    user = _get_user(user_id)
    app = db.session.scalar(db.select(App).filter_by(code=app_code))
    if app is None:
        raise NotFoundError("Aplicación no encontrada.")
    data = parse_body(UserMembershipIn)
    role = db.session.scalar(db.select(AppRole).filter_by(app_id=app.id, code=data.role))
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
          resource_id=user.id, details={"app": app_code, "role": data.role})
    return jsonify(user=_user_dict(user))


@admin_bp.delete("/users/<int:user_id>/memberships/<app_code>")
@platform_guard
@_admin_app_only
@require_permission("roles", "write")
@rate_limit("RATE_LIMIT_WRITE")
def revoke_membership(user_id: int, app_code: str):
    user = _get_user(user_id)
    membership = db.session.scalar(
        db.select(UserAppMembership).join(App, App.id == UserAppMembership.app_id)
        .where(UserAppMembership.user_id == user.id, App.code == app_code))
    if membership is None or not membership.is_active:
        raise NotFoundError("Este usuario no tiene acceso a esa aplicación.")
    if user.id == g.security.user_id and app_code == "admin":
        raise BusinessRuleError("No puedes quitarte tu propio acceso a Admin.")
    membership.is_active = False
    db.session.commit()
    invalidate_permissions(user.id)
    audit(AuditAction.ROLE_REVOKED, "WARNING", user_id=g.security.user_id, resource_type="user",
          resource_id=user.id, details={"app": app_code})
    return jsonify(user=_user_dict(user))


@admin_bp.post("/users/<int:user_id>/deactivate")
@platform_guard
@_admin_app_only
@require_permission("users", "write")
@rate_limit("RATE_LIMIT_WRITE")
def deactivate_user(user_id: int):
    user = _get_user(user_id)
    if user.id == g.security.user_id:
        return jsonify(error="No puedes desactivar tu propia cuenta."), 400
    user.soft_delete()
    db.session.commit()
    sessions.revoke_user_sessions(user.id, "user_deactivated")
    invalidate_permissions(user.id)
    audit(AuditAction.USER_DEACTIVATED, "WARNING", user_id=g.security.user_id,
          resource_type="user", resource_id=user.id)
    return jsonify(user=_user_dict(user))


@admin_bp.post("/users/<int:user_id>/reactivate")
@platform_guard
@_admin_app_only
@require_permission("users", "write")
@rate_limit("RATE_LIMIT_WRITE")
def reactivate_user(user_id: int):
    user = _get_user(user_id)
    if user.is_active:
        raise BusinessRuleError("El usuario ya está activo.")
    user.restore()
    user.failed_login_count, user.locked_until = 0, None
    db.session.commit()
    invalidate_permissions(user.id)
    audit(AuditAction.USER_REACTIVATED, "WARNING", user_id=g.security.user_id,
          resource_type="user", resource_id=user.id)
    return jsonify(user=_user_dict(user))


@admin_bp.post("/users/<int:user_id>/mfa/reset")
@platform_guard
@_admin_app_only
@require_permission("users", "write")
@rate_limit("RATE_LIMIT_WRITE")
def reset_mfa(user_id: int):
    """Para quien pierde el móvil: quita el MFA y cierra sus sesiones. Lo vuelve a activar
    al entrar, desde «Mi cuenta»."""
    user = _get_user(user_id)
    if user.id == g.security.user_id:
        raise BusinessRuleError("Tu propio MFA se gestiona desde «Mi cuenta».")
    if not user.mfa_enabled:
        raise BusinessRuleError("Este usuario no tiene el MFA activado.")
    user.mfa_enabled, user.mfa_secret_encrypted, user.mfa_backup_codes = False, None, None
    db.session.commit()
    sessions.revoke_user_sessions(user.id, "mfa_reset_by_admin")
    audit(AuditAction.MFA_RESET_BY_ADMIN, "WARNING", user_id=g.security.user_id,
          resource_type="user", resource_id=user.id)
    return jsonify(user=_user_dict(user))


# ------------------------------------------------------------------ Aplicaciones y roles
def _role_dict(role: AppRole, members: int) -> dict:
    return {"id": role.id, "code": role.code, "name": role.name, "is_admin": role.is_admin,
            "permissions": role.permissions or {}, "members": members, "version": role.row_version,
            "updated_at": iso(role.updated_at)}


@admin_bp.get("/apps")
@platform_guard
@_admin_app_only
@require_permission("roles", "read")
@rate_limit("RATE_LIMIT_READ")
def list_apps():
    """Aplicaciones con sus roles y el catálogo de permisos para el editor."""
    members = dict(db.session.execute(
        db.select(UserAppMembership.role_id, db.func.count())
        .join(User, User.id == UserAppMembership.user_id)
        .where(UserAppMembership.is_active.is_(True), User.is_active.is_(True))
        .group_by(UserAppMembership.role_id)).all())
    apps = db.session.scalars(db.select(App).where(App.is_active.is_(True)).order_by(App.id)).all()
    return jsonify(items=[{
        "code": a.code, "name": a.name, "description": a.description,
        "modules": [{"module": m, "actions": sorted(registry.MODULES[m])}
                    for m in registry.APP_MODULES.get(a.code, ())],
        "roles": [_role_dict(r, members.get(r.id, 0)) for r in sorted(a.roles, key=lambda r: r.id)],
    } for a in apps], ai_modules=sorted(registry.AI_MODULES))


@admin_bp.patch("/roles/<int:role_id>")
@platform_guard
@_admin_app_only
@require_permission("roles", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_role(role_id: int):
    role = db.session.get(AppRole, role_id)
    if role is None:
        raise NotFoundError("Rol no encontrado.")
    data = parse_body(RolePermissionsIn)
    check_version(role, data.version)
    if role.is_admin:
        raise BusinessRuleError("Un rol de administrador ya tiene todos los permisos de su aplicación.")
    permissions = {m: sorted(set(a)) for m, a in data.permissions.items() if a}
    if errors := registry.validate_permissions(permissions):
        raise ValidationError("Permisos desconocidos: " + ", ".join(errors))
    allowed = set(registry.APP_MODULES.get(role.app.code, ())) | {"ai_modules_access"}
    if foreign := sorted(set(permissions) - allowed):
        raise ValidationError(f"Estos módulos no son de la aplicación '{role.app.code}': {', '.join(foreign)}")
    before = role.permissions
    role.permissions = permissions
    db.session.commit()
    user_ids = db.session.scalars(db.select(UserAppMembership.user_id).filter_by(role_id=role.id)).all()
    for uid in user_ids:
        invalidate_permissions(uid)
    audit(AuditAction.ROLE_PERMISSIONS_CHANGED, "WARNING", user_id=g.security.user_id, resource_type="app_role",
          resource_id=role.id, details={"app": role.app.code, "role": role.code, "before": before,
                                        "after": permissions})
    return jsonify(_role_dict(role, len(user_ids)))


# ------------------------------------------------------------------ Auditoría
def _audit_dict(row: AuditLog, emails: dict[int, str]) -> dict:
    return {"id": row.id, "action": row.action, "severity": row.severity, "user_id": row.user_id,
            "user_email": emails.get(row.user_id) if row.user_id else None,
            "resource_type": row.resource_type, "resource_id": row.resource_id, "ip_address": row.ip_address,
            "request_id": row.request_id, "details": row.details, "created_at": iso(row.created_at)}


@admin_bp.get("/audit")
@platform_guard
@_admin_app_only
@require_permission("audit", "read")
@rate_limit("RATE_LIMIT_READ")
def list_audit():
    stmt = db.select(AuditLog).order_by(AuditLog.id.desc())
    if action := request.args.get("action"):
        stmt = stmt.where(AuditLog.action == action[:60])
    if request.args.get("severity") in ("INFO", "WARNING", "CRITICAL", "ERROR"):
        stmt = stmt.where(AuditLog.severity == request.args["severity"])
    if (uid := request.args.get("user_id", "")).isdigit():
        stmt = stmt.where(AuditLog.user_id == int(uid))
    if (days := request.args.get("days", "")).isdigit():
        stmt = stmt.where(AuditLog.created_at >= utcnow() - timedelta(days=min(int(days), 366)))
    page = paginate(stmt, lambda r: r)
    ids = {r.user_id for r in page["items"] if r.user_id}
    emails = dict(db.session.execute(db.select(User.id, User.email).where(User.id.in_(ids))).all()) if ids else {}
    page["items"] = [_audit_dict(r, emails) for r in page["items"]]
    return jsonify(page)


@admin_bp.get("/audit/actions")
@platform_guard
@_admin_app_only
@require_permission("audit", "read")
@rate_limit("RATE_LIMIT_READ")
def audit_actions():
    """Acciones registrables, para el filtro de la pantalla de auditoría."""
    return jsonify(items=sorted(v for k, v in vars(AuditAction).items() if k.isupper()))
