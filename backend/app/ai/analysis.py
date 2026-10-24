"""Análisis con IA de documentos y oportunidades (Capítulos 9 y 10).

- **Enriquecimiento** de cada documento procesado (modelo rápido): resumen,
  palabras clave, tipo probable y entidades. Alimenta los listados y la búsqueda.
- **Análisis GO/NO-GO** bajo demanda (modelo principal): requisitos, encaje con
  el portfolio, riesgos y veredicto. Se guarda en ``ai_analyses`` con el modelo y
  la versión del prompt que lo produjeron.

Los textos largos se recortan a ``ANALYSIS_MAX_CHARS`` y el análisis queda
marcado como ``truncated`` para que se sepa que no ha leído el documento entero.
"""
import time
import uuid

import structlog
from flask import current_app

from ..extensions import db
from ..models import AIAnalysis, Document, Opportunity, OpportunityDocument, ServiceLine, utcnow
from . import gateway, roi
from .access import Viewer
from .schemas import ENRICHMENT, GO_NO_GO, clamp

log = structlog.get_logger(__name__)
VALID_DOC_TYPES = set(ENRICHMENT["properties"]["doc_type"]["enum"])


def _cut(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    # Principio y final: en los pliegos el final suele traer criterios y anexos
    head = int(limit * 0.8)
    return text[:head] + "\n\n[… texto omitido por longitud …]\n\n" + text[-(limit - head):], True


# ------------------------------------------------------------------ Enriquecimiento
def enrich_document(doc: Document) -> dict:
    """Resumen, palabras clave y entidades. No hace commit."""
    text = (doc.extracted_text or "").strip()
    if not text:
        return {"status": "skipped"}
    started = time.monotonic()
    excerpt, truncated = _cut(text, current_app.config.get("ENRICH_MAX_CHARS", 40000))
    result = gateway.run("document_enrichment", variables={"title": doc.title, "filename": doc.original_filename or "",
                                                           "text": excerpt},
                         user_id=doc.created_by, json_schema=ENRICHMENT)
    data = result.data if isinstance(result.data, dict) else {}
    fields = {
        "ai_summary": (data.get("summary") or "")[:4000] or None,
        "ai_keywords": [k[:80] for k in (data.get("keywords") or [])][:15] or None,
        "ai_entities": {**(data.get("entities") or {}), "language": data.get("language"),
                        "suggested_doc_type": data.get("doc_type"), "truncated": truncated},
        "ai_enriched_at": utcnow(),
    }
    if not doc.doc_type and data.get("doc_type") in VALID_DOC_TYPES and data["doc_type"] != "otro":
        fields["doc_type"] = data["doc_type"]
    doc.set_system_fields(**fields)
    roi.record("document_enrichment", subject_type="document", subject_id=doc.id, user_id=doc.created_by,
               correlation_id=result.correlation_id, duration_seconds=time.monotonic() - started,
               cost_usd=result.cost_usd)
    return {"status": "enriched", "usage_log_id": result.usage_log_id}


# ------------------------------------------------------------------ GO/NO-GO
def portfolio_text() -> str:
    lines = db.session.scalars(ServiceLine.select_active().order_by(ServiceLine.code)).all()
    if not lines:
        return "(sin portfolio definido)"
    return "\n".join(f"- {line.name}: {line.description or ''} Palabras clave: {', '.join(line.keywords or [])}"
                     for line in lines)


def opportunity_text(opp: Opportunity, max_chars: int, viewer: Viewer | None = None) -> tuple[str, bool]:
    parts = [f"Título: {opp.title}"]
    for label, value in (("Organismo", opp.contracting_entity), ("Sector", opp.sector),
                         ("Línea de servicio", opp.service_line),
                         ("Importe estimado (EUR)", opp.estimated_value_eur),
                         ("Plazo de presentación", opp.deadline and opp.deadline.isoformat(timespec="minutes")),
                         ("CPV", ", ".join(opp.cpv_codes or []))):
        if value:
            parts.append(f"{label}: {value}")
    if opp.description:
        parts.append(f"Descripción:\n{opp.description}")
    links = db.session.scalars(db.select(OpportunityDocument).filter_by(opportunity_id=opp.id, is_active=True)).all()
    for link in links:
        doc = db.session.get(Document, link.document_id)
        # Solo entra el texto de los documentos que puede ver quien pide el análisis
        if doc is not None and doc.is_active and doc.extracted_text and (viewer is None or viewer.can_view(doc)):
            parts.append(f"<document title=\"{doc.title}\" role=\"{link.role}\">\n{doc.extracted_text}\n</document>")
    return _cut("\n\n".join(parts), max_chars)


def subject_of(analysis: AIAnalysis):
    model = Document if analysis.subject_type == "document" else Opportunity
    obj = db.session.get(model, analysis.subject_id)
    return obj if obj is not None and obj.is_active else None


def create(subject_type: str, subject_id: int, user_id: int) -> AIAnalysis:
    analysis = AIAnalysis(subject_type=subject_type, subject_id=subject_id, status="queued", created_by=user_id,
                          correlation_id=str(uuid.uuid4()))
    db.session.add(analysis)
    db.session.commit()
    return analysis


def latest(subject_type: str, subject_id: int) -> AIAnalysis | None:
    return db.session.scalars(
        db.select(AIAnalysis).filter_by(subject_type=subject_type, subject_id=subject_id, is_active=True)
        .order_by(AIAnalysis.created_at.desc(), AIAnalysis.id.desc())).first()


def run(analysis: AIAnalysis) -> AIAnalysis:
    """Ejecuta el análisis. Hace commit. Los errores de IA se propagan a la tarea."""
    subject = subject_of(analysis)
    if subject is None:
        analysis.status, analysis.error = "failed", "El documento o la oportunidad ya no existe."
        db.session.commit()
        return analysis
    started = time.monotonic()
    max_chars = current_app.config.get("ANALYSIS_MAX_CHARS", 150000)
    if analysis.subject_type == "document":
        text, truncated = _cut(subject.extracted_text or "", max_chars)
        title = subject.title
    else:
        text, truncated = opportunity_text(subject, max_chars, Viewer.for_user(analysis.created_by))
        title = subject.title
    if not text.strip():
        analysis.status, analysis.error = "failed", "No hay texto que analizar (¿se ha procesado el documento?)."
        db.session.commit()
        return analysis
    analysis.status = "running"
    db.session.commit()

    result = gateway.run("document_analysis", prompt_name="analysis.go_no_go",
                         variables={"title": title, "subject_type": analysis.subject_type, "text": text,
                                    "portfolio": portfolio_text(), "today": utcnow().date().isoformat()},
                         user_id=analysis.created_by, json_schema=GO_NO_GO, correlation_id=analysis.correlation_id)
    data = result.data if isinstance(result.data, dict) else None
    if data is None or data.get("verdict") not in AIAnalysis.VERDICTS:
        analysis.status, analysis.error = "failed", "La IA no ha devuelto un análisis válido."
        db.session.commit()
        return analysis
    data["confidence"] = clamp(data.get("confidence"))
    for key, value in (data.get("scores") or {}).items():
        data["scores"][key] = clamp(value, 0, 10)
    analysis.result = data
    analysis.verdict = data["verdict"]
    analysis.confidence = data["confidence"]
    analysis.truncated = truncated
    analysis.model_name = result.model
    analysis.prompt_version = result.prompt_version
    analysis.llm_usage_log_id = result.usage_log_id
    analysis.status = "done"
    analysis.completed_at = utcnow()
    if analysis.subject_type == "opportunity":
        subject.set_system_fields(ai_summary=data.get("summary"), extra_data={
            **(subject.extra_data or {}),
            "go_no_go": {"analysis_id": analysis.id, "verdict": analysis.verdict, "confidence": analysis.confidence}})
    roi.record("document_analysis", subject_type=analysis.subject_type, subject_id=analysis.subject_id,
               user_id=analysis.created_by, correlation_id=analysis.correlation_id,
               duration_seconds=time.monotonic() - started, cost_usd=gateway.correlation_cost(analysis.correlation_id))
    db.session.commit()
    log.info("analysis_done", analysis_id=analysis.id, verdict=analysis.verdict, truncated=truncated)
    return analysis


def to_dict(a: AIAnalysis) -> dict:
    from ..api.common import iso

    return {"id": a.id, "subject_type": a.subject_type, "subject_id": a.subject_id, "status": a.status,
            "verdict": a.verdict, "confidence": a.confidence, "result": a.result, "error": a.error,
            "truncated": a.truncated, "model": a.model_name, "prompt_version": a.prompt_version,
            "created_by": a.created_by, "created_at": iso(a.created_at), "completed_at": iso(a.completed_at)}
