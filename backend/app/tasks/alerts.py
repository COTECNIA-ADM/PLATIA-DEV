"""Alertas proactivas (cola ``priority``, Capítulo 9)."""
from datetime import timedelta

import structlog
from flask import current_app
from sqlalchemy import func

from ..extensions import db
from ..models import Alert, Opportunity, Proposal, ServiceLine, utcnow
from ..queue import PlatformTask, celery
from ..services import opportunities as opp_service
from ..services.notifications import notify, notify_many, operations_managers

log = structlog.get_logger(__name__)
OPEN_PROPOSAL_STATUSES = ("draft", "in_review", "approved", "sent")


@celery.task(name="tasks.alerts.proactive_scan", base=PlatformTask, bind=True)
def proactive_scan(self) -> dict:
    """Puntúa las oportunidades recientes y avisa de las que encajan con el portfolio."""
    threshold = current_app.config["ALERT_SCORE_THRESHOLD"]
    since = utcnow() - timedelta(hours=current_app.config["ALERT_LOOKBACK_HOURS"])
    lines = list(db.session.scalars(ServiceLine.select_active()))
    if not lines:
        return {"scored": 0, "alerts": 0, "reason": "sin líneas de servicio"}
    by_code = {line.code: line for line in lines}
    recent = db.session.scalars(
        Opportunity.select_active().where(
            Opportunity.status.in_(("detected", "qualifying")),
            func.coalesce(Opportunity.published_at, Opportunity.created_at) >= since,
        ).limit(1000)
    ).all()
    alerts = 0
    for opp in recent:
        best = opp_service.score_opportunity(opp, lines)
        if best is None or best["score"] < threshold:
            continue
        already = db.session.scalar(db.select(Alert.id).filter_by(
            alert_type="OPPORTUNITY_MATCH", opportunity_id=opp.id, is_active=True))
        if already:
            continue
        line = by_code[best["service_line"]]
        message = (f"La oportunidad «{opp.title[:200]}» encaja con {line.name} "
                   f"(puntuación {best['score']:.1f}/10).")
        db.session.add(Alert(alert_type="OPPORTUNITY_MATCH", opportunity_id=opp.id,
                             score=round(best["score"] * 10), message=message))
        recipients = [line.owner_user_id] if line.owner_user_id else operations_managers()
        notify_many(recipients, "OPPORTUNITY_MATCH", "Oportunidad relevante detectada", message,
                    link=f"/opportunities/{opp.id}", extra_data=best)
        alerts += 1
    db.session.commit()
    log.info("proactive_scan_done", scored=len(recent), alerts=alerts)
    return {"scored": len(recent), "alerts": alerts}


@celery.task(name="tasks.alerts.deal_stalled", base=PlatformTask, bind=True)
def deal_stalled(self) -> dict:
    """Avisa al responsable de cada propuesta abierta sin actividad en N días."""
    days = current_app.config["DEAL_STALLED_DAYS"]
    cutoff = utcnow() - timedelta(days=days)
    stalled = db.session.scalars(
        Proposal.select_active().where(Proposal.status.in_(OPEN_PROPOSAL_STATUSES),
                                       Proposal.updated_at < cutoff)
    ).all()
    sent = 0
    for proposal in stalled:
        owner = proposal.owner_user_id or proposal.created_by
        if owner is None:
            continue
        if notify(owner, "DEAL_STALLED", "Propuesta sin actividad",
                  f"«{proposal.title[:200]}» lleva más de {days} días sin cambios "
                  f"(estado: {proposal.status}).", link=f"/proposals/{proposal.id}", commit=False):
            sent += 1
    db.session.commit()
    return {"stalled": len(stalled), "notified": sent}
