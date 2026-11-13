"""Reglas de reparto de oportunidades (caso P18 del portal Low-Code, ADR-020).

Las gestiona quien tiene ``opportunities.manage`` en operaciones. Las aplica
``tasks.alerts.proactive_scan`` a las oportunidades que llegan sin responsable.
"""
from flask import Blueprint, g, jsonify

from ..api.common import check_version, get_active, parse_body, record_audit
from ..api.schemas import RoutingRuleIn, RoutingRulePatch
from ..errors import ValidationError
from ..extensions import db
from ..models import AuditAction, OpportunityRoutingRule
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit
from ..services import routing as service

routing_bp = Blueprint("routing", __name__, url_prefix="/api/opportunities/routing-rules")


def _check_owner(owner_user_id: int) -> None:
    if owner_user_id not in {c["id"] for c in service.candidates()}:
        raise ValidationError("La persona responsable debe poder trabajar oportunidades en operaciones.")


def _payload(rules: list[OpportunityRoutingRule]) -> list[dict]:
    names = service.owner_names({r.owner_user_id for r in rules})
    return [service.rule_dict(r, names) for r in rules]


@routing_bp.get("")
@platform_guard
@require_permission("opportunities", "manage")
@rate_limit("RATE_LIMIT_READ")
def list_rules():
    rules = list(db.session.scalars(OpportunityRoutingRule.select_active().order_by(
        OpportunityRoutingRule.position, OpportunityRoutingRule.id)))
    return jsonify({"items": _payload(rules), "candidates": service.candidates(),
                    "pagination": {"page": 1, "per_page": len(rules), "total": len(rules), "pages": 1}})


@routing_bp.post("")
@platform_guard
@require_permission("opportunities", "manage")
@rate_limit("RATE_LIMIT_WRITE")
def create_rule():
    data = parse_body(RoutingRuleIn)
    _check_owner(data.owner_user_id)
    rule = OpportunityRoutingRule(**data.model_dump(), created_by=g.security.user_id)
    db.session.add(rule)
    db.session.commit()
    record_audit(AuditAction.RECORD_CREATED, rule)
    return jsonify(_payload([rule])[0]), 201


@routing_bp.put("/<int:rule_id>")
@platform_guard
@require_permission("opportunities", "manage")
@rate_limit("RATE_LIMIT_WRITE")
def update_rule(rule_id: int):
    rule = get_active(OpportunityRoutingRule, rule_id, "Regla")
    data = parse_body(RoutingRulePatch)
    check_version(rule, data.version)
    if data.owner_user_id != rule.owner_user_id:
        _check_owner(data.owner_user_id)
    for field, value in data.model_dump(exclude={"version"}).items():
        setattr(rule, field, value)
    db.session.commit()
    record_audit(AuditAction.RECORD_UPDATED, rule)
    return jsonify(_payload([rule])[0])


@routing_bp.delete("/<int:rule_id>")
@platform_guard
@require_permission("opportunities", "manage")
@rate_limit("RATE_LIMIT_WRITE")
def delete_rule(rule_id: int):
    rule = get_active(OpportunityRoutingRule, rule_id, "Regla")
    rule.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, rule)
    return "", 204
