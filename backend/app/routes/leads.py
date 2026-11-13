"""Solicitudes del formulario web (caso P2 del portal Low-Code, ADR-020).

- ``POST /api/leads/inbound``: la entrega n8n, sin sesión de persona, con la clave de
  integración ``N8N_CALLBACK_KEY`` en ``X-Platia-Integration-Key``. Solo guarda y avisa.
- Listado, detalle y resolución en la app de operaciones (``leads.read`` y ``leads.manage``).
"""
from flask import Blueprint, g, jsonify, request

from ..api.common import check_version, get_active, paginate, parse_body, record_audit
from ..api.schemas import InboundLeadIn, LeadResolveIn
from ..extensions import db
from ..models import AuditAction, InboundLead
from ..security.audit import audit
from ..security.integration import integration_key_ok
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit
from ..services import leads as service

leads_bp = Blueprint("leads", __name__, url_prefix="/api/leads")


@leads_bp.post("/inbound")
@rate_limit("RATE_LIMIT_WRITE", scope="ip")
def inbound():
    if not integration_key_ok():
        return jsonify(error="Autenticación requerida."), 401
    data = parse_body(InboundLeadIn).model_dump()
    lead, created = service.receive(data)
    db.session.commit()
    if created:
        audit(AuditAction.RECORD_CREATED, resource_type="inbound_lead", resource_id=lead.id,
              details={"source": lead.source, "workflow_id": lead.workflow_id})
    return jsonify({"id": lead.id, "status": lead.status, "duplicate": not created}), 201 if created else 200


@leads_bp.get("")
@platform_guard
@require_permission("leads", "read")
@rate_limit("RATE_LIMIT_READ")
def list_leads():
    stmt = InboundLead.select_active()
    if (status := request.args.get("status")) in InboundLead.STATUSES:
        stmt = stmt.where(InboundLead.status == status)
    return jsonify(paginate(stmt.order_by(InboundLead.created_at.desc(), InboundLead.id.desc()),
                            service.lead_dict))


@leads_bp.get("/<int:lead_id>")
@platform_guard
@require_permission("leads", "read")
@rate_limit("RATE_LIMIT_READ")
def get_lead(lead_id: int):
    return jsonify(service.lead_dict(get_active(InboundLead, lead_id, "Solicitud"), full=True))


@leads_bp.post("/<int:lead_id>/resolve")
@platform_guard
@require_permission("leads", "manage")
@rate_limit("RATE_LIMIT_WRITE")
def resolve_lead(lead_id: int):
    lead = get_active(InboundLead, lead_id, "Solicitud")
    data = parse_body(LeadResolveIn)
    check_version(lead, data.version)
    try:
        service.resolve(lead, data.action, g.security.user_id, g.security.can, client_id=data.client_id,
                        new_client_name=data.new_client_name, opportunity_title=data.opportunity_title,
                        note=data.note)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    record_audit(AuditAction.RECORD_UPDATED, lead, step=data.action, client_id=lead.client_id,
                 opportunity_id=lead.opportunity_id)
    return jsonify(service.lead_dict(lead, full=True))
