"""Reparto de oportunidades al responsable (caso P18 del portal Low-Code, ADR-020).

Las oportunidades que llegan solas (feeds ATOM, TED, buzón de pliegos) se crean sin
responsable. Después de puntuarlas (que les pone la línea de servicio), se recorren las reglas
activas por orden y se aplica la primera que encaje: asigna el responsable, deja constancia en
``extra_data["routing"]`` y le avisa. Una oportunidad con responsable nunca se reasigna.

La lógica vive aquí y no en n8n: es una regla de negocio sobre datos de PLATIA.
"""
from datetime import datetime

import structlog

from ..api.common import iso, money
from ..extensions import db
from ..models import Opportunity, OpportunityRoutingRule, User, utcnow
from . import notifications

log = structlog.get_logger(__name__)


def rule_dict(rule: OpportunityRoutingRule, names: dict[int, str] | None = None) -> dict:
    return {
        "id": rule.id, "name": rule.name, "position": rule.position, "is_enabled": rule.is_enabled,
        "sources": rule.sources or [], "service_lines": rule.service_lines or [], "sectors": rule.sectors or [],
        "min_value_eur": money(rule.min_value_eur), "max_value_eur": money(rule.max_value_eur),
        "max_days_to_deadline": rule.max_days_to_deadline, "owner_user_id": rule.owner_user_id,
        "owner_name": (names or {}).get(rule.owner_user_id), "created_at": iso(rule.created_at),
        "updated_at": iso(rule.updated_at), "version": rule.row_version,
    }


def active_rules() -> list[OpportunityRoutingRule]:
    return list(db.session.scalars(OpportunityRoutingRule.select_active().where(
        OpportunityRoutingRule.is_enabled.is_(True)).order_by(OpportunityRoutingRule.position,
                                                              OpportunityRoutingRule.id)))


def _in(values: list | None, value: str | None) -> bool:
    if not values:
        return True
    return value is not None and value.casefold() in {v.casefold() for v in values}


def matches(rule: OpportunityRoutingRule, opp: Opportunity, now: datetime | None = None) -> bool:
    """Todos los criterios con valor deben cumplirse; si la regla pide importe o plazo y la
    oportunidad no lo tiene, no encaja."""
    if not (_in(rule.sources, opp.source) and _in(rule.service_lines, opp.service_line)
            and _in(rule.sectors, opp.sector)):
        return False
    value = opp.estimated_value_eur
    if rule.min_value_eur is not None and (value is None or value < rule.min_value_eur):
        return False
    if rule.max_value_eur is not None and (value is None or value > rule.max_value_eur):
        return False
    if rule.max_days_to_deadline is not None:
        if opp.deadline is None:
            return False
        if (opp.deadline - (now or utcnow())).total_seconds() > rule.max_days_to_deadline * 86400:
            return False
    return True


def _owner_active(user_id: int) -> bool:
    user = db.session.get(User, user_id)
    return user is not None and user.is_active


def route(opp: Opportunity, rules: list[OpportunityRoutingRule] | None = None) -> OpportunityRoutingRule | None:
    """Asigna el responsable con la primera regla que encaje. No hace commit."""
    if opp.owner_user_id is not None or opp.status not in ("detected", "qualifying"):
        return None
    now = utcnow()
    for rule in active_rules() if rules is None else rules:
        if not matches(rule, opp, now):
            continue
        if not _owner_active(rule.owner_user_id):
            log.warning("routing_owner_inactive", rule_id=rule.id)
            continue
        opp.owner_user_id = rule.owner_user_id
        opp.extra_data = {**(opp.extra_data or {}), "routing": {"rule_id": rule.id, "rule_name": rule.name,
                                                                 "at": iso(now)}}
        notifications.notify(rule.owner_user_id, "NEW_OPPORTUNITY", "Te han asignado una oportunidad",
                             f"«{opp.title[:200]}» (regla «{rule.name[:100]}»).", link=f"/opportunities/{opp.id}",
                             extra_data={"rule_id": rule.id}, commit=False)
        log.info("opportunity_routed", opportunity_id=opp.id, rule_id=rule.id)
        return rule
    return None


def candidates() -> list[dict]:
    """Personas a las que se puede asignar: quien puede escribir oportunidades en operaciones."""
    ids = notifications.holders_of("operations", "opportunities", "write")
    users = db.session.scalars(db.select(User).where(User.id.in_(ids), User.is_active.is_(True))
                               .order_by(User.full_name)).all() if ids else []
    return [{"id": u.id, "name": u.full_name} for u in users]


def owner_names(ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return dict(db.session.execute(db.select(User.id, User.full_name).where(User.id.in_(ids))).all())
