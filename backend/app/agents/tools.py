"""Catálogo de herramientas de los agentes (Capítulo 15).

Cada herramienta declara:

- una descripción prescriptiva (qué hace, cuándo usarla y cuándo NO), que es lo
  que el modelo lee para elegir;
- un esquema de entrada Pydantic (``extra="forbid"``) que se envía al modelo como
  JSON Schema estricto y se vuelve a validar aquí antes de ejecutar;
- el permiso (módulo, acción) y el módulo de IA que exige, comprobados con los
  permisos de la persona: un agente nunca puede más que quien lo usa;
- su nivel mínimo de autonomía. Lo que solo lee puede ser ``auto``; lo que crea
  datos o gasta en IA es ``approve`` siempre (la persona lo confirma), aunque
  una definición de agente pida menos.

Las herramientas son funciones del backend, no comandos libres: no hay shell
ni acceso a ficheros (divergencia consciente del libro, ADR-013). El contenido
que devuelven (documentos, oportunidades) son datos, nunca instrucciones.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from ..api.common import iso, like_pattern, money
from ..errors import BusinessRuleError, NotFoundError
from ..extensions import db
from ..models import (
    CVProfile,
    CVSkill,
    Document,
    Opportunity,
    Proposal,
    ProposalTemplate,
)
from .actor import Actor

LEVELS = ("auto", "notify", "approve")
MAX_RESULT_CHARS = 12000
SearchText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str  # nombre para la persona (tarjeta de aprobación, Agent Studio)
    description: str
    input_model: type[ToolInput]
    permission: tuple[str, str]
    handler: Callable[[Actor, ToolInput], dict]
    min_level: str = "auto"
    ai_module: str | None = None
    extra_permissions: tuple[tuple[str, str], ...] = ()
    summarize: Callable[[ToolInput], str] | None = None

    def allowed_for(self, actor: Actor) -> bool:
        perms = (self.permission, *self.extra_permissions)
        if not all(actor.can(m, a) for m, a in perms):
            return False
        return self.ai_module is None or actor.has_ai(self.ai_module)

    def effective_level(self, requested: str | None) -> str:
        """El nivel de una asignación nunca baja del mínimo de la herramienta."""
        requested = requested if requested in LEVELS else self.min_level
        return max(requested, self.min_level, key=LEVELS.index)

    def api_schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": strict_schema(self.input_model.model_json_schema()), "strict": True}

    def describe(self, data: ToolInput) -> str:
        return self.summarize(data) if self.summarize else self.title

    def catalog_entry(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description,
                "permission": ".".join(self.permission), "ai_module": self.ai_module,
                "min_level": self.min_level, "input_schema": self.api_schema()["input_schema"]}


# Palabras de JSON Schema que el modo estricto no admite: se validan aquí con Pydantic
_UNSUPPORTED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength",
                "maxLength", "minItems", "maxItems", "uniqueItems", "pattern", "title", "default"}


def strict_schema(schema: dict) -> dict:
    """JSON Schema compatible con ``strict: true``: sin restricciones numéricas ni de
    longitud y con ``additionalProperties: false`` en cada objeto."""
    def clean(node):
        if isinstance(node, dict):
            out = {k: clean(v) for k, v in node.items() if k not in _UNSUPPORTED or k == "properties"}
            if "properties" in node:
                out["properties"] = {name: clean(prop) for name, prop in node["properties"].items()}
            if out.get("type") == "object":
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    return clean(schema)


# ------------------------------------------------------------------ Esquemas de entrada
class SearchOpportunitiesIn(ToolInput):
    query: SearchText = Field("", description="Palabras clave, código de expediente o tema. Vacío = sin texto.")
    status: list[str] | None = Field(None, description="Estados del embudo, p. ej. ['new', 'qualified'].",
                                     max_length=12)
    value_min: float | None = Field(None, ge=0, description="Importe estimado mínimo en euros.")
    value_max: float | None = Field(None, ge=0, description="Importe estimado máximo en euros.")
    cpv: list[Annotated[str, StringConstraints(pattern=r"^\d{2,8}$")]] | None = Field(
        None, max_length=10, description="Prefijos CPV de 2 a 8 cifras, p. ej. ['72'].")
    deadline_within_days: int | None = Field(None, ge=0, le=365, description="Cierran en los próximos N días.")
    only_open: bool = Field(False, description="Solo las que siguen abiertas (plazo no vencido).")
    limit: int = Field(8, ge=1, le=10, description="Número de resultados (máximo 10).")


class OpportunityIdIn(ToolInput):
    opportunity_id: int = Field(..., ge=1, description="Id de la oportunidad.")


class DocumentIdIn(ToolInput):
    document_id: int = Field(..., ge=1, description="Id del documento.")


class ProposalIdIn(ToolInput):
    proposal_id: int = Field(..., ge=1, description="Id de la propuesta.")


class SearchDocumentsIn(ToolInput):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)] = Field(
        ..., description="Pregunta o tema que buscar en el contenido de los documentos.")
    document_ids: list[int] | None = Field(None, max_length=20, description="Limitar a estos documentos.")
    limit: int = Field(5, ge=1, le=8, description="Fragmentos a devolver (máximo 8).")


class SearchClientsIn(ToolInput):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)] = Field(
        ..., description="Nombre, CIF o sector del cliente.")


class SearchProfilesIn(ToolInput):
    skills: list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]] | None = Field(
        None, max_length=10, description="Competencias que debe tener (todas), p. ej. ['kubernetes'].")
    family: Literal["cloud", "cyber", "applications", "data", "infrastructure", "management",
                    "consulting"] | None = Field(None, description="Familia profesional.")
    seniority: Literal["JUNIOR", "MID", "SENIOR", "LEAD", "PRINCIPAL", "DIRECTOR"] | None = None
    query: SearchText = Field("", description="Texto libre sobre nombre, titular o resumen.")
    available_only: bool = Field(True, description="Solo perfiles disponibles.")
    limit: int = Field(8, ge=1, le=15)


class CreateProposalIn(ToolInput):
    opportunity_id: int = Field(..., ge=1)
    proposal_type: Literal["base", "competitive", "premium", "custom", "executive"] = Field(
        "base", description="Tipo de propuesta; determina las secciones y las revisiones.")
    template_id: int | None = Field(None, ge=1, description="Plantilla (de list_proposal_templates).")
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class GenerateProposalToolIn(ToolInput):
    proposal_id: int = Field(..., ge=1)
    sections: list[Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,50}$")]] | None = Field(
        None, max_length=30, description="Claves de sección a redactar. Vacío = las no editadas a mano.")
    instructions: Annotated[str, StringConstraints(max_length=1000)] | None = Field(
        None, description="Indicaciones de la persona para la redacción.")


class GenerateCVIn(ToolInput):
    profile_id: int = Field(..., ge=1, description="Perfil del equipo (de search_profiles).")
    proposal_id: int = Field(..., ge=1, description="Propuesta a la que se adjunta el CV.")


# ------------------------------------------------------------------ Lectura
def _opp_brief(o: Opportunity) -> dict:
    return {"id": o.id, "code": o.code, "title": o.title, "status": o.status,
            "client": o.client.name if o.client else o.contracting_entity,
            "estimated_value_eur": money(o.estimated_value_eur), "deadline": iso(o.deadline),
            "relevance_score": float(o.relevance_score) if o.relevance_score is not None else None}


def search_opportunities(actor: Actor, data: SearchOpportunitiesIn) -> dict:
    from ..api.schemas import OpportunitySearchIn
    from ..search import engine

    params = OpportunitySearchIn(q=data.query, status=data.status or None, value_min=data.value_min,
                                 value_max=data.value_max, cpv=data.cpv or None,
                                 deadline_within_days=data.deadline_within_days, only_open=data.only_open,
                                 per_page=data.limit, facets=False)
    page = engine.search_opportunities(params, actor.user_id)
    items = [{k: i.get(k) for k in ("id", "code", "title", "status", "client_name", "estimated_value_eur",
                                     "deadline", "relevance_score")} for i in page.items]
    return {"total": page.total, "items": items}


def _visible_opportunity(opportunity_id: int) -> Opportunity:
    opp = db.session.get(Opportunity, opportunity_id)
    if opp is None or not opp.is_active:
        raise NotFoundError(f"No existe la oportunidad {opportunity_id}.")
    return opp


def get_opportunity(actor: Actor, data: OpportunityIdIn) -> dict:
    o = _visible_opportunity(data.opportunity_id)
    viewer = actor.viewer
    docs = [{"document_id": link.document_id, "title": link.document.title, "role": link.role}
            for link in o.documents
            if link.is_active and link.document.is_active and viewer.can_view(link.document)]
    proposals = [{"id": p.id, "title": p.title, "type": p.proposal_type, "status": p.status}
                 for p in o.proposals if p.is_active] if actor.can("proposals", "read") else []
    extra = o.extra_data or {}
    return {**_opp_brief(o), "description": (o.description or "")[:3000], "sector": o.sector,
            "contracting_entity": o.contracting_entity, "cpv_codes": o.cpv_codes or [],
            "service_line": o.service_line, "published_at": iso(o.published_at),
            "go_no_go": extra.get("go_no_go"), "ai_summary": o.ai_summary, "documents": docs,
            "proposals": proposals}


def search_documents(actor: Actor, data: SearchDocumentsIn) -> dict:
    from ..ai import rag

    hits = rag.search(actor.viewer, data.query, limit=data.limit, document_ids=data.document_ids)
    return {"passages": [{"n": n, "document_id": h.document.id, "title": h.document.title,
                          "doc_type": h.document.doc_type, "page": h.page, "text": h.parent_text(1500)}
                         for n, h in enumerate(hits[:data.limit], start=1)]}


def get_document(actor: Actor, data: DocumentIdIn) -> dict:
    d = db.session.get(Document, data.document_id)
    if d is None or not d.is_active or not actor.viewer.can_view(d):
        raise NotFoundError(f"No existe el documento {data.document_id} o no tienes acceso.")
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type, "version": d.version_number,
            "processing_status": d.processing_status, "summary": d.ai_summary, "keywords": d.ai_keywords or [],
            "entities": d.ai_entities or {}, "characters": len(d.extracted_text or ""),
            "beginning": (d.extracted_text or "")[:2500]}


def search_clients(actor: Actor, data: SearchClientsIn) -> dict:
    from ..models import Client

    pattern = like_pattern(data.query)
    rows = db.session.scalars(Client.select_active().where(or_(
        Client.name.like(pattern, escape="\\"), Client.tax_id.like(pattern, escape="\\"),
        Client.sector.like(pattern, escape="\\"))).order_by(Client.name).limit(10)).all()
    return {"items": [{"id": c.id, "name": c.name, "sector": c.sector, "segment": c.segment} for c in rows]}


def search_profiles(actor: Actor, data: SearchProfilesIn) -> dict:
    stmt = CVProfile.select_active().options(selectinload(CVProfile.skills))
    if data.available_only:
        stmt = stmt.where(CVProfile.is_available.is_(True))
    if data.family:
        stmt = stmt.where(CVProfile.family == data.family)
    if data.seniority:
        stmt = stmt.where(CVProfile.seniority == data.seniority)
    if pattern := like_pattern(data.query):
        stmt = stmt.where(or_(CVProfile.full_name.like(pattern, escape="\\"),
                              CVProfile.headline.like(pattern, escape="\\"),
                              CVProfile.summary.like(pattern, escape="\\")))
    for skill in data.skills or []:
        stmt = stmt.where(CVProfile.id.in_(db.select(CVSkill.profile_id).where(
            CVSkill.is_active.is_(True), db.func.lower(CVSkill.name) == skill.lower())))
    rows = db.session.scalars(stmt.order_by(CVProfile.years_experience.desc(), CVProfile.id).limit(data.limit))
    # Sin email ni datos de contacto: el modelo no los necesita
    return {"items": [{"id": p.id, "name": p.full_name, "headline": p.headline, "family": p.family,
                       "seniority": p.seniority, "years_experience": p.years_experience,
                       "skills": [s.name for s in p.skills if s.is_active][:15]} for p in rows]}


def _proposal(proposal_id: int) -> Proposal:
    p = db.session.get(Proposal, proposal_id)
    if p is None or not p.is_active:
        raise NotFoundError(f"No existe la propuesta {proposal_id}.")
    return p


def get_proposal(actor: Actor, data: ProposalIdIn) -> dict:
    p = _proposal(data.proposal_id)
    return {"id": p.id, "title": p.title, "type": p.proposal_type, "status": p.status,
            "opportunity_id": p.opportunity_id, "generation_status": p.generation_status,
            "sections": [{"key": s.key, "title": s.title, "edited_by_person": s.edited_content is not None,
                          "text": (s.final_content or "")[:1500]}
                         for s in sorted(p.sections, key=lambda s: s.position) if s.is_active],
            "attachments": [{"kind": a.kind, "filename": a.filename} for a in p.attachments if a.is_active]}


def list_proposal_templates(actor: Actor, data: ToolInput) -> dict:
    rows = db.session.scalars(ProposalTemplate.select_active().order_by(ProposalTemplate.id))
    return {"items": [{"id": t.id, "name": t.name, "proposal_type": t.proposal_type,
                       "sections": [s.get("title") for s in t.sections or []]} for t in rows]}


# ------------------------------------------------------------------ Acciones (siempre con aprobación)
def analyze_opportunity(actor: Actor, data: OpportunityIdIn) -> dict:
    from ..ai import analysis
    from ..queue import PRIORITY_USER, enqueue
    from ..tasks.ai import analyze

    opp = _visible_opportunity(data.opportunity_id)
    if not (opp.description or "").strip() and not any(link.is_active for link in opp.documents):
        raise BusinessRuleError("Añade una descripción o vincula el pliego antes de analizar.")
    a = analysis.create("opportunity", opp.id, actor.user_id)
    enqueue(analyze, a.id, priority=PRIORITY_USER)
    return {"analysis_id": a.id, "status": "queued",
            "message": "Análisis GO/NO-GO lanzado; tardará unos minutos y aparecerá en la oportunidad."}


def analyze_document(actor: Actor, data: DocumentIdIn) -> dict:
    from ..ai import analysis
    from ..queue import PRIORITY_USER, enqueue
    from ..tasks.ai import analyze

    d = db.session.get(Document, data.document_id)
    if d is None or not d.is_active or not actor.viewer.can_view(d):
        raise NotFoundError(f"No existe el documento {data.document_id} o no tienes acceso.")
    if d.processing_status != "processed" or not d.extracted_text:
        raise BusinessRuleError("El documento todavía no tiene texto extraído.")
    a = analysis.create("document", d.id, actor.user_id)
    enqueue(analyze, a.id, priority=PRIORITY_USER)
    return {"analysis_id": a.id, "status": "queued"}


def create_proposal(actor: Actor, data: CreateProposalIn) -> dict:
    from ..models import AuditAction
    from ..security.audit import audit
    from ..services import proposals as service

    opp = _visible_opportunity(data.opportunity_id)
    template = None
    if data.template_id is not None:
        template = db.session.get(ProposalTemplate, data.template_id)
        if template is None or not template.is_active:
            raise NotFoundError("La plantilla no existe.")
    p = service.create(opp, proposal_type=data.proposal_type, template=template, title=data.title,
                       total_amount_eur=None, user_id=actor.user_id)
    audit(AuditAction.RECORD_CREATED, "INFO", user_id=actor.user_id, resource_type="proposals",
          resource_id=p.id, details={"opportunity_id": opp.id, "via": "agent"})
    return {"proposal_id": p.id, "title": p.title, "status": p.status,
            "sections": [s.key for s in p.sections]}


def generate_proposal(actor: Actor, data: GenerateProposalToolIn) -> dict:
    from ..services import proposals as service

    p = _proposal(data.proposal_id)
    actor.ensure_can_modify("proposals", p)
    targets = service.start_generation(p, actor.user_id, data.sections, data.instructions)
    return {"proposal_id": p.id, "generation_status": p.generation_status, "sections": [s.key for s in targets],
            "message": "Redacción en marcha; cada sección aparece en la propuesta al terminar."}


def generate_cv(actor: Actor, data: GenerateCVIn) -> dict:
    from ..ai import cv_tailoring

    p = _proposal(data.proposal_id)
    actor.ensure_can_modify("proposals", p)
    profile = db.session.get(CVProfile, data.profile_id)
    if profile is None or not profile.is_active:
        raise NotFoundError(f"No existe el perfil {data.profile_id}.")
    cv_tailoring.request(p, profile, actor.user_id)
    return {"proposal_id": p.id, "profile_id": profile.id, "status": "queued",
            "message": "CV adaptado en preparación; se adjuntará a la propuesta en DOCX y PDF."}


def export_proposal(actor: Actor, data: ProposalIdIn) -> dict:
    from ..queue import PRIORITY_USER, enqueue
    from ..tasks.proposals import generate_package

    p = _proposal(data.proposal_id)
    actor.ensure_can_modify("proposals", p)
    if p.status not in ("approved", "sent", "won", "lost"):
        raise BusinessRuleError("El paquete se genera cuando la propuesta está aprobada.")
    enqueue(generate_package, p.id, priority=PRIORITY_USER)
    return {"proposal_id": p.id, "status": "queued",
            "message": "Paquete en preparación: DOCX, PDF y presentación PPTX."}


def _opp_title(opportunity_id: int) -> str:
    o = db.session.get(Opportunity, opportunity_id)
    return f"«{o.title[:80]}»" if o is not None else f"#{opportunity_id}"


def _proposal_title(proposal_id: int) -> str:
    p = db.session.get(Proposal, proposal_id)
    return f"«{p.title[:80]}»" if p is not None else f"#{proposal_id}"


# ------------------------------------------------------------------ Registro
TOOLS: dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec(
        "search_opportunities", "Buscar oportunidades",
        "Busca oportunidades de negocio (licitaciones y contratos) por texto, estado, importe, CPV o plazo. "
        "Úsala para encontrar o filtrar oportunidades y obtener sus ids. Devuelve un resumen de cada una. "
        "NO usar para leer el detalle de una oportunidad concreta (usa get_opportunity) ni para buscar "
        "dentro del texto de los documentos (usa search_documents).",
        SearchOpportunitiesIn, ("opportunities", "read"), search_opportunities),
    ToolSpec(
        "get_opportunity", "Ver una oportunidad",
        "Devuelve el detalle de una oportunidad por su id: descripción, cliente, importes, plazos, CPV, "
        "resultado del análisis GO/NO-GO si existe, documentos vinculados y propuestas. "
        "NO usar para buscar oportunidades (usa search_opportunities).",
        OpportunityIdIn, ("opportunities", "read"), get_opportunity),
    ToolSpec(
        "search_documents", "Buscar en los documentos",
        "Busca por significado dentro del contenido de los documentos que la persona puede ver (pliegos, "
        "contratos, propuestas anteriores, CV) y devuelve los fragmentos más relevantes numerados, con su "
        "documento. Úsala para responder preguntas con datos de los documentos y cítalos. "
        "NO usar para listar documentos por título ni para buscar oportunidades.",
        SearchDocumentsIn, ("documents", "read"), search_documents),
    ToolSpec(
        "get_document", "Ver un documento",
        "Devuelve los metadatos de un documento por su id: tipo, resumen, palabras clave, entidades y el "
        "comienzo del texto. NO usar para buscar información dentro de varios documentos (usa search_documents).",
        DocumentIdIn, ("documents", "read"), get_document),
    ToolSpec(
        "search_clients", "Buscar clientes",
        "Busca clientes por nombre, CIF o sector y devuelve su id, sector y segmento. "
        "NO usar para buscar oportunidades de un cliente (usa search_opportunities con su nombre).",
        SearchClientsIn, ("clients", "read"), search_clients),
    ToolSpec(
        "search_profiles", "Buscar perfiles del equipo",
        "Busca perfiles profesionales del equipo interno por competencias, familia, seniority o texto, para "
        "proponer personas en una propuesta. No devuelve datos de contacto. "
        "NO usar para buscar clientes ni contactos externos.",
        SearchProfilesIn, ("talent", "read"), search_profiles),
    ToolSpec(
        "get_proposal", "Ver una propuesta",
        "Devuelve una propuesta por su id: tipo, estado, secciones con su texto (recortado) y adjuntos. "
        "NO usar para crear ni redactar propuestas.",
        ProposalIdIn, ("proposals", "read"), get_proposal),
    ToolSpec(
        "list_proposal_templates", "Ver plantillas de propuesta",
        "Lista las plantillas de propuesta disponibles con su tipo y secciones. Úsala antes de create_proposal "
        "si la persona pide un tipo o plantilla concreta. NO usar para ver propuestas existentes.",
        ToolInput, ("templates", "read"), list_proposal_templates),
    ToolSpec(
        "analyze_opportunity", "Analizar una oportunidad (GO/NO-GO)",
        "Lanza en segundo plano el análisis GO/NO-GO con IA de una oportunidad y sus documentos. Tiene coste y "
        "la persona debe confirmarlo. Úsala solo si la persona pide analizar o decidir si presentarse. "
        "NO usar si la oportunidad ya tiene un análisis reciente (míralo con get_opportunity) salvo que lo pidan.",
        OpportunityIdIn, ("opportunities", "write"), analyze_opportunity, min_level="approve",
        ai_module="document_analyzer",
        summarize=lambda d: f"Analizar (GO/NO-GO) la oportunidad {_opp_title(d.opportunity_id)}"),
    ToolSpec(
        "analyze_document", "Analizar un documento (GO/NO-GO)",
        "Lanza en segundo plano el análisis GO/NO-GO con IA de un documento (normalmente un pliego). Tiene coste "
        "y la persona debe confirmarlo. NO usar para responder preguntas sobre el documento (usa search_documents).",
        DocumentIdIn, ("documents", "read"), analyze_document, min_level="approve", ai_module="document_analyzer",
        summarize=lambda d: f"Analizar (GO/NO-GO) el documento #{d.document_id}"),
    ToolSpec(
        "create_proposal", "Crear una propuesta",
        "Crea una propuesta en borrador para una oportunidad, con las secciones de su tipo o plantilla. No redacta "
        "el texto (después usa generate_proposal). La persona debe confirmarlo. "
        "NO usar si la oportunidad ya tiene una propuesta en borrador (compruébalo con get_opportunity).",
        CreateProposalIn, ("proposals", "write"), create_proposal, min_level="approve",
        summarize=lambda d: f"Crear una propuesta ({d.proposal_type}) para {_opp_title(d.opportunity_id)}"),
    ToolSpec(
        "generate_proposal", "Redactar una propuesta con IA",
        "Redacta con IA, en segundo plano, las secciones de una propuesta en borrador (por defecto las que nadie "
        "ha editado a mano). Tiene coste y la persona debe confirmarlo. NO usar para propuestas que no estén en "
        "borrador ni para reescribir secciones editadas a mano salvo que la persona lo pida.",
        GenerateProposalToolIn, ("proposals", "write"), generate_proposal, min_level="approve",
        ai_module="proposal_generator",
        summarize=lambda d: f"Redactar con IA la propuesta {_proposal_title(d.proposal_id)}"),
    ToolSpec(
        "generate_cv", "Preparar un CV a medida",
        "Prepara con IA un CV del perfil adaptado a la oportunidad de la propuesta (DOCX y PDF) y lo adjunta a la "
        "propuesta. Tiene coste y la persona debe confirmarlo. Usa antes search_profiles para elegir el perfil. "
        "NO usar para modificar el perfil original.",
        GenerateCVIn, ("proposals", "write"), generate_cv, min_level="approve", ai_module="proposal_generator",
        extra_permissions=(("talent", "read"),),
        summarize=lambda d: (f"Preparar el CV a medida del perfil #{d.profile_id} "
                             f"para {_proposal_title(d.proposal_id)}")),
    ToolSpec(
        "export_proposal", "Generar el paquete de la propuesta",
        "Genera el paquete final de una propuesta aprobada: documento Word, PDF y presentación PowerPoint. "
        "La persona debe confirmarlo. NO usar si la propuesta no está aprobada.",
        ProposalIdIn, ("proposals", "write"), export_proposal, min_level="approve",
        summarize=lambda d: f"Generar el paquete (DOCX, PDF y PPTX) de {_proposal_title(d.proposal_id)}"),
]}

MAX_TOOLS_PER_AGENT = 12


def get(name: str) -> ToolSpec | None:
    return TOOLS.get(name)


def catalog() -> list[dict]:
    return [t.catalog_entry() for t in TOOLS.values()]
