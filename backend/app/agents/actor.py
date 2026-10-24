"""En nombre de quién actúa un agente.

Las herramientas trabajan sobre datos de operaciones, así que los permisos son
los del rol de la persona en la app ``operations``, leídos de la base de datos
(nunca del token), aunque el copiloto se abra desde otra app. Lo que el rol no
permite, el agente tampoco: ni se le ofrece la herramienta ni se ejecuta.
"""
from dataclasses import dataclass, field

from flask import g, has_request_context

from ..ai.access import OPERATIONS_APP, Viewer
from ..api.common import owner_of
from ..errors import ForbiddenError
from ..extensions import db
from ..models import AuditAction, User
from ..security.audit import audit


@dataclass(frozen=True)
class Actor:
    user_id: int | None
    role: str | None
    is_admin: bool = False
    permissions: dict = field(default_factory=dict)

    @classmethod
    def for_user(cls, user_id: int | None) -> "Actor":
        from ..security.context import resolve_role

        ctx = g.get("security") if has_request_context() else None
        if ctx is not None and ctx.user_id == user_id and ctx.app_code == OPERATIONS_APP:
            return cls(ctx.user_id, ctx.role_code, ctx.is_admin, dict(ctx.permissions))
        user = db.session.get(User, user_id) if user_id else None
        if user is None or not user.is_active:
            return cls(user_id, None)
        role = resolve_role(user, OPERATIONS_APP)
        if role is None:
            return cls(user.id, None)
        return cls(user.id, role["role"], bool(role["is_admin"]), dict(role["permissions"] or {}))

    def can(self, module: str, action: str) -> bool:
        if self.role is None:
            return False
        return self.is_admin or action in self.permissions.get(module, [])

    def has_ai(self, module: str) -> bool:
        return self.role is not None and (self.is_admin or module in self.permissions.get("ai_modules_access", []))

    @property
    def viewer(self) -> Viewer:
        return Viewer(self.user_id, self.role, self.can("documents", "manage"))

    def ensure_can_modify(self, module: str, obj) -> None:
        """Autorización por objeto: responsable del registro o acción ``manage``."""
        if self.can(module, "manage"):
            return
        owner = owner_of(obj)
        if owner is not None and owner == self.user_id:
            return
        audit(AuditAction.ACCESS_DENIED, "WARNING", user_id=self.user_id,
              resource_type=type(obj).__tablename__, resource_id=getattr(obj, "id", None),
              details={"reason": "not_owner", "module": module, "via": "agent"})
        raise ForbiddenError("Solo el responsable del registro o un gestor puede modificarlo.")
