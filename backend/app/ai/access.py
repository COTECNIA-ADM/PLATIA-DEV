"""Quién puede ver qué documento, también dentro de la búsqueda semántica (Capítulo 12).

Un documento sin ``allowed_roles`` lo ve cualquiera con ``documents.read``. Con
roles, solo su propietario, esos roles de la app de operaciones y quien tenga
``documents.manage``. La misma regla se aplica en tres sitios:

1. En MySQL, al listar, abrir o descargar documentos.
2. En Qdrant, como filtro de la búsqueda vectorial (el payload lleva los roles).
3. Otra vez en el backend sobre los resultados de Qdrant, por si el payload no
   se ha actualizado todavía tras un cambio de permisos o un borrado.
"""
from dataclasses import dataclass

from flask import g, has_request_context
from sqlalchemy import String, cast, or_

from ..extensions import db
from ..models import Document, User

OPERATIONS_APP = "operations"


@dataclass(frozen=True)
class Viewer:
    user_id: int | None
    role: str | None  # rol en la app de operaciones
    manage: bool = False

    @classmethod
    def system(cls) -> "Viewer":
        return cls(None, None, True)

    @classmethod
    def for_user(cls, user_id: int | None) -> "Viewer":
        """Desde una tarea en segundo plano: permisos leídos de la BD."""
        from ..security.context import resolve_role

        user = db.session.get(User, user_id) if user_id else None
        if user is None or not user.is_active:
            return cls(user_id, None, False)
        role = resolve_role(user, OPERATIONS_APP)
        if role is None:
            return cls(user.id, None, False)
        manage = role["is_admin"] or "manage" in role["permissions"].get("documents", [])
        return cls(user.id, role["role"], bool(manage))

    @classmethod
    def current(cls) -> "Viewer":
        ctx = g.get("security") if has_request_context() else None
        if ctx is None:
            return cls(None, None, False)
        if ctx.app_code == OPERATIONS_APP:
            return cls(ctx.user_id, ctx.role_code, ctx.can("documents", "manage"))
        return cls.for_user(ctx.user_id)

    def can_view(self, doc: Document) -> bool:
        if self.manage or not doc.allowed_roles:
            return True
        if self.user_id is not None and doc.created_by == self.user_id:
            return True
        return self.role is not None and self.role in doc.allowed_roles

    def sql_filter(self):
        """Condición SQL equivalente a ``can_view`` (None = sin restricción)."""
        if self.manage:
            return None
        conditions = [Document.allowed_roles.is_(None)]
        if self.user_id is not None:
            conditions.append(Document.created_by == self.user_id)
        if self.role:
            # Los códigos de rol son [a-z_]: se escapa el comodín "_" de LIKE
            escaped = self.role.replace("_", "\\_")
            conditions.append(cast(Document.allowed_roles, String).like(f'%"{escaped}"%', escape="\\"))
        return or_(*conditions)

    def qdrant_access(self) -> dict:
        if self.manage:
            return {"bypass": True}
        return {"user_id": self.user_id, "roles": [self.role] if self.role else []}


def payload_roles(doc: Document) -> list[str]:
    return list(doc.allowed_roles) if doc.allowed_roles else ["*"]
