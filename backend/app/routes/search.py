"""Búsqueda y asistente (Capítulo 13).

- ``GET  /api/search?q=``: cuadro de búsqueda único (oportunidades, documentos y
  clientes a la vez), pensado para buscar mientras se escribe.
- ``POST /api/search/opportunities``: búsqueda con filtros, facetas y orden.
- ``POST /api/search/documents``: documentos que la persona puede ver.
- ``POST /api/search/click``: la persona abrió un resultado (métrica de calidad).
- ``POST /api/assistant/query``: una frase libre; el clasificador decide si es
  una búsqueda, una pregunta sobre documentos, un encargo o algo fuera de ámbito.
- ``POST /api/assistant/feedback``: valoración o "no era eso lo que pedía".
"""
import time

from flask import Blueprint, g, jsonify, request

from ..ai.access import Viewer
from ..api.common import parse_body
from ..api.schemas import (AssistantFeedbackIn, AssistantQueryIn, DocumentSearchIn, OpportunitySearchIn,
                           SearchClickIn)
from ..errors import NotFoundError, ValidationError
from ..extensions import db
from ..models import SearchQueryLog, utcnow
from ..search import engine, router
from ..security.context import platform_guard, require_ai_module, require_permission
from ..security.ratelimit import rate_limit

search_bp = Blueprint("search", __name__, url_prefix="/api")


@search_bp.get("/search")
@platform_guard
@require_permission("opportunities", "read")
@rate_limit("RATE_LIMIT_SEARCH")
def quick_search():
    q = (request.args.get("q") or "").strip()[:100]
    if not q:
        raise ValidationError("Escribe algo que buscar (parámetro q).")
    try:
        limit = max(1, min(10, int(request.args.get("limit", 5))))
    except ValueError as exc:
        raise ValidationError("limit debe ser un número.") from exc
    ctx = g.security
    return jsonify(engine.quick_search(q, limit, viewer=Viewer.current(), can_opportunities=True,
                                       can_documents=ctx.can("documents", "read"),
                                       can_clients=ctx.can("clients", "read")))


@search_bp.post("/search/opportunities")
@platform_guard
@require_permission("opportunities", "read")
@rate_limit("RATE_LIMIT_SEARCH")
def search_opportunities():
    started = time.monotonic()
    params = parse_body(OpportunitySearchIn)
    page = engine.search_opportunities(params, g.security.user_id)
    out = page.to_dict()
    if params.q:
        row = router.log_query("opportunities", params.q, user_id=g.security.user_id, engine_name=page.engine,
                               filters=params.model_dump(mode="json", exclude_defaults=True, exclude={"q"}),
                               result_count=page.total, total_ms=int((time.monotonic() - started) * 1000))
        out["query_log_id"] = row.id
    return jsonify(out)


@search_bp.post("/search/documents")
@platform_guard
@require_permission("documents", "read")
@rate_limit("RATE_LIMIT_SEARCH")
def search_documents():
    started = time.monotonic()
    params = parse_body(DocumentSearchIn)
    page = engine.search_documents(params, Viewer.current())
    out = page.to_dict()
    if params.q:
        row = router.log_query("documents", params.q, user_id=g.security.user_id, engine_name=page.engine,
                               filters=params.model_dump(mode="json", exclude_defaults=True, exclude={"q"}),
                               result_count=page.total, total_ms=int((time.monotonic() - started) * 1000))
        out["query_log_id"] = row.id
    return jsonify(out)


def _own_log(query_log_id: int) -> SearchQueryLog:
    row = db.session.get(SearchQueryLog, query_log_id)
    if row is None or row.user_id != g.security.user_id:
        raise NotFoundError("Consulta no encontrada.")
    return row


@search_bp.post("/search/click")
@platform_guard
@require_permission("opportunities", "read")
@rate_limit("RATE_LIMIT_WRITE")
def click():
    data = parse_body(SearchClickIn)
    row = _own_log(data.query_log_id)
    if row.first_click_at is None:  # solo cuenta la primera interacción
        row.first_click_at = utcnow()
        row.click_position = data.position
        db.session.commit()
    return jsonify({"query_log_id": row.id, "first_click_at": row.first_click_at.isoformat() + "Z"})


@search_bp.post("/assistant/query")
@platform_guard
@require_permission("opportunities", "read")
@require_ai_module("copilot_chat")
@rate_limit("RATE_LIMIT_AI")
def assistant_query():
    return jsonify(router.handle(parse_body(AssistantQueryIn)))


@search_bp.post("/assistant/feedback")
@platform_guard
@require_permission("opportunities", "read")
@require_ai_module("copilot_chat")
@rate_limit("RATE_LIMIT_WRITE")
def assistant_feedback():
    data = parse_body(AssistantFeedbackIn)
    if data.rating is None and data.expected_intent is None:
        raise ValidationError("Envía una valoración (rating) o la intención esperada (expected_intent).")
    row = _own_log(data.query_log_id)
    if data.rating is not None:
        row.user_rating = data.rating
    if data.expected_intent is not None:
        row.expected_intent = data.expected_intent
    db.session.commit()
    return jsonify({"query_log_id": row.id, "rating": row.user_rating, "expected_intent": row.expected_intent})
