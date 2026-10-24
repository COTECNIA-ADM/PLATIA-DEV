"""Esquema operations_db: datos de negocio del caso B2B.

Dominios (Apéndice A): clientes, proyectos y oportunidades, propuestas,
documentos, talento (CV) y alertas. Todo con borrado lógico y auditoría.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import BusinessMixin, VersionedMixin

BIND = "operations"


# ---------------------------------------------------------------- Clientes
class Client(VersionedMixin, BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "clients"

    SEGMENTS = ("A", "B", "C")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tax_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    sector: Mapped[str | None] = mapped_column(String(100))
    segment: Mapped[str | None] = mapped_column(String(1))
    risk_level: Mapped[str | None] = mapped_column(String(20))
    website: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[int | None] = mapped_column(Integer, index=True)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="client")
    projects: Mapped[list["Project"]] = relationship(back_populates="client")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="client")


class Contact(VersionedMixin, BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    position: Mapped[str | None] = mapped_column(String(150))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    client: Mapped[Client] = relationship(back_populates="contacts")


# ---------------------------------------------------------------- Proyectos y oportunidades
class Project(VersionedMixin, BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "projects"

    STATUSES = ("active", "completed", "on_hold", "cancelled")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    budget_eur: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    client: Mapped[Client] = relationship(back_populates="projects")


class Opportunity(VersionedMixin, BusinessMixin, db.Model):
    """Oportunidad de negocio. Doce estados agrupados en cinco fases del embudo."""

    __bind_key__ = BIND
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opportunities_status_deadline", "status", "deadline"),
        UniqueConstraint("source", "external_id", name="uq_opportunities_source_external"),
    )

    # estado -> fase del embudo (F1 detección ... F5 cierre)
    STATUS_PHASE = {
        "detected": "F1",
        "qualifying": "F1",
        "qualified": "F2",
        "analyzing": "F2",
        "go_no_go": "F3",
        "preparing_proposal": "F3",
        "proposal_review": "F4",
        "proposal_sent": "F4",
        "negotiation": "F4",
        "won": "F5",
        "lost": "F5",
        "discarded": "F5",
    }
    STATUSES = tuple(STATUS_PHASE)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(50), unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="detected", nullable=False)
    source: Mapped[str | None] = mapped_column(String(50))  # licitación, contacto directo...
    sector: Mapped[str | None] = mapped_column(String(100))
    service_line: Mapped[str | None] = mapped_column(String(100))
    estimated_value_eur: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    probability: Mapped[int | None] = mapped_column(Integer)  # 0-100
    deadline: Mapped[datetime | None] = mapped_column(DateTime)
    owner_user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    ai_score: Mapped[int | None] = mapped_column(Integer)  # encaje con el portfolio, 0-100
    ai_summary: Mapped[str | None] = mapped_column(Text)
    extra_data: Mapped[dict | None] = mapped_column(JSON)

    # Motor de oportunidades (Capítulo 9): origen externo, deduplicación y relevancia
    external_id: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    contracting_entity: Mapped[str | None] = mapped_column(String(255))
    cpv_codes: Mapped[list | None] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))  # 0-10
    scored_at: Mapped[datetime | None] = mapped_column(DateTime)

    client: Mapped[Client | None] = relationship(back_populates="opportunities")
    documents: Mapped[list["OpportunityDocument"]] = relationship(back_populates="opportunity")
    proposals: Mapped[list["Proposal"]] = relationship(back_populates="opportunity")

    @property
    def funnel_phase(self) -> str:
        return self.STATUS_PHASE.get(self.status, "F1")


# ---------------------------------------------------------------- Documentos
class Document(VersionedMixin, BusinessMixin, db.Model):
    """Documento con versionado y enriquecimiento por IA."""

    __bind_key__ = BIND
    __tablename__ = "documents"

    PROCESSING_STATUSES = ("pending", "processing", "processed", "failed")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_type: Mapped[str | None] = mapped_column(String(50), index=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    storage_path: Mapped[str | None] = mapped_column(String(500))
    file_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # SHA-256
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)

    # Versionado
    parent_version_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current_version: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Procesamiento IA
    processing_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    processing_error: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text().with_variant(mysql.LONGTEXT(), "mysql"))
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_keywords: Mapped[list | None] = mapped_column(JSON)
    ai_entities: Mapped[dict | None] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))

    parent_version: Mapped["Document | None"] = relationship(remote_side=[id])


class OpportunityDocument(BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "opportunity_documents"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "document_id", name="uq_opportunity_document"),
    )

    ROLES = ("requirements", "annex", "budget", "other")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="requirements", nullable=False)

    opportunity: Mapped[Opportunity] = relationship(back_populates="documents")
    document: Mapped[Document] = relationship()


# ---------------------------------------------------------------- Propuestas
class ProposalTemplate(VersionedMixin, BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "proposal_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Estructura de secciones: [{"key": "resumen", "title": "...", "order": 1}, ...]
    sections: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str | None] = mapped_column(Text)


class Proposal(VersionedMixin, BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "proposals"

    TYPES = ("base", "competitive", "premium", "custom", "executive")
    # Máquina de estados en services/proposals.py (Capítulo 9)
    STATUSES = ("draft", "in_review", "approved", "sent", "won", "lost", "archived")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id"), nullable=False, index=True
    )
    template_id: Mapped[int | None] = mapped_column(ForeignKey("proposal_templates.id"))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(20), default="base", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    total_amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    reviewed_by: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    owner_user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    # Cada vez que entra en revisión empieza una ronda nueva: las aprobaciones de
    # rondas anteriores no cuentan
    review_round: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)

    opportunity: Mapped[Opportunity] = relationship(back_populates="proposals")
    template: Mapped[ProposalTemplate | None] = relationship()
    sections: Mapped[list["ProposalSection"]] = relationship(
        back_populates="proposal", order_by="ProposalSection.position"
    )
    attachments: Mapped[list["ProposalAttachment"]] = relationship(back_populates="proposal")
    reviews: Mapped[list["ProposalReview"]] = relationship(back_populates="proposal")


class ProposalSection(VersionedMixin, BusinessMixin, db.Model):
    """Sección de propuesta: lo que generó la IA y lo que editó la persona, por separado."""

    __bind_key__ = BIND
    __tablename__ = "proposal_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ai_content: Mapped[str | None] = mapped_column(Text)
    edited_content: Mapped[str | None] = mapped_column(Text)
    llm_usage_log_id: Mapped[int | None] = mapped_column(BigInteger)  # platform_core.llm_usage_log

    proposal: Mapped[Proposal] = relationship(back_populates="sections")

    @property
    def final_content(self) -> str | None:
        return self.edited_content if self.edited_content is not None else self.ai_content


class ProposalAttachment(BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "proposal_attachments"

    KINDS = ("competitive_analysis", "generated", "other")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), default="other", server_default="other", nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)

    proposal: Mapped[Proposal] = relationship(back_populates="attachments")


class ProposalReview(BusinessMixin, db.Model):
    """Revisión de una propuesta en una ronda. Las premium y ejecutivas necesitan
    una técnica y una ejecutiva; las custom, la del responsable de área."""

    __bind_key__ = BIND
    __tablename__ = "proposal_reviews"

    KINDS = ("technical", "executive", "area", "general")
    DECISIONS = ("approve", "reject")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), nullable=False, index=True)
    review_round: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewer_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)

    proposal: Mapped[Proposal] = relationship(back_populates="reviews")


# ---------------------------------------------------------------- Portfolio de servicios
class ServiceLine(VersionedMixin, BusinessMixin, db.Model):
    """Línea de servicio del portfolio: contra ella se puntúan las oportunidades.

    En la fase 4 la relevancia usa palabras clave y códigos CPV; en la fase 5 se
    añade la similitud semántica con Qdrant (Capítulo 9).
    """

    __bind_key__ = BIND
    __tablename__ = "service_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    cpv_prefixes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    owner_user_id: Mapped[int | None] = mapped_column(Integer)  # a quién avisar


# ---------------------------------------------------------------- Talento (CV)
class CVProfile(VersionedMixin, BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "cv_profiles"

    FAMILIES = ("cloud", "cyber", "applications", "data", "infrastructure", "management", "consulting")
    SENIORITIES = ("JUNIOR", "MID", "SENIOR", "LEAD", "PRINCIPAL", "DIRECTOR")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    headline: Mapped[str | None] = mapped_column(String(255))
    family: Mapped[str | None] = mapped_column(String(30), index=True)
    seniority: Mapped[str | None] = mapped_column(String(20))
    years_experience: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    skills: Mapped[list["CVSkill"]] = relationship(back_populates="profile")
    experiences: Mapped[list["CVExperience"]] = relationship(back_populates="profile")


class CVSkill(BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "cv_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("cv_profiles.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    level: Mapped[int | None] = mapped_column(Integer)  # 1-5
    years: Mapped[int | None] = mapped_column(Integer)

    profile: Mapped[CVProfile] = relationship(back_populates="skills")


class CVExperience(BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "cv_experiences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("cv_profiles.id"), nullable=False, index=True)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    technologies: Mapped[list | None] = mapped_column(JSON)

    profile: Mapped[CVProfile] = relationship(back_populates="experiences")


# ---------------------------------------------------------------- Alertas y notificaciones
class Alert(BusinessMixin, db.Model):
    """Alerta proactiva, p. ej. una oportunidad que encaja con el portfolio."""

    __bind_key__ = BIND
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    score: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class Notification(BusinessMixin, db.Model):
    __bind_key__ = BIND
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    TYPES = (
        "NEW_OPPORTUNITY",
        "DEAL_STALLED",
        "ACCOUNT_RISK",
        "REPORT_READY",
        "OPPORTUNITY_MATCH",
        "SYSTEM",
    )
    PRIORITIES = ("low", "normal", "high", "urgent")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)  # platform_core.users
    notification_type: Mapped[str] = mapped_column(String(30), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), default="normal", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))  # enlace profundo en el frontal
    extra_data: Mapped[dict | None] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
