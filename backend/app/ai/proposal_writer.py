"""Redacción de propuestas con IA, sección a sección (Capítulo 10).

Para cada sección se busca en los documentos vinculados a la oportunidad (y,
si no hay, en todos los que puede ver el responsable) el contexto más
relevante, y se redacta con el modelo principal. El texto va a ``ai_content``:
lo que la persona haya editado (``edited_content``) no se toca nunca.

Todas las llamadas de una misma redacción comparten ``correlation_id``, así el
coste total de la propuesta se puede consultar de una vez.
"""
import time
import uuid

import structlog

from ..extensions import db
from ..models import OpportunityDocument, Proposal, ProposalSection, utcnow
from . import analysis as analysis_service
from . import gateway, rag, roi
from .access import Viewer
from .errors import AIUnavailableError
from .schemas import PROPOSAL_SECTION

log = structlog.get_logger(__name__)
SECTION_MAX_TOKENS = 6000


def _opportunity_brief(proposal: Proposal) -> str:
    opp = proposal.opportunity
    lines = [f"Oportunidad: {opp.title}"]
    if opp.client is not None:
        lines.append(f"Cliente: {opp.client.name}")
    for label, value in (("Organismo", opp.contracting_entity), ("Sector", opp.sector),
                         ("Línea de servicio", opp.service_line), ("Importe estimado (EUR)", opp.estimated_value_eur),
                         ("Plazo", opp.deadline and opp.deadline.date().isoformat())):
        if value:
            lines.append(f"{label}: {value}")
    if opp.description:
        lines.append(f"Descripción: {opp.description[:4000]}")
    return "\n".join(lines)


def _analysis_brief(proposal: Proposal) -> str:
    a = analysis_service.latest("opportunity", proposal.opportunity_id)
    if a is None or a.status != "done" or not a.result:
        return "(no hay análisis GO/NO-GO de esta oportunidad)"
    r = a.result
    reqs = "\n".join(f"- [{q.get('kind')}] {q.get('requirement')} → {q.get('meets')}" for q in r.get("requirements", [])[:25])
    risks = "\n".join(f"- ({x.get('severity')}) {x.get('description')}" for x in r.get("risks", [])[:10])
    return f"Veredicto: {a.verdict}\nResumen: {r.get('summary', '')}\nRequisitos:\n{reqs}\nRiesgos:\n{risks}"


def sections_to_write(proposal: Proposal, keys: list[str] | None) -> list[ProposalSection]:
    active = sorted((s for s in proposal.sections if s.is_active), key=lambda s: s.position)
    if keys:
        return [s for s in active if s.key in keys]
    # Por defecto, solo las que nadie ha editado a mano
    return [s for s in active if s.edited_content is None]


def generate(proposal: Proposal, user_id: int | None, keys: list[str] | None = None,
             instructions: str | None = None) -> dict:
    """Redacta las secciones. Hace commit tras cada sección para que se vea el avance."""
    started = time.monotonic()
    correlation_id = str(uuid.uuid4())
    viewer = Viewer.for_user(user_id)
    linked = [link.document_id for link in db.session.scalars(
        db.select(OpportunityDocument).filter_by(opportunity_id=proposal.opportunity_id, is_active=True))]
    brief, analysis_text = _opportunity_brief(proposal), _analysis_brief(proposal)
    written, previous = [], []
    for section in sections_to_write(proposal, keys):
        try:
            hits = rag.search(viewer, f"{section.title}. {proposal.opportunity.title}", limit=5,
                              document_ids=linked or None)
        except AIUnavailableError:
            hits = []
        result = gateway.run(
            "proposal_generation", prompt_name="proposal.section",
            variables={"proposal_title": proposal.title, "proposal_type": proposal.proposal_type,
                       "section_title": section.title, "section_key": section.key, "opportunity": brief,
                       "analysis": analysis_text, "sources": rag.format_sources(hits, 2500) or "(sin documentos)",
                       "previous_sections": "\n".join(previous)[-6000:] or "(es la primera sección)",
                       "instructions": (instructions or "").strip()[:2000] or "(ninguna)"},
            user_id=user_id, json_schema=PROPOSAL_SECTION, correlation_id=correlation_id,
            max_tokens=SECTION_MAX_TOKENS)
        data = result.data if isinstance(result.data, dict) else {"content": result.text}
        section.ai_content = (data.get("content") or "").strip() or None
        section.llm_usage_log_id = result.usage_log_id
        db.session.commit()
        previous.append(f"## {section.title}\n{(section.ai_content or '')[:800]}")
        written.append(section.key)
    proposal.set_system_fields(generation_status="done", generation_error=None, generated_at=utcnow())
    cost = gateway.correlation_cost(correlation_id)
    roi.record("proposal_generation", subject_type="proposal", subject_id=proposal.id, user_id=user_id,
               correlation_id=correlation_id, duration_seconds=time.monotonic() - started, cost_usd=cost)
    db.session.commit()
    log.info("proposal_generated", proposal_id=proposal.id, sections=len(written), cost_usd=str(cost))
    return {"proposal_id": proposal.id, "sections": written, "correlation_id": correlation_id,
            "cost_usd": f"{cost:.4f}"}
