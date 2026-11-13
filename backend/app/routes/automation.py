"""Portal Low-Code (app ``automation``, ADR-020, fases L1 y L2).

Solo dentro de la app automation (``X-App-Code: automation``).

- Estado de la conexión con n8n (``automations.read``); el enlace al editor solo se da a
  quien construye (``automations.build``).
- Catálogo: las fichas publicadas, con el estado del flujo en n8n.
- Taller (L3, ``automations.build``): flujos candidatos de n8n, fichas, comprobaciones y
  envío a revisión; publicar, devolver y retirar, con ``automations.manage``.
- Ejecuciones (L2): lanzar un flujo (``automations.run``) y seguirlo. Cada persona ve las
  suyas; ``automations.manage`` ve todas.
- Respuesta de n8n (``/runs/<id>/callback``): sin sesión de persona, con la clave de
  integración ``N8N_CALLBACK_KEY`` en ``X-Platia-Integration-Key``.
- Monitorización (L4): el flujo de errores común entrega los fallos en
  ``/incidents/inbound`` (misma clave de integración); quien construye ve incidencias y salud
  (``automations.build``) y quien administra las resuelve (``automations.manage``).
"""

from flask import Blueprint, g, jsonify, request

from ..api.common import MAX_SEARCH_LENGTH, check_version, page_args, paginate, parse_body
from ..api.schemas import (AutomationCallbackIn, AutomationEntryIn, AutomationEntryPatch, AutomationIncidentIn,
                           AutomationIncidentResolveIn, AutomationReviewIn, AutomationRunIn, Versioned)
from ..errors import BusinessRuleError, ForbiddenError, NotFoundError
from ..extensions import db
from ..models import AuditAction, AutomationEntry, AutomationIncident, AutomationRun
from ..queue import enqueue
from ..security.audit import audit
from ..security.context import platform_guard, require_permission
from ..security.integration import integration_key_ok
from ..security.ratelimit import rate_limit
from ..services import automation as service
from ..services import automation_incidents as incidents

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
    items, source = service.published_catalog()
    can_build = g.security.can("automations", "build")
    return jsonify({
        **_source(source),
        "published": len(items),
        "active": sum(1 for w in items if w["active"]),
        "candidates": len(source.workflows) if can_build else None,
        "editor_url": service.editor_url() if can_build else None,
    })


@automation_bp.get("/catalog")
@platform_guard
@_automation_app_only
@require_permission("automations", "read")
@rate_limit("RATE_LIMIT_READ")
def catalog():
    page, per_page = page_args()
    q = (request.args.get("q") or "").strip()[:MAX_SEARCH_LENGTH]
    items, source = service.published_catalog(q, request.args.get("category") or "")
    if request.args.get("active") in ("true", "false"):
        items = [w for w in items if w["active"] == (request.args["active"] == "true")]
    total = len(items)
    start = (page - 1) * per_page
    return jsonify({
        "items": items[start:start + per_page],
        "pagination": {"page": page, "per_page": per_page, "total": total,
                       "pages": (total + per_page - 1) // per_page},
        "source": _source(source),
    })


# ---------------------------------------------------------------- Taller (fase L3)
def _get_entry(entry_id: int) -> AutomationEntry:
    entry = db.session.scalar(AutomationEntry.select_active().where(AutomationEntry.id == entry_id))
    if entry is None:
        raise NotFoundError("Ficha no encontrada.")
    return entry


def _audit_entry(entry: AutomationEntry, audit_action: str, **details) -> None:
    audit(audit_action, user_id=g.security.user_id, resource_type="automation_entry", resource_id=entry.id,
          details={"workflow_id": entry.workflow_id, "status": entry.status, **details})


@automation_bp.get("/workflows")
@platform_guard
@_automation_app_only
@require_permission("automations", "build")
@rate_limit("RATE_LIMIT_READ")
def workflows():
    """Flujos de n8n con la etiqueta del catálogo, con la ficha que ya tengan."""
    data = service.fetch_catalog()
    taken = {e.workflow_id: e for e in db.session.scalars(
        AutomationEntry.select_active().where(AutomationEntry.status != "retired"))}
    items = [{**w, "entry_id": taken[w["id"]].id if w["id"] in taken else None} for w in data.workflows]
    return jsonify({"items": items, "source": _source(data)})


@automation_bp.get("/entries")
@platform_guard
@_automation_app_only
@require_permission("automations", "build")
@rate_limit("RATE_LIMIT_READ")
def list_entries():
    stmt = AutomationEntry.select_active()
    if (status := request.args.get("status")) in AutomationEntry.STATUSES:
        stmt = stmt.where(AutomationEntry.status == status)
    return jsonify(paginate(stmt.order_by(AutomationEntry.updated_at.desc(), AutomationEntry.id.desc()),
                            service.entry_dict))


@automation_bp.post("/entries")
@platform_guard
@_automation_app_only
@require_permission("automations", "build")
@rate_limit("RATE_LIMIT_WRITE")
def create_entry():
    data = parse_body(AutomationEntryIn).model_dump()
    entry = service.create_entry(data, g.security.user_id)
    db.session.commit()
    _audit_entry(entry, AuditAction.RECORD_CREATED)
    return jsonify(service.entry_dict(entry)), 201


@automation_bp.get("/entries/<int:entry_id>")
@platform_guard
@_automation_app_only
@require_permission("automations", "build")
@rate_limit("RATE_LIMIT_READ")
def get_entry(entry_id: int):
    entry = _get_entry(entry_id)
    return jsonify({**service.entry_dict(entry), "input_names": service.workflow_inputs(entry)})


@automation_bp.patch("/entries/<int:entry_id>")
@platform_guard
@_automation_app_only
@require_permission("automations", "build")
@rate_limit("RATE_LIMIT_WRITE")
def update_entry(entry_id: int):
    entry = _get_entry(entry_id)
    data = parse_body(AutomationEntryPatch)
    check_version(entry, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    service.update_entry(entry, changes)
    db.session.commit()
    _audit_entry(entry, AuditAction.RECORD_UPDATED, fields=sorted(changes))
    return jsonify(service.entry_dict(entry))


@automation_bp.post("/entries/<int:entry_id>/check")
@platform_guard
@_automation_app_only
@require_permission("automations", "build")
@rate_limit("RATE_LIMIT_WRITE")
def check_entry(entry_id: int):
    entry = _get_entry(entry_id)
    service.check_entry(entry)
    db.session.commit()
    return jsonify(service.entry_dict(entry))


@automation_bp.post("/entries/<int:entry_id>/submit")
@platform_guard
@_automation_app_only
@require_permission("automations", "build")
@rate_limit("RATE_LIMIT_WRITE")
def submit_entry(entry_id: int):
    entry = _get_entry(entry_id)
    check_version(entry, parse_body(Versioned).version)
    try:
        service.submit_entry(entry, g.security.user_id)
    except BusinessRuleError:
        db.session.commit()  # se guarda el resultado de las comprobaciones para enseñarlo
        raise
    db.session.commit()
    _audit_entry(entry, AuditAction.RECORD_UPDATED, step="submit")
    return jsonify(service.entry_dict(entry))


@automation_bp.post("/entries/<int:entry_id>/review")
@platform_guard
@_automation_app_only
@require_permission("automations", "manage")
@rate_limit("RATE_LIMIT_WRITE")
def review_entry(entry_id: int):
    entry = _get_entry(entry_id)
    data = parse_body(AutomationReviewIn)
    check_version(entry, data.version)
    try:
        service.review_entry(entry, data.decision == "approve", data.note, g.security.user_id)
    except BusinessRuleError:
        db.session.rollback()
        raise
    db.session.commit()
    _audit_entry(entry, AuditAction.RECORD_UPDATED, step=data.decision)
    return jsonify(service.entry_dict(entry))


@automation_bp.post("/entries/<int:entry_id>/retire")
@platform_guard
@_automation_app_only
@require_permission("automations", "manage")
@rate_limit("RATE_LIMIT_WRITE")
def retire_entry(entry_id: int):
    entry = _get_entry(entry_id)
    check_version(entry, parse_body(Versioned).version)
    service.retire_entry(entry)
    db.session.commit()
    _audit_entry(entry, AuditAction.RECORD_UPDATED, step="retire")
    return jsonify(service.entry_dict(entry))


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
    entry = db.session.scalar(AutomationEntry.select_active().where(AutomationEntry.id == data.entry_id))
    if entry is None:
        raise NotFoundError("Esa automatización no está publicada.")
    run = service.launch(entry, data.input, g.security.user_id)
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
    if not integration_key_ok():
        return jsonify(error="Autenticación requerida."), 401
    data = parse_body(AutomationCallbackIn)
    run = service.complete(run_id, data.status, data.result, data.error)
    db.session.commit()
    return jsonify({"id": run.id, "status": run.status})


# ---------------------------------------------------------------- Monitorización (fase L4)
@automation_bp.post("/incidents/inbound")
@rate_limit("RATE_LIMIT_WRITE", scope="ip")
def incident_inbound():
    if not integration_key_ok():
        return jsonify(error="Autenticación requerida."), 401
    incident, created = incidents.record(parse_body(AutomationIncidentIn).model_dump())
    db.session.commit()
    if created:
        audit(AuditAction.RECORD_CREATED, "WARNING", resource_type="automation_incident", resource_id=incident.id,
              details={"workflow_id": incident.workflow_id, "run_id": incident.run_id})
    return jsonify({"id": incident.id, "run_id": incident.run_id, "duplicate": not created}), 201 if created else 200


@automation_bp.get("/incidents")
@platform_guard
@_automation_app_only
@require_permission("automations", "build")
@rate_limit("RATE_LIMIT_READ")
def list_incidents():
    stmt = AutomationIncident.select_active()
    if (status := request.args.get("status")) in AutomationIncident.STATUSES:
        stmt = stmt.where(AutomationIncident.status == status)
    if workflow_id := (request.args.get("workflow_id") or "").strip()[:64]:
        stmt = stmt.where(AutomationIncident.workflow_id == workflow_id)
    stmt = stmt.order_by(AutomationIncident.created_at.desc(), AutomationIncident.id.desc())
    return jsonify(paginate(stmt, incidents.incident_dict))


@automation_bp.post("/incidents/<int:incident_id>/resolve")
@platform_guard
@_automation_app_only
@require_permission("automations", "manage")
@rate_limit("RATE_LIMIT_WRITE")
def resolve_incident(incident_id: int):
    incident = db.session.scalar(AutomationIncident.select_active().where(AutomationIncident.id == incident_id))
    if incident is None:
        raise NotFoundError("Incidencia no encontrada.")
    data = parse_body(AutomationIncidentResolveIn)
    check_version(incident, data.version)
    incidents.resolve(incident, g.security.user_id, data.note)
    db.session.commit()
    audit(AuditAction.RECORD_UPDATED, user_id=g.security.user_id, resource_type="automation_incident",
          resource_id=incident.id, details={"step": "resolve", "workflow_id": incident.workflow_id})
    return jsonify(incidents.incident_dict(incident))


@automation_bp.get("/health")
@platform_guard
@_automation_app_only
@require_permission("automations", "build")
@rate_limit("RATE_LIMIT_READ")
def workflow_health():
    try:
        days = min(max(int(request.args.get("days", 30)), 1), 365)
    except ValueError:
        days = 30
    items = incidents.health(days)
    return jsonify({"days": days, "items": items,
                    "open_incidents": sum(i["open_incidents"] for i in items)})
