"""Presupuestos de IA con acciones graduadas: aviso -> frenado -> bloqueo (Capítulo 11).

Antes de cada llamada se compara lo gastado hoy y este mes con los límites que
aplican (global, del servicio y del usuario):

- al llegar al umbral de aviso (80 % por defecto) se avisa a los superadmins una
  vez al día;
- al de frenado (95 %) cada llamada espera unos segundos, para que un bucle o
  un uso anómalo no agote el resto del presupuesto en minutos;
- al de bloqueo (100 %) la llamada se rechaza con un error claro.

La progresión es intencionada: un servicio en producción no debe pararse de
golpe sin que nadie haya recibido antes un aviso.
"""
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import structlog
from flask import current_app

from ..extensions import db
from ..models import AuditAction, BudgetConfig, LLMUsageLog, utcnow
from ..security.audit import audit
from .errors import BudgetExceededError

log = structlog.get_logger(__name__)


@dataclass
class BudgetStatus:
    budget: BudgetConfig
    period: str
    limit: Decimal
    spent: Decimal

    @property
    def pct(self) -> float:
        return float(self.spent / self.limit * 100) if self.limit else 0.0

    def to_dict(self) -> dict:
        return {"budget_id": self.budget.id, "scope": self.budget.scope, "scope_id": self.budget.scope_id,
                "period": self.period, "limit_usd": f"{self.limit:.2f}", "spent_usd": f"{self.spent:.4f}",
                "pct": round(self.pct, 1)}


def _period_start(period: str, now: datetime) -> datetime:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day if period == "daily" else day.replace(day=1)


def spent(since: datetime, service_type: str | None = None, user_id: int | None = None) -> Decimal:
    stmt = db.select(db.func.coalesce(db.func.sum(LLMUsageLog.cost_usd), 0)).where(LLMUsageLog.created_at >= since)
    if service_type:
        stmt = stmt.where(LLMUsageLog.service_type == service_type)
    if user_id is not None:
        stmt = stmt.where(LLMUsageLog.user_id == user_id)
    return Decimal(str(db.session.scalar(stmt) or 0))


def applicable(service_type: str, user_id: int | None) -> list[BudgetConfig]:
    budgets = db.session.scalars(db.select(BudgetConfig).filter_by(is_active=True)).all()
    out = []
    for b in budgets:
        if b.scope == "global":
            out.append(b)
        elif b.scope == "service" and b.scope_id == service_type:
            out.append(b)
        elif b.scope == "user" and user_id is not None and b.scope_id in ("", str(user_id)):
            out.append(b)
    # Un límite específico de un usuario sustituye al genérico de "cada usuario"
    if any(b.scope == "user" and b.scope_id == str(user_id) for b in out):
        out = [b for b in out if not (b.scope == "user" and b.scope_id == "")]
    return out


def statuses(service_type: str, user_id: int | None, now: datetime | None = None) -> list[BudgetStatus]:
    now = now or utcnow()
    result = []
    for b in applicable(service_type, user_id):
        for period, limit in (("daily", b.daily_limit_usd), ("monthly", b.monthly_limit_usd)):
            if limit is None or limit <= 0:
                continue
            since = _period_start(period, now)
            amount = spent(since, service_type=service_type if b.scope == "service" else None,
                           user_id=user_id if b.scope == "user" else None)
            result.append(BudgetStatus(b, period, Decimal(limit), amount))
    return result


def check(service_type: str, user_id: int | None) -> None:
    """Aplica los presupuestos antes de una llamada. Lanza BudgetExceededError al bloquear."""
    throttle = 0.0
    for st in statuses(service_type, user_id):
        b = st.budget
        if st.pct >= b.block_threshold_pct:
            audit(AuditAction.AI_BUDGET_EXCEEDED, "WARNING", user_id=user_id, resource_type="budget_configs",
                  resource_id=b.id, details={"service_type": service_type, **st.to_dict()})
            scope = {"global": "de la plataforma", "service": "de este servicio",
                     "user": "por usuario"}[b.scope]
            period = "diario" if st.period == "daily" else "mensual"
            raise BudgetExceededError(f"Se ha alcanzado el presupuesto {period} de IA {scope}. "
                                      "Avisa a un administrador.", budget_id=b.id, period=st.period)
        if st.pct >= b.throttle_threshold_pct:
            throttle = max(throttle, b.throttle_delay_seconds)
        if st.pct >= b.alert_threshold_pct:
            _alert(st)
    if throttle:
        log.warning("ai_budget_throttled", service_type=service_type, delay=throttle)
        time.sleep(min(throttle, current_app.config.get("AI_MAX_THROTTLE_SECONDS", 10)))


def _alert(st: BudgetStatus) -> None:
    from ..services.notifications import notify_many, superadmins

    day = utcnow().strftime("%Y-%m-%d")
    link = f"/admin/ia/presupuestos?b={st.budget.id}&p={st.period}&d={day}"
    try:
        notify_many(superadmins(), "SYSTEM", f"Presupuesto de IA al {st.pct:.0f} %",
                    body=f"Gastado {st.spent:.2f} USD de {st.limit:.2f} USD ({st.period}, {st.budget.scope}).",
                    priority="high", link=link)
    except Exception as exc:  # noqa: BLE001 - el aviso no debe impedir la llamada
        log.warning("ai_budget_alert_failed", error=str(exc))


def overview(now: datetime | None = None) -> list[dict]:
    """Estado de todos los presupuestos para el panel de administración."""
    now = now or utcnow()
    out = []
    for b in db.session.scalars(db.select(BudgetConfig).order_by(BudgetConfig.id)):
        item = {"id": b.id, "scope": b.scope, "scope_id": b.scope_id, "is_active": b.is_active,
                "daily_limit_usd": None if b.daily_limit_usd is None else f"{b.daily_limit_usd:.2f}",
                "monthly_limit_usd": None if b.monthly_limit_usd is None else f"{b.monthly_limit_usd:.2f}",
                "alert_threshold_pct": b.alert_threshold_pct, "throttle_threshold_pct": b.throttle_threshold_pct,
                "block_threshold_pct": b.block_threshold_pct, "throttle_delay_seconds": b.throttle_delay_seconds}
        service = b.scope_id if b.scope == "service" else None
        user = int(b.scope_id) if b.scope == "user" and b.scope_id.isdigit() else None
        item["spent_today_usd"] = f"{spent(_period_start('daily', now), service, user):.4f}"
        item["spent_month_usd"] = f"{spent(_period_start('monthly', now), service, user):.4f}"
        out.append(item)
    return out


def scan(now: datetime | None = None) -> int:
    """Revisión periódica: avisa de los presupuestos que pasan el umbral de aviso
    aunque no llegue ninguna llamada nueva. Los límites "por cada usuario" se
    revisan en cada llamada, no aquí. Devuelve cuántos avisos aplican."""
    now = now or utcnow()
    count = 0
    for b in db.session.scalars(db.select(BudgetConfig).filter_by(is_active=True)):
        if b.scope == "user" and not b.scope_id.isdigit():
            continue
        service = b.scope_id if b.scope == "service" else None
        user = int(b.scope_id) if b.scope == "user" else None
        for period, limit in (("daily", b.daily_limit_usd), ("monthly", b.monthly_limit_usd)):
            if limit is None or limit <= 0:
                continue
            st = BudgetStatus(b, period, Decimal(limit), spent(_period_start(period, now), service, user))
            if st.pct >= b.alert_threshold_pct:
                _alert(st)
                count += 1
    return count
