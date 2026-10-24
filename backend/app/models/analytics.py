"""Esquema analytics_db: datos derivados para inteligencia de negocio (Cap. 23).

El retorno de la inversión de la IA (Capítulo 11) se registra desde la fase 5. La
fase 9a añade el mapa de oportunidad (puntuación por sector y línea de servicio),
las fotos diarias de la cartera, los competidores y los objetivos de negocio.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db
from .base import AuditMixin, BusinessMixin, TimestampMixin, VersionedMixin, utcnow

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


# ---------------------------------------------------------------- Mapa de oportunidad (fase 9a)
class HeatmapConfig(AuditMixin, VersionedMixin, db.Model):
    """Pesos de las cuatro dimensiones del mapa de oportunidad (suman 100).

    Una sola fila activa. Se editan desde Analítica; cambiar los pesos recalcula
    el mes en curso. Los meses anteriores conservan los pesos con que se calcularon."""

    __bind_key__ = BIND
    __tablename__ = "heatmap_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weight_demand: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    weight_traction: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    weight_economic: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    weight_right_to_win: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    lookback_months: Mapped[int] = mapped_column(Integer, nullable=False, default=12)

    def weights(self) -> dict[str, int]:
        return {"demand": self.weight_demand, "traction": self.weight_traction,
                "economic": self.weight_economic, "right_to_win": self.weight_right_to_win}


class HeatmapScore(TimestampMixin, db.Model):
    """Puntuación 0-100 de una celda sector x línea de servicio en un mes.

    Guarda las subpuntuaciones y los datos de partida para poder explicar cada
    cifra (de dónde sale el 72 de «Sanidad x Ciberseguridad»)."""

    __bind_key__ = BIND
    __tablename__ = "heatmap_scores"
    __table_args__ = (UniqueConstraint("period", "sector", "service_line", name="uq_heatmap_cell"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # AAAA-MM
    sector: Mapped[str] = mapped_column(String(100), nullable=False)
    service_line: Mapped[str] = mapped_column(String(50), nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_demand: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    score_traction: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    score_economic: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    score_right_to_win: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    opportunities_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prior_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    won_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lost_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_value_eur: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    pipeline_eur: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    weights: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


# ---------------------------------------------------------------- Competidores y objetivos (fase 9a)
class CompetitorProfile(BusinessMixin, VersionedMixin, db.Model):
    """Competidor con su DAFO. Se edita a mano o se importa desde Excel."""

    __bind_key__ = BIND
    __tablename__ = "competitor_profiles"

    TYPES = ("direct", "indirect", "substitute")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    competitor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="direct")
    website: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2000))
    strengths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    weaknesses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    opportunities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    threats: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    service_lines: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # códigos donde coincidimos
    sectors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    price_positioning: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # -1, 0, 1


class BusinessTarget(BusinessMixin, VersionedMixin, db.Model):
    """Objetivo mensual de una métrica, para el total o para una línea de servicio."""

    __bind_key__ = BIND
    __tablename__ = "business_targets"
    __table_args__ = (UniqueConstraint("metric", "period", "service_line", name="uq_target_metric_period_line"),)

    METRICS = ("new_count", "new_eur", "won_count", "won_eur")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric: Mapped[str] = mapped_column(String(30), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # AAAA-MM
    service_line: Mapped[str] = mapped_column(String(50), nullable=False, default="")  # "" = total
    target_value: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
