"""Esquema analytics_db: datos derivados para inteligencia de negocio (Cap. 23).

En esta fase solo se crean las tablas base; se alimentan en la fase 9.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Date, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db
from .base import AuditMixin, TimestampMixin

BIND = "analytics"


class DashboardConfig(AuditMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "dashboard_configs"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_dashboard_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    layout: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class FunnelStage(TimestampMixin, db.Model):
    """Métricas del embudo F1-F5 por periodo."""

    __bind_key__ = BIND
    __tablename__ = "funnel_stages"
    __table_args__ = (UniqueConstraint("period", "phase", name="uq_funnel_period_phase"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # AAAA-MM
    phase: Mapped[str] = mapped_column(String(2), nullable=False)  # F1..F5
    opportunities_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_value_eur: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0, nullable=False)
    conversion_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class AnalyticsSnapshot(TimestampMixin, db.Model):
    """Foto periódica de una métrica para ver tendencias."""

    __bind_key__ = BIND
    __tablename__ = "analytics_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "metric", "dimension", name="uq_snapshot_metric"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(100), nullable=False)
    dimension: Mapped[str] = mapped_column(String(100), nullable=False, default="total")
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    extra_data: Mapped[dict | None] = mapped_column(JSON)
