"""Retorno de la inversión de la IA (Capítulo 11).

Cada tarea completada con IA deja una fila en ``task_completion_log`` con su
coste en tokens y el tiempo que habría tardado una persona (tabla editable
``human_baseline_config``). Los costes de los modelos están en USD y el ahorro
en EUR: el tipo de cambio es configurable (``AI_USD_EUR_RATE``).
"""
from datetime import datetime
from decimal import Decimal

import structlog
from flask import current_app

from ..extensions import db
from ..models import HumanBaselineConfig, TaskCompletionLog, utcnow

log = structlog.get_logger(__name__)


def usd_to_eur(amount: Decimal) -> Decimal:
    return amount * Decimal(str(current_app.config.get("AI_USD_EUR_RATE", 0.92)))


def record(service_type: str, *, subject_type: str | None, subject_id: int | None, user_id: int | None,
           correlation_id: str | None, duration_seconds: float, cost_usd: Decimal,
           quality_score: float | None = None) -> TaskCompletionLog:
    """Registra una tarea completada. No hace commit."""
    base = db.session.get(HumanBaselineConfig, service_type)
    saved_minutes = money_saved = None
    if base is not None:
        saved_minutes = max(0.0, base.human_time_minutes - duration_seconds / 60)
        human_cost = Decimal(str(saved_minutes / 60)) * Decimal(base.human_hourly_cost_eur)
        money_saved = (human_cost - usd_to_eur(cost_usd)).quantize(Decimal("0.01"))
    row = TaskCompletionLog(
        service_type=service_type, subject_type=subject_type, subject_id=subject_id, user_id=user_id,
        correlation_id=correlation_id, ai_duration_seconds=round(duration_seconds, 2), llm_cost_usd=cost_usd,
        human_time_baseline_minutes=base.human_time_minutes if base else None,
        time_saved_minutes=None if saved_minutes is None else round(saved_minutes, 2),
        money_saved_eur=money_saved, quality_score=quality_score,
    )
    db.session.add(row)
    return row


def summary(since: datetime, until: datetime | None = None) -> dict:
    until = until or utcnow()
    rows = db.session.execute(
        db.select(TaskCompletionLog.service_type, db.func.count(), db.func.sum(TaskCompletionLog.llm_cost_usd),
                  db.func.sum(TaskCompletionLog.time_saved_minutes), db.func.sum(TaskCompletionLog.money_saved_eur),
                  db.func.avg(TaskCompletionLog.user_rating))
        .where(TaskCompletionLog.created_at >= since, TaskCompletionLog.created_at < until)
        .group_by(TaskCompletionLog.service_type)
    ).all()
    services = []
    total_cost = total_saved = Decimal(0)
    total_minutes = 0.0
    for service_type, count, cost, minutes, saved, rating in rows:
        cost_eur = usd_to_eur(Decimal(str(cost or 0)))
        saved = Decimal(str(saved or 0))
        services.append({
            "service_type": service_type, "tasks": count, "cost_eur": f"{cost_eur:.2f}",
            "hours_saved": round((minutes or 0) / 60, 1), "net_saving_eur": f"{saved:.2f}",
            "roi_pct": round(float(saved / cost_eur * 100), 0) if cost_eur else None,
            "avg_user_rating": round(float(rating), 2) if rating is not None else None,
        })
        total_cost += cost_eur
        total_saved += saved
        total_minutes += minutes or 0
    return {
        "from": since.isoformat(timespec="seconds") + "Z", "to": until.isoformat(timespec="seconds") + "Z",
        "services": services,
        "total": {"tasks": sum(s["tasks"] for s in services), "cost_eur": f"{total_cost:.2f}",
                  "hours_saved": round(total_minutes / 60, 1), "net_saving_eur": f"{total_saved:.2f}",
                  "roi_pct": round(float(total_saved / total_cost * 100), 0) if total_cost else None},
    }
