"""Autorización en capas (Capítulo 6).

1. ``platform_guard``: token válido y usuario/rol comprobados contra la BD en cada
   petición. Del token solo se usa el id de usuario; nunca rol ni is_admin.
2. ``require_permission(módulo, acción)``: el rol de la app activa lo permite.
3. ``rate_limit`` (ver ratelimit.py).

La app activa llega en la cabecera ``X-App-Code`` (por defecto ``operations``).
Todo lo que no está permitido explícitamente está denegado.
"""
import json
from dataclasses import dataclass, field
from functools import wraps

import structlog
from flask import current_app, g, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from ..extensions import db
from ..models import App, AppRole, AuditAction, User, UserAppMembership
from .audit import audit
from .redis_store import get_redis
from .registry import AI_MODULES
from .registry import check as check_registered

log = structlog.get_logger(__name__)
DEFAULT_APP = "operations"


@dataclass(frozen=True)
class SecurityContext:
    """Identidad y permisos verificados, creados una vez por petición y propagados."""

    user_id: int
    email: str
    app_code: str
    role_code: str
    is_admin: bool = False
    permissions: dict = field(default_factory=dict)

    def can(self, module: str, action: str) -> bool:
        if self.is_admin:
            return True
        return action in self.permissions.get(module, [])

    def ai_modules(self) -> list[str]:
        return list(self.permissions.get("ai_modules_access", []))


def _cache_key(user_id: int, app_code: str) -> str:
    return f"permissions:{user_id}:{app_code}"


def invalidate_permissions(user_id: int) -> None:
    try:
        r = get_redis()
        for key in r.scan_iter(f"permissions:{user_id}:*"):
            r.delete(key)
    except Exception as exc:  # noqa: BLE001
        log.warning("permissions_cache_unavailable", error=str(exc))


def resolve_role(user: User, app_code: str) -> dict | None:
    """Rol del usuario en una app, desde la BD (con caché de 5 minutos en Redis)."""
    if user.is_superadmin:
        # También para el superadmin, la app tiene que existir y estar activa
        exists = db.session.scalar(db.select(App.id).filter_by(code=app_code, is_active=True))
        return {"role": "superadmin", "is_admin": True, "permissions": {}} if exists else None
    key = _cache_key(user.id, app_code)
    try:
        cached = get_redis().get(key)
        if cached:
            return json.loads(cached)
    except Exception as exc:  # noqa: BLE001 - sin caché se consulta la BD
        log.warning("permissions_cache_unavailable", error=str(exc))
    row = db.session.execute(
        db.select(AppRole)
        .join(UserAppMembership, UserAppMembership.role_id == AppRole.id)
        .join(App, App.id == UserAppMembership.app_id)
        .where(
            UserAppMembership.user_id == user.id,
            UserAppMembership.is_active.is_(True),
            App.code == app_code,
            App.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    role = {"role": row.code, "is_admin": bool(row.is_admin), "permissions": dict(row.permissions or {})}
    try:
        get_redis().setex(key, current_app.config["PERMISSIONS_CACHE_SECONDS"], json.dumps(role))
    except Exception:  # noqa: BLE001
        pass
    return role


def _deny(status: int, message: str, user_id: int | None = None, **details):
    if status == 403:
        audit(AuditAction.ACCESS_DENIED, "WARNING", user_id=user_id,
              details={"path": request.path, **details})
    return jsonify(error=message), status


def platform_guard(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request(locations=["headers"])
        if get_jwt().get("mfa_pending"):
            return _deny(401, "Falta completar el segundo factor.")
        user = db.session.get(User, int(get_jwt_identity()))
        if user is None or not user.is_active or user.status != "active":
            return _deny(401, "Sesión no válida.")
        app_code = (request.headers.get("X-App-Code") or DEFAULT_APP).strip().lower()
        role = resolve_role(user, app_code)
        if role is None:
            return _deny(403, "Sin acceso a esta aplicación.", user.id, app=app_code)
        g.security = SecurityContext(
            user_id=user.id,
            email=user.email,
            app_code=app_code,
            role_code=role["role"],
            is_admin=role["is_admin"],
            permissions=role["permissions"],
        )
        g.current_user = user
        structlog.contextvars.bind_contextvars(user_id=user.id, app=app_code)
        return fn(*args, **kwargs)

    wrapper.platform_guard = True  # lo revisa tests/test_security_matrix.py
    return wrapper


def require_permission(module: str, action: str):
    check_registered(module, action)  # falla al importar si el permiso no existe

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ctx: SecurityContext | None = g.get("security")
            if ctx is None:  # mal encadenado: sin platform_guard no hay acceso
                return _deny(401, "Autenticación requerida.")
            if not ctx.can(module, action):
                return _deny(403, "Permiso insuficiente.", ctx.user_id,
                             app=ctx.app_code, permission=f"{module}.{action}")
            return fn(*args, **kwargs)

        wrapper.required_permission = (module, action)
        return wrapper

    return decorator


def require_ai_module(name: str):
    """Acceso a un módulo de IA (``ai_modules_access`` del rol). Va después de
    ``require_permission``: el módulo de IA no sustituye al permiso sobre los datos."""
    if name not in AI_MODULES:
        raise LookupError(f"Módulo de IA desconocido '{name}'. Añádelo a app/security/registry.py.")

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ctx: SecurityContext | None = g.get("security")
            if ctx is None:
                return _deny(401, "Autenticación requerida.")
            if not ctx.is_admin and name not in ctx.ai_modules():
                return _deny(403, "Tu rol no tiene acceso a esta función de IA.", ctx.user_id,
                             app=ctx.app_code, ai_module=name)
            return fn(*args, **kwargs)

        wrapper.required_ai_module = name
        return wrapper

    return decorator
