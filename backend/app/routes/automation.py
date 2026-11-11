"""Portal Low-Code (app ``automation``, ADR-020, fase L1).

Solo dentro de la app automation (``X-App-Code: automation``).

- Estado de la conexión con n8n (``automations.read``); el enlace al editor solo se da a
  quien construye (``automations.build``).
- Catálogo de solo lectura: los flujos de n8n con la etiqueta del catálogo.
"""
from flask import Blueprint, g, jsonify, request

from ..api.common import MAX_SEARCH_LENGTH, page_args
from ..errors import ForbiddenError
from ..models import AuditAction
from ..security.audit import audit
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit
from ..services import automation as service

automation_bp = Blueprint("automation", __name__, url_prefix="/api/automation")


def _automation_app_only(fn):
    """Estas rutas solo existen dentro de la app automation."""
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.security.app_code != "automation":
            audit(AuditAction.ACCESS_DENIED, "WARNING", user_id=g.security.user_id,
                  details={"path": request.path, "app": g.security.app_code})
            raise ForbiddenError("Usa la aplicación automation (cabecera X-App-Code: automation).")
        return fn(*args, **kwargs)

    return wrapper


def _source(catalog: service.Catalog) -> dict:
    return {"enabled": catalog.enabled, "reachable": catalog.reachable, "problem": catalog.problem}


@automation_bp.get("/status")
@platform_guard
@_automation_app_only
@require_permission("automations", "read")
@rate_limit("RATE_LIMIT_READ")
def status():
    catalog = service.fetch_catalog()
    can_build = g.security.can("automations", "build")
    return jsonify({
        **_source(catalog),
        "published": len(catalog.workflows),
        "active": sum(1 for w in catalog.workflows if w["active"]),
        "editor_url": service.editor_url() if can_build else None,
    })


@automation_bp.get("/catalog")
@platform_guard
@_automation_app_only
@require_permission("automations", "read")
@rate_limit("RATE_LIMIT_READ")
def catalog():
    page, per_page = page_args()
    data = service.fetch_catalog()
    items = data.workflows
    if needle := (request.args.get("q") or "").strip()[:MAX_SEARCH_LENGTH].lower():
        items = [w for w in items if needle in w["name"].lower() or any(needle in t.lower() for t in w["tags"])]
    if request.args.get("active") in ("true", "false"):
        items = [w for w in items if w["active"] == (request.args["active"] == "true")]
    total = len(items)
    start = (page - 1) * per_page
    return jsonify({
        "items": items[start:start + per_page],
        "pagination": {"page": page, "per_page": per_page, "total": total,
                       "pages": (total + per_page - 1) // per_page},
        "source": _source(data),
    })
