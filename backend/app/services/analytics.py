"""Cuadro de mando de negocio (app ``analytics``, fase 6b).

Se calcula al vuelo sobre operations_db: con los volúmenes del caso (miles de
oportunidades) basta con una consulta por tabla y el agregado en Python.

Lo que no se puede reconstruir después (cuánta cartera abierta había un día
concreto) se guarda cada noche en ``analytics_snapshots`` (fase 9a). Con esas
fotos se compara la cartera con la del inicio del periodo y se dibuja su evolución.
Las métricas de flujo (nuevas, ganadas, perdidas) del periodo anterior sí salen
del historial de estados.

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
from datetime import date, datetime, timedelta
from decimal import Decimal

from ..extensions import db
from ..models import (
    AnalyticsSnapshot,
    BusinessTarget,
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
    # Periodo anterior de la misma duración, para comparar
    prev_start = period_start(months, start - timedelta(days=1))

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
    prev = {"new_count": 0, "won_count": 0, "won_eur": Decimal(0), "lost_count": 0}
    for oid, item in opps.items():
        closed = closed_at.get(oid)
        if prev_start <= item["created_at"] < start:
            prev["new_count"] += 1
        if closed and prev_start <= closed[1] < start and closed[0] in ("won", "lost"):
            prev[f"{closed[0]}_count"] += 1
            if closed[0] == "won":
                prev["won_eur"] += item["value"]
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
    days_to_send, rounds, sent, prev_sent = [], [], 0, 0
    for opp_id, status, created_at, sent_at, review_round in proposal_rows:
        if opp_id not in opps:
            continue
        by_status[status] += 1
        if sent_at and prev_start <= sent_at < start:
            prev_sent += 1
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
        "previous": _previous_kpis(prev, prev_sent, prev_start, start, filtered=bool(service_line or sector)),
        "pipeline_history": [] if (service_line or sector) else pipeline_history(start.date()),
        "targets": targets_vs_actual(keys, monthly, service_line) if not sector else [],
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


# ---------------------------------------------------------------- Comparación y fotos (fase 9a)
SNAPSHOT_METRICS = ("pipeline_eur", "weighted_pipeline_eur", "open_count")


def _previous_kpis(prev: dict, sent: int, prev_start: datetime, start: datetime, *, filtered: bool) -> dict:
    """KPI del periodo anterior. La cartera abierta sale de la foto más cercana al
    inicio del periodo actual (solo sin filtros: las fotos guardan el total)."""
    snap = None if filtered else snapshot_at(start.date() - timedelta(days=1))
    return {
        "from": prev_start.isoformat() + "Z", "to": start.isoformat() + "Z",
        "new_count": prev["new_count"], "won_count": prev["won_count"], "won_eur": _eur(prev["won_eur"]),
        "lost_count": prev["lost_count"],
        "win_rate": _rate(prev["won_count"], prev["won_count"] + prev["lost_count"]),
        "proposals_sent": sent,
        "pipeline_eur": snap["pipeline_eur"] if snap else None,
        "weighted_pipeline_eur": snap["weighted_pipeline_eur"] if snap else None,
        "open_count": int(Decimal(snap["open_count"])) if snap else None,
        "pipeline_date": snap["date"] if snap else None,
    }


def take_snapshot(today: date | None = None) -> dict:
    """Foto de la cartera abierta (total y por fase). Idempotente: una por día."""
    today = today or utcnow().date()
    values: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for status, value, probability in db.session.execute(
        db.select(Opportunity.status, Opportunity.estimated_value_eur, Opportunity.probability)
        .where(Opportunity.is_active.is_(True), Opportunity.status.notin_(CLOSED))
    ).all():
        phase = Opportunity.STATUS_PHASE.get(status, "F1")
        value = value or Decimal(0)
        weighted = value * probability / 100 if probability is not None else Decimal(0)
        for dimension in ("total", phase):
            values[("open_count", dimension)] += 1
            values[("pipeline_eur", dimension)] += value
            values[("weighted_pipeline_eur", dimension)] += weighted
    for metric in SNAPSHOT_METRICS:
        values.setdefault((metric, "total"), Decimal(0))
    existing = {(s.metric, s.dimension): s for s in db.session.scalars(
        db.select(AnalyticsSnapshot).where(AnalyticsSnapshot.snapshot_date == today,
                                           AnalyticsSnapshot.metric.in_(SNAPSHOT_METRICS)))}
    for (metric, dimension), value in values.items():
        row = existing.pop((metric, dimension), None)
        if row is None:
            db.session.add(AnalyticsSnapshot(snapshot_date=today, metric=metric, dimension=dimension, value=value))
        else:
            row.value = value
    for row in existing.values():  # una fase que se ha quedado vacía
        row.value = Decimal(0)
    db.session.commit()
    return {"date": today.isoformat(), "pipeline_eur": _eur(values[("pipeline_eur", "total")]),
            "open_count": int(values[("open_count", "total")])}


def _snapshot_rows(stmt) -> dict[date, dict]:
    days: dict[date, dict] = defaultdict(dict)
    for day, metric, value in db.session.execute(stmt).all():
        days[day][metric] = value
    return days


def snapshot_at(day: date) -> dict | None:
    """Foto del total más reciente en ``day`` o antes (hasta 7 días antes)."""
    found = db.session.scalar(
        db.select(AnalyticsSnapshot.snapshot_date).where(
            AnalyticsSnapshot.dimension == "total", AnalyticsSnapshot.metric == "pipeline_eur",
            AnalyticsSnapshot.snapshot_date <= day, AnalyticsSnapshot.snapshot_date >= day - timedelta(days=7))
        .order_by(AnalyticsSnapshot.snapshot_date.desc()).limit(1))
    if found is None:
        return None
    values = _snapshot_rows(db.select(AnalyticsSnapshot.snapshot_date, AnalyticsSnapshot.metric,
                                      AnalyticsSnapshot.value)
                            .where(AnalyticsSnapshot.snapshot_date == found, AnalyticsSnapshot.dimension == "total"))
    v = values[found]
    return {"date": found.isoformat(), **{m: _eur(v.get(m, Decimal(0))) for m in SNAPSHOT_METRICS}}


def pipeline_history(since: date) -> list[dict]:
    """Evolución de la cartera abierta: una foto por semana (la última de cada semana)."""
    days = _snapshot_rows(
        db.select(AnalyticsSnapshot.snapshot_date, AnalyticsSnapshot.metric, AnalyticsSnapshot.value)
        .where(AnalyticsSnapshot.dimension == "total", AnalyticsSnapshot.snapshot_date >= since,
               AnalyticsSnapshot.metric.in_(SNAPSHOT_METRICS))
        .order_by(AnalyticsSnapshot.snapshot_date))
    weekly: dict[tuple[int, int], date] = {}
    for day in sorted(days):
        weekly[day.isocalendar()[:2]] = day
    return [{"date": d.isoformat(), "pipeline_eur": _eur(days[d].get("pipeline_eur", Decimal(0))),
             "weighted_pipeline_eur": _eur(days[d].get("weighted_pipeline_eur", Decimal(0))),
             "open_count": int(days[d].get("open_count", 0))} for d in sorted(weekly.values())]


def targets_vs_actual(keys: list[str], monthly: dict, service_line: str | None) -> list[dict]:
    """Objetivo frente a real por métrica. Solo cuentan los meses que tienen objetivo."""
    rows = db.session.execute(
        db.select(BusinessTarget.metric, BusinessTarget.period, BusinessTarget.target_value)
        .where(BusinessTarget.is_active.is_(True), BusinessTarget.period.in_(keys),
               BusinessTarget.service_line == (service_line or ""))
    ).all()
    by_metric: dict[str, dict] = {}
    for metric, period, target in rows:
        m = by_metric.setdefault(metric, {"metric": metric, "target": Decimal(0), "actual": Decimal(0),
                                          "months": []})
        m["target"] += target
        m["actual"] += Decimal(monthly[period][metric])
        m["months"].append(period)
    out = []
    for metric in BusinessTarget.METRICS:
        if metric in by_metric:
            m = by_metric[metric]
            out.append({**m, "target": _eur(m["target"]), "actual": _eur(m["actual"]),
                        "progress": round(float(m["actual"] / m["target"]), 3) if m["target"] else None,
                        "months": sorted(m["months"])})
    return out
