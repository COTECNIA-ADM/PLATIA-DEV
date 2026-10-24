"""Esquema platform_core: identidad, acceso, auditoría y gobernanza de IA.

Referencia: Apéndice A y Capítulos 5, 6, 11 y 22 del libro.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import AuditMixin, BusinessMixin, TimestampMixin, utcnow

BIND = "core"


# ---------------------------------------------------------------- Identidad (Cap. 6)
class User(BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "users"

    STATUSES = ("active", "locked", "pending")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Solo el hash; la lógica de contraseñas llega en la fase 3
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(String(255))
    # [{"salt": ..., "hash": ..., "used_at": null}], SHA-256 con sal por código (Cap. 6)
    mfa_backup_codes: Mapped[list | None] = mapped_column(JSON)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime)

    memberships: Mapped[list["UserAppMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class App(TimestampMixin, db.Model):
    """Aplicaciones de la plataforma: operations, analytics, admin, security."""

    __bind_key__ = BIND
    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    roles: Mapped[list["AppRole"]] = relationship(back_populates="app")


class AppRole(TimestampMixin, db.Model):
    """Rol dentro de una aplicación, con permisos granulares en JSON."""

    __bind_key__ = BIND
    __tablename__ = "app_roles"
    __table_args__ = (UniqueConstraint("app_id", "code", name="uq_app_roles_app_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Acciones permitidas por módulo, p. ej. {"proposals": ["read", "write"],
    # "ai_modules_access": ["document_analyzer"]}. Lo que no aparece está denegado.
    permissions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Un rol de administrador salta la comprobación de módulo, solo dentro de su app
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"), nullable=False
    )

    app: Mapped[App] = relationship(back_populates="roles")


class UserAppMembership(AuditMixin, db.Model):
    """Relación usuario-aplicación-rol (M2M con datos)."""

    __bind_key__ = BIND
    __tablename__ = "user_app_memberships"
    __table_args__ = (UniqueConstraint("user_id", "app_id", name="uq_membership_user_app"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("app_roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="memberships")
    app: Mapped[App] = relationship()
    role: Mapped[AppRole] = relationship()


# ---------------------------------------------------------------- Auditoría (Cap. 22)
class AuditAction:
    """Acciones de auditoría predefinidas: nunca texto libre (Cap. 22)."""

    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    LOGOUT = "LOGOUT"
    TOKEN_REFRESH = "TOKEN_REFRESH"
    REFRESH_TOKEN_REUSE = "REFRESH_TOKEN_REUSE"
    SESSION_INVALIDATED = "SESSION_INVALIDATED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    MFA_ENABLED = "MFA_ENABLED"
    MFA_DISABLED = "MFA_DISABLED"
    MFA_FAILED = "MFA_FAILED"
    MFA_BACKUP_CODE_USED = "MFA_BACKUP_CODE_USED"
    ACCESS_DENIED = "ACCESS_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"
    USER_CREATED = "USER_CREATED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    # Datos de negocio (fase 4)
    RECORD_CREATED = "RECORD_CREATED"
    RECORD_UPDATED = "RECORD_UPDATED"
    RECORD_DELETED = "RECORD_DELETED"
    OPPORTUNITY_STATUS_CHANGED = "OPPORTUNITY_STATUS_CHANGED"
    PROPOSAL_STATUS_CHANGED = "PROPOSAL_STATUS_CHANGED"
    PROPOSAL_REVIEWED = "PROPOSAL_REVIEWED"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    DOCUMENT_DOWNLOADED = "DOCUMENT_DOWNLOADED"
    DATA_EXPORTED = "DATA_EXPORTED"
    TASK_FAILED = "TASK_FAILED"
    TASK_REQUEUED = "TASK_REQUEUED"
    # Gobernanza de IA (fase 5)
    AI_REQUEST_BLOCKED = "AI_REQUEST_BLOCKED"
    AI_OUTPUT_BLOCKED = "AI_OUTPUT_BLOCKED"
    AI_BUDGET_EXCEEDED = "AI_BUDGET_EXCEEDED"
    AI_CONFIG_CHANGED = "AI_CONFIG_CHANGED"
    PROMPT_PUBLISHED = "PROMPT_PUBLISHED"
    PROMPT_ACTIVATED = "PROMPT_ACTIVATED"
    PROMPT_INTEGRITY_VIOLATION = "PROMPT_INTEGRITY_VIOLATION"
    PII_DETECTED_IN_OUTPUT = "PII_DETECTED_IN_OUTPUT"
    GDPR_AI_EXPORT = "GDPR_AI_EXPORT"
    GDPR_AI_ERASURE = "GDPR_AI_ERASURE"


class AuditLog(db.Model):
    """Registro inmutable de acciones relevantes. Solo se inserta, nunca se modifica."""

    __bind_key__ = BIND
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_action_created", "action", "created_at"),
        Index("ix_audit_log_user_action", "user_id", "action"),
        Index("ix_audit_log_severity_created", "severity", "created_at"),
    )

    SEVERITIES = ("INFO", "WARNING", "CRITICAL")

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="INFO", nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(45))  # cabe IPv6
    user_agent: Mapped[str | None] = mapped_column(String(500))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class UserSession(db.Model):
    """Una sesión por token de refresco. Rotación: cada uso revoca la fila y crea otra."""

    __bind_key__ = BIND
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    refresh_jti: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    family_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revocation_reason: Mapped[str | None] = mapped_column(String(50))


# ---------------------------------------------------------------- Colas (Cap. 8)
class FailedTask(TimestampMixin, db.Model):
    """Dead-letter queue: tareas que agotaron sus reintentos.

    Se guardan en MySQL y no en Redis para que sobrevivan a reinicios. El equipo
    de operaciones las revisa (reviewed) y puede reencolarlas desde Admin.
    """

    __bind_key__ = BIND
    __tablename__ = "failed_tasks"
    __table_args__ = (Index("ix_failed_tasks_reviewed_failed", "reviewed", "failed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    queue: Mapped[str | None] = mapped_column(String(50))
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    task_args: Mapped[list | None] = mapped_column(JSON)
    task_kwargs: Mapped[dict | None] = mapped_column(JSON)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    requeued_task_id: Mapped[str | None] = mapped_column(String(255))


# ---------------------------------------------------------------- Gobernanza IA (Cap. 11)
class LLMServiceConfig(AuditMixin, db.Model):
    """Qué modelo usa cada tipo de tarea y su cadena de reserva (patrón LLM Factory).

    Se edita desde Admin sin redesplegar. ``temperature`` se conserva por
    compatibilidad pero no se envía: los modelos Claude 5.x no admiten parámetros
    de muestreo y la profundidad se controla con ``effort`` (ADR-011).
    """

    __bind_key__ = BIND
    __tablename__ = "llm_service_config"

    service_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    fallback_provider: Mapped[str | None] = mapped_column(String(30))
    fallback_model: Mapped[str | None] = mapped_column(String(100))
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    temperature: Mapped[float | None] = mapped_column(Float)
    effort: Mapped[str | None] = mapped_column(String(10))  # low | medium | high
    prompt_name: Mapped[str | None] = mapped_column(String(100))  # prompt principal del servicio
    description: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def targets(self) -> list[dict]:
        chain = [{"provider": self.provider, "model": self.model_name}]
        if self.fallback_provider and self.fallback_model:
            chain.append({"provider": self.fallback_provider, "model": self.fallback_model})
        return chain


class LLMUsageLog(db.Model):
    """Una fila por cada llamada a un LLM, también las fallidas: modelo, tokens,
    coste, latencia, versión del prompt y si la respondió un modelo de reserva."""

    __bind_key__ = BIND
    __tablename__ = "llm_usage_log"
    __table_args__ = (
        Index("ix_llm_usage_service_created", "service_type", "created_at"),
        Index("ix_llm_usage_correlation", "correlation_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    service_type: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("prompts.id"))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(100))
    stop_reason: Mapped[str | None] = mapped_column(String(30))
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64))
    # Agrupa las llamadas de una misma tarea (p. ej. todas las secciones de una propuesta)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    # Primeros 500 caracteres de la respuesta, solo para el escaneo de datos
    # personales; se borran al cumplir la retención (Capítulo 11)
    output_sample: Mapped[str | None] = mapped_column(String(500))
    contained_pii: Mapped[bool | None] = mapped_column(Boolean)
    pii_types: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class LLMModelPricing(TimestampMixin, db.Model):
    """Precio por modelo en USD por millón de tokens (moneda y unidad del proveedor).

    Las filas no se editan: un cambio de precio es una fila nueva con otra fecha de
    efecto, así los costes ya registrados no cambian."""

    __bind_key__ = BIND
    __tablename__ = "llm_model_pricing"

    provider: Mapped[str] = mapped_column(String(30), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    effective_date: Mapped[date] = mapped_column(Date, primary_key=True)
    input_usd_per_mtok: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    output_usd_per_mtok: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    # Lectura y escritura de la caché de prompts. Si faltan: 10 % y 125 % de la entrada.
    cache_read_usd_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    cache_write_usd_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))


class LLMQualityScore(TimestampMixin, db.Model):
    """Puntuaciones de calidad de una respuesta (evaluación automática o persona)."""

    __bind_key__ = BIND
    __tablename__ = "llm_quality_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usage_log_id: Mapped[int] = mapped_column(ForeignKey("llm_usage_log.id"), nullable=False)
    service_type: Mapped[str | None] = mapped_column(String(50), index=True)
    hallucination_score: Mapped[float | None] = mapped_column(Float)
    groundedness_score: Mapped[float | None] = mapped_column(Float)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    coherence_score: Mapped[float | None] = mapped_column(Float)
    completeness_score: Mapped[float | None] = mapped_column(Float)
    faithfulness_score: Mapped[float | None] = mapped_column(Float)
    bias_score: Mapped[float | None] = mapped_column(Float)
    toxicity_score: Mapped[float | None] = mapped_column(Float)
    composite_score: Mapped[float | None] = mapped_column(Float)
    user_rating: Mapped[int | None] = mapped_column(Integer)  # 1-5
    pii_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewer_type: Mapped[str] = mapped_column(String(20), default="automated", nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class Prompt(AuditMixin, db.Model):
    """Prompts versionados en base de datos (CLAUDE.md: nunca en el código).

    Cada cambio crea una versión nueva; solo una versión por nombre está activa.
    ``content_hash`` permite detectar cambios hechos directamente en la base de
    datos, saltándose el versionado (comprobación de integridad, Capítulo 11).
    """

    __bind_key__ = BIND
    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_prompts_name_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    service_type: Mapped[str | None] = mapped_column(String(50))
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(String(500))  # qué cambia en esta versión
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)


class BudgetConfig(AuditMixin, db.Model):
    """Límite de gasto en IA con acciones graduadas: aviso, frenado y bloqueo.

    ``scope``: global (toda la plataforma), service (un tipo de tarea) o user (por
    persona; ``scope_id`` vacío = el mismo límite para cada usuario)."""

    __bind_key__ = BIND
    __tablename__ = "budget_configs"
    __table_args__ = (UniqueConstraint("scope", "scope_id", name="uq_budget_scope"),)

    SCOPES = ("global", "service", "user")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    daily_limit_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    monthly_limit_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    alert_threshold_pct: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    throttle_threshold_pct: Mapped[int] = mapped_column(Integer, default=95, nullable=False)
    block_threshold_pct: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    throttle_delay_seconds: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
