"""Validación de entrada con Pydantic (Capítulo 7).

Los campos no declarados se rechazan (``extra="forbid"``): un atacante no puede
colar claves arbitrarias que luego se persistan sin control.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

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
class DocumentPatch(Versioned):
    title: Str500 | None = None
    doc_type: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None


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
