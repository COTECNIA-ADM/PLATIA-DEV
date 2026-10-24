"""Cuadro de mando de negocio (app ``analytics``, fase 6b).

Se calcula al vuelo sobre operations_db: con los volúmenes del caso (miles de
oportunidades) basta con una consulta por tabla y el agregado en Python. Si crece,
el paso siguiente son las instantáneas diarias de ``analytics_db`` (fase 9).

Definiciones:
- Cartera abierta: oportunidades que no están en F5 (ganada, perdida, descartada).
- Cartera ponderada: importe x probabilidad (sin probabilidad no cuenta).
- Tasa de éxito: ganadas / (ganadas + perdidas) cerradas en el periodo. Las
  descartadas no cuentan: no se llegó a competir.
- Embudo: de las oportunidades creadas en el periodo, cuántas llegaron al menos a
  cada fase (según su historial de estados). F5 es «ganada».
- Fechas de cierre: las del historial de estados, no ``updated_at``.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from ..extensions import db
from ..models import (
    Client,
    LLMUsageLog,
    Opportunity,
    OpportunityStatusChange,
    Proposal,
    ServiceLine,
    utcnow,
)

PHASES = ("F1", "F2", "F3", "F4", "F5")
CLOSED = ("won", "lost", "discarded")
NO_VALUE = "Sin indicar"


def _month(value: datetime) -> str:
    return value.strftime("%Y-%m")


def period_start(months: int, now: datetime | None = None) -> datetime:
    """Primer día del mes, ``months - 1`` meses atrás (el mes actual cuenta)."""
    now = now or utcnow()
    index = now.year * 12 + now.month - 1 - (months - 1)
    return datetime(index // 12, index % 12 + 1, 1)


def month_keys(start: datetime, now: datetime) -> list[str]:
    keys, year, month = [], start.year, start.month
    while (year, month) <= (now.year, now.month):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return keys


def _eur(value: Decimal) -> str:
    return f"{value:.2f}"


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _reached_phase(statuses: list[str]) -> int:
    """Índice (0-4) de la fase más avanzada. Perder o descartar no hace avanzar."""
    best = 0
    for status in statuses:
        if status == "won":
            best = 4
        elif status not in ("lost", "discarded"):
            best = max(best, PHASES.index(Opportunity.STATUS_PHASE.get(status, "F1")))
    return best


def overview(months: int = 12, service_line: str | None = None, sector: str | None = None) -> dict:
    now = utcnow()
    start = period_start(months, now)
    keys = month_keys(start, now)

    rows = db.session.execute(
        db.select(Opportunity.id, Opportunity.status, Opportunity.service_line, Opportunity.sector,
                  Opportunity.source, Opportunity.estimated_value_eur, Opportunity.probability,
                  Opportunity.created_at, Opportunity.client_id, Client.name, Client.sector)
        .outerjoin(Client, Client.id == Opportunity.client_id)
        .where(Opportunity.is_active.is_(True))
    ).all()
    opps = {}
    for (oid, status, line, opp_sector, source, value, probability, created_at, client_id, client_name,
         client_sector) in rows:
        item = {"status": status, "line": line or NO_VALUE, "sector": opp_sector or client_sector or NO_VALUE,
                "source": source or NO_VALUE, "value": value or Decimal(0), "probability": probability,
                "created_at": created_at, "client_id": client_id, "client_name": client_name}
        if service_line and item["line"] != service_line:
            continue
        if sector and item["sector"] != sector:
            continue
        opps[oid] = item

    # Historial: estados por oportunidad y fecha de cierre (último paso a won/lost/discarded)
    history: dict[int, list[str]] = defaultdict(list)
    closed_at: dict[int, tuple[str, datetime]] = {}
    for oid, to_status, changed_at in db.session.execute(
        db.select(OpportunityStatusChange.opportunity_id, OpportunityStatusChange.to_status,
                  OpportunityStatusChange.created_at).where(OpportunityStatusChange.is_active.is_(True)).order_by(OpportunityStatusChange.created_at,
                                                               OpportunityStatusChange.id)
    ).all():
        if oid not in opps:
            continue
        history[oid].append(to_status)
        if to_status in CLOSED:
            closed_at[oid] = (to_status, changed_at)
        else:
            closed_at.pop(oid, None)  # reabierta
    for oid, item in opps.items():
        if item["status"] in CLOSED and oid not in closed_at:
            closed_at[oid] = (item["status"], item["created_at"])  # sin historial: mejor aproximación

    # ---------------------------------------------------------- KPI y tendencia mensual
    monthly = {k: {"month": k, "new_count": 0, "new_eur": Decimal(0), "won_count": 0, "won_eur": Decimal(0),
                   "lost_count": 0} for k in keys}
    open_items = [o for o in opps.values() if o["status"] not in CLOSED]
    pipeline = sum((o["value"] for o in open_items), Decimal(0))
    weighted = sum((o["value"] * o["probability"] / 100 for o in open_items if o["probability"] is not None),
                   Decimal(0))
    won = lost = discarded = 0
    won_eur = Decimal(0)
    for oid, item in opps.items():
        if item["created_at"] >= start:
            m = monthly.get(_month(item["created_at"]))
            if m:
                m["new_count"] += 1
                m["new_eur"] += item["value"]
        closed = closed_at.get(oid)
        if closed and closed[1] >= start:
            m = monthly.get(_month(closed[1]))
            if closed[0] == "won":
                won, won_eur = won + 1, won_eur + item["value"]
                if m:
                    m["won_count"] += 1
                    m["won_eur"] += item["value"]
            elif closed[0] == "lost":
                lost += 1
                if m:
                    m["lost_count"] += 1
            else:
                discarded += 1

    # ---------------------------------------------------------- Embudo (cohorte del periodo)
    cohort = [oid for oid, o in opps.items() if o["created_at"] >= start]
    reached = [0] * len(PHASES)
    for oid in cohort:
        statuses = history.get(oid) or [opps[oid]["status"]]
        for i in range(_reached_phase(statuses + [opps[oid]["status"]]) + 1):
            reached[i] += 1
    current = {p: {"count": 0, "eur": Decimal(0)} for p in PHASES}
    for o in open_items:
        phase = Opportunity.STATUS_PHASE.get(o["status"], "F1")
        current[phase]["count"] += 1
        current[phase]["eur"] += o["value"]
    funnel = [{"phase": p, "reached": reached[i], "reached_pct": _rate(reached[i], len(cohort)),
               "open_count": current[p]["count"], "open_eur": _eur(current[p]["eur"])}
              for i, p in enumerate(PHASES)]

    # ---------------------------------------------------------- Desgloses
    def breakdown(field: str) -> list[dict]:
        groups: dict[str, dict] = {}
        for oid, o in opps.items():
            g = groups.setdefault(o[field], {"key": o[field], "open_count": 0, "pipeline_eur": Decimal(0),
                                             "won": 0, "lost": 0, "won_eur": Decimal(0)})
            if o["status"] not in CLOSED:
                g["open_count"] += 1
                g["pipeline_eur"] += o["value"]
            closed = closed_at.get(oid)
            if closed and closed[1] >= start and closed[0] in ("won", "lost"):
                g[closed[0]] += 1
                if closed[0] == "won":
                    g["won_eur"] += o["value"]
        out = []
        for g in groups.values():
            g["win_rate"] = _rate(g["won"], g["won"] + g["lost"])
            g["pipeline_eur"], g["won_eur"] = _eur(g["pipeline_eur"]), _eur(g["won_eur"])
            out.append(g)
        return sorted(out, key=lambda g: (-Decimal(g["pipeline_eur"]), -g["open_count"], g["key"]))

    line_names = dict(db.session.execute(db.select(ServiceLine.code, ServiceLine.name)).all())
    by_line = [{**g, "label": line_names.get(g["key"], g["key"])} for g in breakdown("line")]
    by_sector = [{**g, "label": g["key"]} for g in breakdown("sector")]

    # Mapa de calor sector x línea: cartera abierta
    cells: dict[tuple[str, str], dict] = {}
    for o in open_items:
        c = cells.setdefault((o["sector"], o["line"]), {"sector": o["sector"], "service_line": o["line"],
                                                         "count": 0, "eur": Decimal(0)})
        c["count"] += 1
        c["eur"] += o["value"]
    heatmap = [{**c, "eur": _eur(c["eur"]), "service_line_label": line_names.get(c["service_line"], c["service_line"])}
               for c in cells.values()]

    clients: dict[int, dict] = {}
    for oid, o in opps.items():
        if o["client_id"] is None:
            continue
        c = clients.setdefault(o["client_id"], {"client_id": o["client_id"], "name": o["client_name"],
                                                "open_count": 0, "pipeline_eur": Decimal(0), "won_eur": Decimal(0)})
        if o["status"] not in CLOSED:
            c["open_count"] += 1
            c["pipeline_eur"] += o["value"]
        closed = closed_at.get(oid)
        if closed and closed[0] == "won" and closed[1] >= start:
            c["won_eur"] += o["value"]
    top_clients = sorted(clients.values(), key=lambda c: (-(c["pipeline_eur"] + c["won_eur"]), c["name"] or ""))[:8]

    # ---------------------------------------------------------- Propuestas
    proposal_rows = db.session.execute(
        db.select(Proposal.opportunity_id, Proposal.status, Proposal.created_at, Proposal.sent_at,
                  Proposal.review_round).where(Proposal.is_active.is_(True))
    ).all()
    by_status: dict[str, int] = defaultdict(int)
    days_to_send, rounds, sent = [], [], 0
    for opp_id, status, created_at, sent_at, review_round in proposal_rows:
        if opp_id not in opps:
            continue
        by_status[status] += 1
        if sent_at and sent_at >= start:
            sent += 1
            days_to_send.append((sent_at - created_at).total_seconds() / 86400)
            rounds.append(review_round)

    return {
        "period": {"months": months, "from": start.isoformat() + "Z", "to": now.isoformat(timespec="seconds") + "Z"},
        "filters": {"service_line": service_line, "sector": sector},
        "kpis": {
            "open_count": len(open_items), "pipeline_eur": _eur(pipeline), "weighted_pipeline_eur": _eur(weighted),
            "new_count": len(cohort), "won_count": won, "won_eur": _eur(won_eur), "lost_count": lost,
            "discarded_count": discarded, "win_rate": _rate(won, won + lost), "proposals_sent": sent,
        },
        "funnel": funnel,
        "monthly": [{**m, "new_eur": _eur(m["new_eur"]), "won_eur": _eur(m["won_eur"])} for m in monthly.values()],
        "by_service_line": by_line,
        "by_sector": by_sector,
        "heatmap": heatmap,
        "top_clients": [{**c, "pipeline_eur": _eur(c["pipeline_eur"]), "won_eur": _eur(c["won_eur"])}
                        for c in top_clients],
        "proposals": {
            "by_status": dict(by_status), "sent": sent,
            "avg_days_to_send": round(sum(days_to_send) / len(days_to_send), 1) if days_to_send else None,
            "avg_review_rounds": round(sum(rounds) / len(rounds), 1) if rounds else None,
        },
    }


def ai_costs(months: int = 12) -> list[dict]:
    """Gasto en IA por mes (USD, tal como se registra cada llamada)."""
    now = utcnow()
    start = period_start(months, now)
    series = {k: {"month": k, "calls": 0, "cost_usd": Decimal(0)} for k in month_keys(start, now)}
    year, month = db.extract("year", LLMUsageLog.created_at), db.extract("month", LLMUsageLog.created_at)
    for y, mo, calls, cost in db.session.execute(
        db.select(year, month, db.func.count(), db.func.sum(LLMUsageLog.cost_usd))
        .where(LLMUsageLog.created_at >= start).group_by(year, month)
    ).all():
        m = series.get(f"{int(y):04d}-{int(mo):02d}")
        if m:
            m["calls"] += calls
            m["cost_usd"] += Decimal(str(cost or 0))
    return [{**m, "cost_usd": f"{m['cost_usd']:.4f}"} for m in series.values()]
