"""Modelos de la plataforma, agrupados por esquema (bind)."""
from . import analytics, core, operations  # noqa: F401  (registra todas las tablas)
from .analytics import AnalyticsSnapshot, DashboardConfig, FunnelStage
from .base import utcnow
from .core import (
    App,
    AppRole,
    AuditLog,
    LLMModelPricing,
    LLMQualityScore,
    LLMServiceConfig,
    LLMUsageLog,
    Prompt,
    User,
    UserAppMembership,
)
from .operations import (
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
    ProposalSection,
    ProposalTemplate,
)

__all__ = [name for name in dir() if name[0].isupper()] + ["utcnow"]
