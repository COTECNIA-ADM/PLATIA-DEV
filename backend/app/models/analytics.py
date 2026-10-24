"""Esquema analytics_db: datos derivados para inteligencia de negocio (Cap. 23).

Las tablas de cuadros de mando se alimentan en la fase 9. El retorno de la
inversión de la IA (Capítulo 11) se registra desde la fase 5.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db
from .base import AuditMixin, TimestampMixin, utcnow

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


class HumanBaselineConfig(TimestampMixin, db.Model):
    """Cuánto tardaría una persona en hacer cada tarea que hace la IA (Capítulo 11).

    Es una estimación de la organización, editable desde Admin. Con ella se calcula
    el ahorro de cada tarea completada."""

    __bind_key__ = BIND
    __tablename__ = "human_baseline_config"

    service_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_name: Mapped[str] = mapped_column(String(128), nullable=False)
    human_time_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    human_hourly_cost_eur: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("65"))


class TaskCompletionLog(db.Model):
    """Una fila por tarea de IA completada, con su coste y el ahorro estimado."""

    __bind_key__ = BIND
    __tablename__ = "task_completion_log"
    __table_args__ = (Index("ix_task_completion_service_created", "service_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(30))
    subject_id: Mapped[int | None] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    ai_duration_seconds: Mapped[float | None] = mapped_column(Float)
    llm_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    human_time_baseline_minutes: Mapped[float | None] = mapped_column(Float)
    time_saved_minutes: Mapped[float | None] = mapped_column(Float)
    money_saved_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    quality_score: Mapped[float | None] = mapped_column(Float)
    user_rating: Mapped[int | None] = mapped_column(Integer)
    was_accepted: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
