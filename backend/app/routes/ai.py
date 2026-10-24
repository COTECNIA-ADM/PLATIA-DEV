"""Funciones de IA para las personas usuarias (Capítulos 10-12).

- ``POST /api/ai/ask``: pregunta sobre los documentos (RAG con citas).
- ``POST /api/ai/search``: búsqueda semántica sin generar respuesta (no gasta tokens).
- ``POST /api/ai/feedback``: valoración de 1 a 5 de una respuesta.
- ``GET /api/ai/analyses/<id>``: estado y resultado de un análisis GO/NO-GO.

El modelo solo recibe fragmentos de documentos que la persona puede abrir.
"""
from flask import Blueprint, g, jsonify

from ..ai import analysis as analysis_service
from ..ai import rag
from ..ai.access import Viewer
from ..api.common import get_active, parse_body
from ..api.schemas import AskIn, FeedbackIn, SemanticSearchIn
from ..errors import ForbiddenError, NotFoundError
from ..extensions import db
from ..models import AIAnalysis, Document, LLMQualityScore, LLMUsageLog, Opportunity, TaskCompletionLog
from ..security.context import platform_guard, require_ai_module, require_permission
from ..security.ratelimit import rate_limit

ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")


@ai_bp.post("/ask")
@platform_guard
@require_permission("documents", "read")
@require_ai_module("document_analyzer")
@rate_limit("RATE_LIMIT_AI")
def ask():
    data = parse_body(AskIn)
    result = rag.ask(Viewer.current(), data.question, document_ids=data.document_ids,
                     history=[t.model_dump() for t in data.history])
    return jsonify(result)


@ai_bp.post("/search")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_READ")
def semantic_search():
    data = parse_body(SemanticSearchIn)
    hits = rag.search(Viewer.current(), data.query, limit=data.limit, document_ids=data.document_ids,
                      doc_types=data.doc_types, include_old_versions=data.include_old_versions)
    # Un resultado por documento, con su mejor fragmento
    best: dict[int, rag.Hit] = {}
    for h in hits:
        if h.document.id not in best or h.score > best[h.document.id].score:
            best[h.document.id] = h
    items = sorted(best.values(), key=lambda h: h.score, reverse=True)[:data.limit]
    return jsonify(items=[h.to_dict() for h in items])


@ai_bp.post("/feedback")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_WRITE")
def feedback():
    data = parse_body(FeedbackIn)
    usage = db.session.get(LLMUsageLog, data.usage_log_id)
    # Solo se valora una respuesta propia
    if usage is None or usage.user_id != g.security.user_id:
        raise NotFoundError("Respuesta no encontrada.")
    score = db.session.scalar(db.select(LLMQualityScore).filter_by(usage_log_id=usage.id, reviewer_type="user",
                                                                   reviewer_id=g.security.user_id))
    if score is None:
        score = LLMQualityScore(usage_log_id=usage.id, service_type=usage.service_type, reviewer_type="user",
                                reviewer_id=g.security.user_id)
        db.session.add(score)
    score.user_rating = data.rating
    score.notes = data.comment
    task = db.session.scalar(db.select(TaskCompletionLog).filter_by(correlation_id=usage.correlation_id))
    if task is not None:
        task.user_rating = data.rating
    db.session.commit()
    return jsonify({"usage_log_id": usage.id, "rating": data.rating})


@ai_bp.get("/analyses/<int:analysis_id>")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_READ")
def get_analysis(analysis_id: int):
    a = get_active(AIAnalysis, analysis_id, "Análisis")
    # Quien no puede ver el documento o la oportunidad tampoco ve su análisis
    if a.subject_type == "document":
        doc = db.session.get(Document, a.subject_id)
        if doc is None or not Viewer.current().can_view(doc):
            raise NotFoundError("Análisis no encontrado.")
    elif not g.security.can("opportunities", "read"):
        raise ForbiddenError("Permiso insuficiente.")
    elif db.session.get(Opportunity, a.subject_id) is None:
        raise NotFoundError("Análisis no encontrado.")
    return jsonify(analysis_service.to_dict(a))
