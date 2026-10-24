"""Validación de entrada con Pydantic (Capítulo 7).

Los campos no declarados se rechazan (``extra="forbid"``): un atacante no puede
colar claves arbitrarias que luego se persistan sin control.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from ..models import CVProfile, Opportunity, OpportunityDocument, Proposal, ProposalReview

Str255 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Str500 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
OptStr100 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None
OptStr255 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None
LongText = Annotated[str, StringConstraints(max_length=20000)] | None
Slug = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9_]{1,50}$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Versioned(Schema):
    version: int = Field(ge=1)


# ---------------------------------------------------------------- Clientes
class ClientIn(Schema):
    name: Str255
    tax_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None
    sector: OptStr100 = None
    segment: Literal["A", "B", "C"] | None = None
    risk_level: Literal["low", "medium", "high"] | None = None
    website: OptStr255 = None
    notes: LongText = None
    owner_user_id: int | None = None


class ClientPatch(Versioned):
    name: Str255 | None = None
    tax_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None
    sector: OptStr100 = None
    segment: Literal["A", "B", "C"] | None = None
    risk_level: Literal["low", "medium", "high"] | None = None
    website: OptStr255 = None
    notes: LongText = None
    owner_user_id: int | None = None


class ContactIn(Schema):
    full_name: Str255
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255,
                                            pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")] | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None
    position: Annotated[str, StringConstraints(strip_whitespace=True, max_length=150)] | None = None
    is_primary: bool = False


class ContactPatch(ContactIn, Versioned):
    full_name: Str255 | None = None
    is_primary: bool | None = None


class ProjectIn(Schema):
    name: Str255
    description: LongText = None
    status: Literal["active", "completed", "on_hold", "cancelled"] = "active"
    start_date: date | None = None
    end_date: date | None = None
    budget_eur: Money | None = None


class ProjectPatch(ProjectIn, Versioned):
    name: Str255 | None = None
    status: Literal["active", "completed", "on_hold", "cancelled"] | None = None


# ---------------------------------------------------------------- Oportunidades
OppStatus = Literal[tuple(Opportunity.STATUSES)]  # type: ignore[valid-type]
CpvCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{2,8}(-\d)?$")]


class OpportunityIn(Schema):
    title: Str500
    client_id: int | None = None
    code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None
    source: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = "manual"
    sector: OptStr100 = None
    service_line: OptStr100 = None
    estimated_value_eur: Money | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    deadline: datetime | None = None
    owner_user_id: int | None = None
    description: LongText = None
    contracting_entity: OptStr255 = None
    cpv_codes: list[CpvCode] | None = Field(default=None, max_length=50)


class OpportunityPatch(OpportunityIn, Versioned):
    title: Str500 | None = None
    source: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None


class StatusChange(Versioned):
    status: str
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class LinkDocument(Schema):
    document_id: int
    role: Literal[tuple(OpportunityDocument.ROLES)] = "requirements"  # type: ignore[valid-type]


# ---------------------------------------------------------------- Documentos
RoleCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z_]{2,30}$")]


class DocumentPatch(Versioned):
    title: Str500 | None = None
    doc_type: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None
    # Roles de operaciones que pueden ver el documento; null o [] = cualquiera con documents.read
    allowed_roles: list[RoleCode] | None = Field(default=None, max_length=10)


# ---------------------------------------------------------------- Propuestas
ProposalType = Literal[tuple(Proposal.TYPES)]  # type: ignore[valid-type]


class ProposalIn(Schema):
    opportunity_id: int
    proposal_type: ProposalType = "base"
    template_id: int | None = None
    title: Str500 | None = None
    total_amount_eur: Money | None = None


class ProposalPatch(Versioned):
    title: Str500 | None = None
    total_amount_eur: Money | None = None
    owner_user_id: int | None = None


class SectionIn(Schema):
    key: Slug
    title: Str255
    position: int | None = Field(default=None, ge=0, le=1000)
    edited_content: Annotated[str, StringConstraints(max_length=100000)] | None = None


class SectionPatch(Versioned):
    title: Str255 | None = None
    position: int | None = Field(default=None, ge=0, le=1000)
    edited_content: Annotated[str, StringConstraints(max_length=100000)] | None = None


class ReviewIn(Schema):
    kind: Literal[tuple(ProposalReview.KINDS)]  # type: ignore[valid-type]
    decision: Literal[tuple(ProposalReview.DECISIONS)]  # type: ignore[valid-type]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None


class TemplateSection(Schema):
    key: Slug
    title: Str255
    order: int = Field(ge=0, le=1000)
    guidance: Annotated[str, StringConstraints(max_length=2000)] | None = None


class TemplateIn(Schema):
    name: Str255
    proposal_type: ProposalType
    description: LongText = None
    sections: list[TemplateSection] = Field(min_length=1, max_length=40)

    @field_validator("sections")
    @classmethod
    def unique_keys(cls, sections: list[TemplateSection]):
        keys = [s.key for s in sections]
        if len(keys) != len(set(keys)):
            raise ValueError("Las claves de sección deben ser únicas.")
        return sections


class TemplatePatch(Versioned):
    name: Str255 | None = None
    description: LongText = None
    sections: list[TemplateSection] | None = Field(default=None, min_length=1, max_length=40)

    @field_validator("sections")
    @classmethod
    def unique_keys(cls, sections):
        return TemplateIn.unique_keys(sections) if sections else sections


# ---------------------------------------------------------------- Portfolio
Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
CpvPrefix = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{2,8}$")]


class ServiceLineIn(Schema):
    code: Slug
    name: Str255
    description: LongText = None
    keywords: list[Keyword] = Field(default_factory=list, max_length=100)
    cpv_prefixes: list[CpvPrefix] = Field(default_factory=list, max_length=50)
    owner_user_id: int | None = None


class ServiceLinePatch(Versioned):
    name: Str255 | None = None
    description: LongText = None
    keywords: list[Keyword] | None = Field(default=None, max_length=100)
    cpv_prefixes: list[CpvPrefix] | None = Field(default=None, max_length=50)
    owner_user_id: int | None = None


# ---------------------------------------------------------------- Talento
class SkillIn(Schema):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    level: int | None = Field(default=None, ge=1, le=5)
    years: int | None = Field(default=None, ge=0, le=60)


class ExperienceIn(Schema):
    company: Str255
    role: OptStr255 = None
    start_date: date | None = None
    end_date: date | None = None
    description: LongText = None
    technologies: list[Annotated[str, StringConstraints(max_length=60)]] | None = Field(
        default=None, max_length=50)


class CVProfileIn(Schema):
    full_name: Str255
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255,
                                            pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")] | None = None
    headline: OptStr255 = None
    family: Literal[tuple(CVProfile.FAMILIES)] | None = None  # type: ignore[valid-type]
    seniority: Literal[tuple(CVProfile.SENIORITIES)] | None = None  # type: ignore[valid-type]
    years_experience: int | None = Field(default=None, ge=0, le=60)
    summary: LongText = None
    is_available: bool = True
    skills: list[SkillIn] = Field(default_factory=list, max_length=100)
    experiences: list[ExperienceIn] = Field(default_factory=list, max_length=50)


class CVProfilePatch(CVProfileIn, Versioned):
    full_name: Str255 | None = None
    is_available: bool | None = None
    skills: list[SkillIn] | None = Field(default=None, max_length=100)
    experiences: list[ExperienceIn] | None = Field(default=None, max_length=50)


# ---------------------------------------------------------------- IA (fase 5)
Question = Annotated[str, StringConstraints(min_length=1, max_length=4000)]
PromptText = Annotated[str, StringConstraints(min_length=1, max_length=50000)]
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9._:/\-]{1,100}$")]
PromptName = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$",
                                              max_length=100)]
Provider = Literal["anthropic", "openai_compatible"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
Usd = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=4)]


class ChatTurn(Schema):
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class AskIn(Schema):
    # El guardarraíl de entrada limita la pregunta a 2.000 caracteres con un mensaje claro
    question: Question
    document_ids: list[int] | None = Field(default=None, max_length=50)
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)


class SemanticSearchIn(Schema):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)]
    limit: int = Field(default=10, ge=1, le=20)
    document_ids: list[int] | None = Field(default=None, max_length=50)
    doc_types: list[Annotated[str, StringConstraints(max_length=50)]] | None = Field(default=None, max_length=10)
    include_old_versions: bool = False


class FeedbackIn(Schema):
    usage_log_id: int = Field(ge=1)
    rating: int = Field(ge=1, le=5)
    comment: Annotated[str, StringConstraints(max_length=1000)] | None = None


class GenerateProposalIn(Schema):
    sections: list[Slug] | None = Field(default=None, max_length=30)
    instructions: Annotated[str, StringConstraints(max_length=2000)] | None = None


class PromptPublishIn(Schema):
    name: PromptName
    system_prompt: PromptText
    user_template: Annotated[str, StringConstraints(max_length=50000)] | None = None
    notes: Annotated[str, StringConstraints(max_length=500)] | None = None
    description: Annotated[str, StringConstraints(max_length=500)] | None = None
    service_type: Slug | None = None
    activate: bool = True


class PromptPreviewIn(Schema):
    variables: dict[str, Annotated[str, StringConstraints(max_length=20000)]] = Field(default_factory=dict)


class ServiceConfigPatch(Schema):
    provider: Provider | None = None
    model_name: ModelName | None = None
    fallback_provider: Provider | None = None
    fallback_model: ModelName | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=64000)
    effort: Effort | None = None
    prompt_name: PromptName | None = None
    description: OptStr255 = None
    is_active: bool | None = None


class PricingIn(Schema):
    provider: Provider = "anthropic"
    model_name: ModelName
    effective_date: date
    input_usd_per_mtok: Usd
    output_usd_per_mtok: Usd
    cache_read_usd_per_mtok: Usd | None = None
    cache_write_usd_per_mtok: Usd | None = None


class BudgetIn(Schema):
    scope: Literal["global", "service", "user"]
    scope_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64,
                                               pattern=r"^[a-z0-9_]*$")] = ""
    daily_limit_usd: Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)] | None = None
    monthly_limit_usd: Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)] | None = None
    alert_threshold_pct: int = Field(default=80, ge=1, le=100)
    throttle_threshold_pct: int = Field(default=95, ge=1, le=100)
    block_threshold_pct: int = Field(default=100, ge=1, le=1000)
    throttle_delay_seconds: float = Field(default=2.0, ge=0, le=30)
    is_active: bool = True

    @model_validator(mode="after")
    def _ordered(self):
        if not self.alert_threshold_pct <= self.throttle_threshold_pct <= self.block_threshold_pct:
            raise ValueError("Los umbrales deben ir en orden: aviso <= frenado <= bloqueo.")
        return self


class BaselineIn(Schema):
    task_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    human_time_minutes: float = Field(gt=0, le=10000)
    human_hourly_cost_eur: Annotated[Decimal, Field(ge=0, max_digits=8, decimal_places=2)] = Decimal("65")
