"""Piezas que comparten todos los blueprints de negocio.

Contrato común de la API (Capítulo 7, coherencia entre módulos):
- Listados: ``{"items": [...], "pagination": {page, per_page, total, pages}}``.
- Fechas en ISO 8601 UTC con ``Z``.
- Cada recurso modificable devuelve ``version``; al modificarlo hay que enviarla.
- Errores: ``{"error": "...", "type": "..."}``.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, TypeVar

from flask import g, request
from pydantic import BaseModel

from ..errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from ..extensions import db
from ..models import AuditAction
from ..security.audit import audit

M = TypeVar("M", bound=BaseModel)
MAX_PER_PAGE = 100
MAX_SEARCH_LENGTH = 100


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="seconds") + "Z"


def money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def to_utc_naive(value: datetime | None) -> datetime | None:
    """Todas las fechas se guardan en UTC sin zona (Capítulo 9: normalizar en la entrada)."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def parse_body(schema: type[M]) -> M:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("El cuerpo de la petición debe ser un objeto JSON.")
    return schema.model_validate(data)


def page_args() -> tuple[int, int]:
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(MAX_PER_PAGE, max(1, int(request.args.get("per_page", 20))))
    except ValueError as exc:
        raise ValidationError("page y per_page deben ser números.") from exc
    return page, per_page


def paginate(stmt, serializer: Callable[[Any], dict]) -> dict:
    page, per_page = page_args()
    result = db.paginate(stmt, page=page, per_page=per_page, error_out=False, max_per_page=MAX_PER_PAGE)
    return {
        "items": [serializer(item) for item in result.items],
        "pagination": {"page": page, "per_page": per_page, "total": result.total,
                       "pages": result.pages},
    }


def like_pattern(text: str | None) -> str | None:
    """Patrón LIKE seguro: escapa los comodines del usuario y limita la longitud."""
    if not text:
        return None
    text = text.strip()[:MAX_SEARCH_LENGTH]
    if not text:
        return None
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def get_active(model, object_id: int, label: str = "Recurso"):
    obj = db.session.get(model, object_id)
    if obj is None or not getattr(obj, "is_active", True):
        raise NotFoundError(f"{label} no encontrado.")
    return obj


def check_version(obj, version: int | None) -> None:
    """Bloqueo optimista: la versión enviada debe ser la actual."""
    if version is None:
        raise ValidationError("Falta 'version': envía la versión que leíste del recurso.")
    if version != obj.row_version:
        raise ConflictError(
            "Otra persona ha modificado este registro. Recarga y vuelve a aplicar tus cambios.",
            current_version=obj.row_version,
        )


def owner_of(obj) -> int | None:
    owner = getattr(obj, "owner_user_id", None)
    return owner if owner is not None else getattr(obj, "created_by", None)


def ensure_can_modify(module: str, obj, owner_id: int | None = None) -> None:
    """Autorización por objeto (IDOR, Capítulo 7): tener permiso de escritura en el
    módulo no basta. Hay que ser el responsable del registro o tener ``manage``."""
    ctx = g.security
    if ctx.can(module, "manage"):
        return
    owner = owner_id if owner_id is not None else owner_of(obj)
    if owner is not None and owner == ctx.user_id:
        return
    audit(AuditAction.ACCESS_DENIED, "WARNING", user_id=ctx.user_id,
          resource_type=type(obj).__tablename__, resource_id=getattr(obj, "id", None),
          details={"path": request.path, "reason": "not_owner", "module": module})
    raise ForbiddenError("Solo el responsable del registro o un gestor puede modificarlo.")


def record_audit(action: str, obj, **details) -> None:
    audit(action, "INFO", user_id=g.security.user_id, resource_type=type(obj).__tablename__,
          resource_id=getattr(obj, "id", None), details=details or None)


def apply_changes(obj, changes: dict, required: tuple[str, ...] = ()) -> list[str]:
    """Aplica los campos enviados y devuelve los nombres de los que cambiaron.
    ``required`` son los campos que no se pueden vaciar con null."""
    nulls = [f for f in required if f in changes and changes[f] is None]
    if nulls:
        raise ValidationError(f"Estos campos no pueden quedar vacíos: {', '.join(nulls)}.")
    changed = []
    for field, value in changes.items():
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed.append(field)
    return changed
