"""Modelos de la plataforma, agrupados por esquema (bind)."""
from . import analytics, core, operations  # noqa: F401  (registra todas las tablas)
from .analytics import (AnalyticsSnapshot, BusinessTarget, CompetitorProfile, DashboardConfig, FunnelStage,
                        HeatmapConfig, HeatmapScore, HumanBaselineConfig, TaskCompletionLog)
from .base import utcnow
from .core import (
    App,
    AppRole,
    AuditAction,
    AgentDefinition,
    AgentDefinitionVersion,
    AgentRun,
    AgentToolAssignment,
    AuditLog,
    BudgetConfig,
    FailedTask,
    IntentPattern,
    LLMModelPricing,
    LLMQualityScore,
    LLMServiceConfig,
    LLMUsageLog,
    Prompt,
    SearchQueryLog,
    User,
    UserAppMembership,
    UserMemory,
    UserSession,
)
from .operations import (
    AIAnalysis,
    Alert,
    ChatConversation,
    ChatMessage,
    Client,
    Contact,
    CVExperience,
    CVProfile,
    CVSkill,
    Document,
    Notification,
    Opportunity,
    OpportunityDocument,
    OpportunityStatusChange,
    Project,
    Proposal,
    ProposalAttachment,
    ProposalReview,
    ProposalSection,
    ProposalTemplate,
    ServiceLine,
)

__all__ = [name for name in dir() if name[0].isupper()] + ["utcnow"]
