"""Portal Low-Code (app ``automation``, ADR-020, fases L1 y L2).

Solo dentro de la app automation (``X-App-Code: automation``).

- Estado de la conexión con n8n (``automations.read``); el enlace al editor solo se da a
  quien construye (``automations.build``).
- Catálogo de solo lectura: los flujos de n8n con la etiqueta del catálogo.
- Ejecuciones (L2): lanzar un flujo (``automations.run``) y seguirlo. Cada persona ve las
  suyas; ``automations.manage`` ve todas.
- Respuesta de n8n (``/runs/<id>/callback``): sin sesión de persona, con la clave de
  integración ``N8N_CALLBACK_KEY`` en ``X-Platia-Integration-Key``.
"""
import hmac

from flask import Blueprint, current_app, g, jsonify, request

from ..api.common import MAX_SEARCH_LENGTH, page_args, paginate, parse_body
from ..api.schemas import AutomationCallbackIn, AutomationRunIn
from ..errors import ForbiddenError, NotFoundError
from ..extensions import db
from ..models import AuditAction, AutomationRun
from ..queue import enqueue
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


# ---------------------------------------------------------------- Ejecuciones (fase L2)
def _visible_runs():
    stmt = AutomationRun.select_active()
    if not g.security.can("automations", "manage"):
        stmt = stmt.where(AutomationRun.created_by == g.security.user_id)
    return stmt


def _get_run(run_id: int) -> AutomationRun:
    run = db.session.scalar(_visible_runs().where(AutomationRun.id == run_id))
    if run is None:
        raise NotFoundError("Ejecución no encontrada.")
    return run


@automation_bp.post("/runs")
@platform_guard
@_automation_app_only
@require_permission("automations", "run")
@rate_limit("RATE_LIMIT_WRITE")
def launch():
    from ..tasks.automation import run as run_task

    data = parse_body(AutomationRunIn)
    run = service.launch(data.workflow_id, data.input, g.security.user_id)
    db.session.commit()
    audit(AuditAction.RECORD_CREATED, user_id=g.security.user_id, resource_type="automation_run",
          resource_id=run.id, details={"workflow_id": run.workflow_id})
    enqueue(run_task, run.id)
    db.session.refresh(run)
    return jsonify(service.run_dict(run, full=True)), 202


@automation_bp.get("/runs")
@platform_guard
@_automation_app_only
@require_permission("automations", "read")
@rate_limit("RATE_LIMIT_READ")
def list_runs():
    stmt = _visible_runs()
    if (status := request.args.get("status")) in AutomationRun.STATUSES:
        stmt = stmt.where(AutomationRun.status == status)
    if workflow_id := (request.args.get("workflow_id") or "").strip()[:64]:
        stmt = stmt.where(AutomationRun.workflow_id == workflow_id)
    if request.args.get("mine") == "true":
        stmt = stmt.where(AutomationRun.created_by == g.security.user_id)
    stmt = stmt.order_by(AutomationRun.created_at.desc(), AutomationRun.id.desc())
    return jsonify(paginate(stmt, service.run_dict))


@automation_bp.get("/runs/<int:run_id>")
@platform_guard
@_automation_app_only
@require_permission("automations", "read")
@rate_limit("RATE_LIMIT_READ")
def get_run(run_id: int):
    return jsonify(service.run_dict(_get_run(run_id), full=True))


@automation_bp.post("/runs/<int:run_id>/callback")
@rate_limit("RATE_LIMIT_WRITE", scope="ip")
def callback(run_id: int):
    expected = current_app.config.get("N8N_CALLBACK_KEY") or ""
    given = request.headers.get("X-Platia-Integration-Key") or ""
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        audit(AuditAction.ACCESS_DENIED, "WARNING", details={"path": request.path, "reason": "integration_key"})
        return jsonify(error="Autenticación requerida."), 401
    data = parse_body(AutomationCallbackIn)
    run = service.complete(run_id, data.status, data.result, data.error)
    db.session.commit()
    return jsonify({"id": run.id, "status": run.status})
