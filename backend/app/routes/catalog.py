"""Plantillas de propuesta y portfolio de líneas de servicio."""
from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..api.common import apply_changes, check_version, get_active, iso, paginate, parse_body, record_audit
from ..api.schemas import ServiceLineIn, ServiceLinePatch, TemplateIn, TemplatePatch
from ..errors import ConflictError
from ..extensions import db
from ..models import AuditAction, ProposalTemplate, ServiceLine
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit

catalog_bp = Blueprint("catalog", __name__, url_prefix="/api")


def template_dict(t: ProposalTemplate) -> dict:
    return {"id": t.id, "name": t.name, "proposal_type": t.proposal_type,
            "description": t.description, "sections": t.sections, "version": t.row_version,
            "updated_at": iso(t.updated_at)}


def line_dict(s: ServiceLine) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "description": s.description,
            "keywords": s.keywords, "cpv_prefixes": s.cpv_prefixes,
            "owner_user_id": s.owner_user_id, "version": s.row_version}


@catalog_bp.get("/proposal-templates")
@platform_guard
@require_permission("templates", "read")
@rate_limit("RATE_LIMIT_READ")
def list_templates():
    stmt = ProposalTemplate.select_active().order_by(ProposalTemplate.proposal_type, ProposalTemplate.name)
    if ptype := request.args.get("proposal_type"):
        stmt = stmt.where(ProposalTemplate.proposal_type == ptype)
    return jsonify(paginate(stmt, template_dict))


@catalog_bp.post("/proposal-templates")
@platform_guard
@require_permission("templates", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_template():
    data = parse_body(TemplateIn)
    values = data.model_dump()
    template = ProposalTemplate(**values, created_by=g.security.user_id)
    db.session.add(template)
    db.session.commit()
    record_audit(AuditAction.RECORD_CREATED, template)
    return jsonify(template_dict(template)), 201


@catalog_bp.get("/proposal-templates/<int:template_id>")
@platform_guard
@require_permission("templates", "read")
@rate_limit("RATE_LIMIT_READ")
def get_template(template_id: int):
    return jsonify(template_dict(get_active(ProposalTemplate, template_id, "Plantilla")))


@catalog_bp.patch("/proposal-templates/<int:template_id>")
@platform_guard
@require_permission("templates", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_template(template_id: int):
    template = get_active(ProposalTemplate, template_id, "Plantilla")
    data = parse_body(TemplatePatch)
    check_version(template, data.version)
    changed = apply_changes(template, data.model_dump(exclude_unset=True, exclude={"version"}),
                            required=("name", "sections"))
    db.session.commit()
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, template, fields=changed)
    return jsonify(template_dict(template))


@catalog_bp.delete("/proposal-templates/<int:template_id>")
@platform_guard
@require_permission("templates", "write")
@rate_limit("RATE_LIMIT_WRITE")
def delete_template(template_id: int):
    template = get_active(ProposalTemplate, template_id, "Plantilla")
    template.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, template)
    return "", 204


# ------------------------------------------------------------------ Portfolio
@catalog_bp.get("/portfolio/service-lines")
@platform_guard
@require_permission("portfolio", "read")
@rate_limit("RATE_LIMIT_READ")
def list_service_lines():
    return jsonify(paginate(ServiceLine.select_active().order_by(ServiceLine.name), line_dict))


@catalog_bp.post("/portfolio/service-lines")
@platform_guard
@require_permission("portfolio", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_service_line():
    data = parse_body(ServiceLineIn)
    line = ServiceLine(**data.model_dump(), created_by=g.security.user_id)
    db.session.add(line)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ConflictError("Ya existe una línea con ese código.") from exc
    record_audit(AuditAction.RECORD_CREATED, line)
    return jsonify(line_dict(line)), 201


@catalog_bp.patch("/portfolio/service-lines/<int:line_id>")
@platform_guard
@require_permission("portfolio", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_service_line(line_id: int):
    line = get_active(ServiceLine, line_id, "Línea de servicio")
    data = parse_body(ServiceLinePatch)
    check_version(line, data.version)
    changed = apply_changes(line, data.model_dump(exclude_unset=True, exclude={"version"}),
                            required=("name", "keywords", "cpv_prefixes"))
    db.session.commit()
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, line, fields=changed)
    return jsonify(line_dict(line))
