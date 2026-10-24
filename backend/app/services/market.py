"""Mapa de oportunidad: puntuación 0-100 por sector x línea de servicio (Capítulo 23).

Cada celda se puntúa en cuatro dimensiones, con los datos de los últimos
``lookback_months`` meses de operations_db:

- **Demanda**: cuántas oportunidades aparecen en ese cruce (todas, también las
  descartadas: miden el mercado, no nuestra elección).
- **Tracción**: si el cruce crece. Oportunidades de la mitad reciente del periodo
  frente a la mitad anterior, con suavizado (+1) para que un 1 frente a 0 no sea
  un «infinito».
- **Valor económico**: importe medio de las oportunidades con importe. En escala
  logarítmica, para que un contrato enorme no aplaste al resto.
- **Capacidad de ganar**: tasa de éxito (ganadas / ganadas + perdidas) suavizada
  hacia la media de la empresa con ``PRIOR_WEIGHT`` cierres ficticios: con dos
  cierres no se puede afirmar un 100 %.

Cada dimensión se normaliza de 0 a 100 entre las celdas del mes (es una
comparación relativa: 100 es la mejor celda, no un valor absoluto) y la
puntuación total es la media ponderada con los pesos de ``HeatmapConfig``.
Las celdas sin sector o sin línea no se puntúan: no sirven para decidir dónde
invertir, y se cuentan aparte (``unclassified``).

Se recalcula cada noche para el mes en curso (``tasks.analytics.compute_heatmap``)
y cuando cambian los pesos. Los meses cerrados se conservan tal como quedaron.
"""
import math
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

import structlog
from sqlalchemy import delete

from ..errors import ValidationError
from ..extensions import db
from ..models import Client, HeatmapConfig, HeatmapScore, Opportunity, ServiceLine, utcnow
from .analytics import NO_VALUE, month_keys, period_start

log = structlog.get_logger(__name__)

DIMENSIONS = ("demand", "traction", "economic", "right_to_win")
PRIOR_WEIGHT = 3  # cierres ficticios con la tasa media al suavizar la tasa de éxito
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def current_period(now: datetime | None = None) -> str:
    return (now or utcnow()).strftime("%Y-%m")


def validate_period(period: str) -> str:
    if not PERIOD_RE.match(period or ""):
        raise ValidationError("El periodo debe tener el formato AAAA-MM.")
    return period


def get_config() -> HeatmapConfig:
    config = db.session.scalar(db.select(HeatmapConfig).order_by(HeatmapConfig.id).limit(1))
    if config is None:
        config = HeatmapConfig()
        db.session.add(config)
        db.session.flush()
    return config


def config_dict(config: HeatmapConfig) -> dict:
    return {"weights": config.weights(), "lookback_months": config.lookback_months,
            "version": config.row_version}


def _period_end(period: str) -> datetime:
    """Primer instante del mes siguiente."""
    year, month = map(int, period.split("-"))
    return datetime(year + month // 12, month % 12 + 1, 1)


def _normalize(values: dict, *, log_scale: bool = False) -> dict:
    """Escala 0-100 entre las celdas. Si todas valen lo mismo, 50."""
    present = {k: v for k, v in values.items() if v is not None}
    if log_scale:
        present = {k: math.log1p(v) for k, v in present.items()}
    if not present:
        return {k: 0.0 for k in values}
    low, high = min(present.values()), max(present.values())
    out = {}
    for key in values:
        if key not in present:
            out[key] = 0.0  # sin dato (p. ej. ninguna oportunidad con importe)
        elif high == low:
            out[key] = 50.0
        else:
            out[key] = round((present[key] - low) / (high - low) * 100, 1)
    return out


def compute(period: str | None = None, now: datetime | None = None) -> dict:
    """Calcula y guarda las puntuaciones de un mes. Idempotente: sustituye las del mes."""
    now = now or utcnow()
    period = validate_period(period or current_period(now))
    config = get_config()
    weights = config.weights()
    months = max(2, config.lookback_months)
    # La ventana termina al final del mes pedido (o ahora, si es el mes en curso)
    end = min(_period_end(period), now)
    start = period_start(months, end)
    keys = month_keys(start, end)
    midpoint_key = keys[len(keys) // 2]

    rows = db.session.execute(
        db.select(Opportunity.sector, Client.sector, Opportunity.service_line, Opportunity.status,
                  Opportunity.estimated_value_eur, Opportunity.created_at)
        .outerjoin(Client, Client.id == Opportunity.client_id)
        .where(Opportunity.is_active.is_(True), Opportunity.created_at >= start, Opportunity.created_at < end)
    ).all()

    cells: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "count": 0, "recent": 0, "prior": 0, "won": 0, "lost": 0, "values": [], "pipeline": Decimal(0)})
    unclassified = 0
    for opp_sector, client_sector, line, status, value, created_at in rows:
        sector = opp_sector or client_sector
        if not sector or not line or sector == NO_VALUE:
            unclassified += 1
            continue
        c = cells[(sector, line)]
        c["count"] += 1
        if created_at.strftime("%Y-%m") >= midpoint_key:
            c["recent"] += 1
        else:
            c["prior"] += 1
        if status == "won":
            c["won"] += 1
        elif status == "lost":
            c["lost"] += 1
        elif status != "discarded" and value:
            c["pipeline"] += value
        if value:
            c["values"].append(value)

    total_won = sum(c["won"] for c in cells.values())
    total_closed = total_won + sum(c["lost"] for c in cells.values())
    base_rate = total_won / total_closed if total_closed else 0.5

    raw = {dim: {} for dim in DIMENSIONS}
    for key, c in cells.items():
        raw["demand"][key] = c["count"]
        raw["traction"][key] = math.log((c["recent"] + 1) / (c["prior"] + 1))
        raw["economic"][key] = float(sum(c["values"]) / len(c["values"])) if c["values"] else None
        raw["right_to_win"][key] = (c["won"] + PRIOR_WEIGHT * base_rate) / (c["won"] + c["lost"] + PRIOR_WEIGHT)
    scores = {dim: _normalize(raw[dim], log_scale=(dim == "economic")) for dim in DIMENSIONS}

    total_weight = sum(weights.values()) or 1
    db.session.execute(delete(HeatmapScore).where(HeatmapScore.period == period))
    for (sector, line), c in cells.items():
        sub = {dim: scores[dim][(sector, line)] for dim in DIMENSIONS}
        total = sum(sub[dim] * weights[dim] for dim in DIMENSIONS) / total_weight
        db.session.add(HeatmapScore(
            period=period, sector=sector, service_line=line, total_score=round(total, 1),
            score_demand=sub["demand"], score_traction=sub["traction"], score_economic=sub["economic"],
            score_right_to_win=sub["right_to_win"], opportunities_count=c["count"], recent_count=c["recent"],
            prior_count=c["prior"], won_count=c["won"], lost_count=c["lost"],
            avg_value_eur=(sum(c["values"]) / len(c["values"])).quantize(Decimal("0.01")) if c["values"] else None,
            pipeline_eur=c["pipeline"], weights={**weights, "lookback_months": months,
                                                 "unclassified": unclassified},
            calculated_at=now,
        ))
    db.session.commit()
    log.info("heatmap_computed", period=period, cells=len(cells), unclassified=unclassified)
    return {"period": period, "cells": len(cells), "unclassified": unclassified}


def periods() -> list[str]:
    return list(db.session.scalars(
        db.select(HeatmapScore.period).distinct().order_by(HeatmapScore.period.desc()).limit(36)))


def score_dict(s: HeatmapScore, line_names: dict[str, str]) -> dict:
    return {
        "sector": s.sector, "service_line": s.service_line,
        "service_line_label": line_names.get(s.service_line, s.service_line),
        "total_score": s.total_score,
        "scores": {"demand": s.score_demand, "traction": s.score_traction, "economic": s.score_economic,
                   "right_to_win": s.score_right_to_win},
        "data": {"opportunities": s.opportunities_count, "recent": s.recent_count, "prior": s.prior_count,
                 "won": s.won_count, "lost": s.lost_count,
                 "avg_value_eur": None if s.avg_value_eur is None else f"{s.avg_value_eur:.2f}",
                 "pipeline_eur": f"{s.pipeline_eur:.2f}"},
    }


def heatmap(period: str | None = None) -> dict | None:
    """Puntuaciones de un mes. El mes en curso se calcula si aún no existe."""
    period = validate_period(period or current_period())
    rows = list(db.session.scalars(db.select(HeatmapScore).where(HeatmapScore.period == period)
                                   .order_by(HeatmapScore.total_score.desc())))
    if not rows and period == current_period():
        compute(period)
        rows = list(db.session.scalars(db.select(HeatmapScore).where(HeatmapScore.period == period)
                                       .order_by(HeatmapScore.total_score.desc())))
    if not rows:
        return None
    line_names = dict(db.session.execute(db.select(ServiceLine.code, ServiceLine.name)).all())
    first = rows[0]
    weights = {k: v for k, v in (first.weights or {}).items() if k in DIMENSIONS}
    return {
        "period": period,
        "calculated_at": first.calculated_at.isoformat(timespec="seconds") + "Z",
        "weights": weights,
        "lookback_months": (first.weights or {}).get("lookback_months"),
        "unclassified": (first.weights or {}).get("unclassified", 0),
        "cells": [score_dict(s, line_names) for s in rows],
    }


def top_cells(limit: int = 10) -> list[dict]:
    """Las mejores celdas del último mes calculado (para el asistente de datos)."""
    data = heatmap(periods()[0]) if periods() else None
    return (data or {}).get("cells", [])[:limit]
