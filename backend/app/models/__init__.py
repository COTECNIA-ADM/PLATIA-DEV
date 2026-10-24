"""Modelos de la plataforma, agrupados por esquema (bind)."""
from . import analytics, core, operations  # noqa: F401  (registra todas las tablas)
from .analytics import AnalyticsSnapshot, DashboardConfig, FunnelStage, HumanBaselineConfig, TaskCompletionLog
from .base import utcnow
from .core import (
    App,
    AppRole,
    AuditAction,
    AuditLog,
    BudgetConfig,
    FailedTask,
    LLMModelPricing,
    LLMQualityScore,
    LLMServiceConfig,
    LLMUsageLog,
    Prompt,
    User,
    UserAppMembership,
    UserSession,
)
from .operations import (
    AIAnalysis,
    Alert,
    Client,
    Contact,
    CVExperience,
    CVProfile,
    CVSkill,
    Document,
    Notification,
    Opportunity,
    OpportunityDocument,
    Project,
    Proposal,
    ProposalAttachment,
    ProposalReview,
    ProposalSection,
    ProposalTemplate,
    ServiceLine,
)

__all__ = [name for name in dir() if name[0].isupper()] + ["utcnow"]
