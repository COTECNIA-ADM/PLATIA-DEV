"""Enrutador del asistente: clasifica la consulta y llama al motor adecuado (Capítulo 13).

El clasificador no toma decisiones de negocio: produce una señal. Este módulo
actúa sobre ella y devuelve siempre la misma forma de respuesta:

- ``search_results``: búsqueda en Meilisearch con los filtros extraídos de la frase.
- ``rag_answer``: respuesta con citas sobre los documentos que la persona puede ver.
- ``workflow_suggestion``: la acción propuesta y cómo confirmarla. **Nunca se
  ejecuta sola**: generar o analizar cuesta dinero y crea datos, así que la
  confirma la persona (el agente de la fase 5c seguirá la misma regla).
- ``off_topic``: mensaje orientativo.

Cada consulta queda en ``search_query_log`` para vigilar la calidad del
clasificador (capa usada, confianza, reformulaciones, clics, valoraciones).
"""
import hashlib
import re
import time
from datetime import timedelta

import structlog
from flask import current_app, g

from ..ai import pii, rag
from ..ai.access import Viewer
from ..api.schemas import AssistantQueryIn, DocumentSearchIn, OpportunitySearchIn
from ..errors import ForbiddenError
from ..extensions import db
from ..models import Document, Opportunity, Proposal, SearchQueryLog, utcnow
from . import engine, intent
from .extract import extract, merge, normalize

log = structlog.get_logger(__name__)
REFORMULATION_SECONDS = 30
OFF_TOPIC_MESSAGE = ("Esta consulta queda fuera de lo que hace la plataforma. Puedo buscar oportunidades, "
                     "documentos o clientes, responder preguntas sobre tus documentos o preparar análisis "
                     "y propuestas. ¿En qué te ayudo?")
_DOC_WORDS = {"pliego": "pliego", "pliegos": "pliego", "contrato": "contrato", "contratos": "contrato",
              "propuesta": "propuesta", "propuestas": "propuesta", "cv": "cv", "curriculum": "cv",
              "acta": "acta", "actas": "acta", "informe": "informe", "informes": "informe"}


# ------------------------------------------------------------------ Registro de consultas
def query_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def log_query(channel: str, text: str, *, user_id: int | None, result: intent.IntentResult | None = None,
              engine_name: str | None = None, filters: dict | None = None, result_count: int | None = None,
              total_ms: int | None = None) -> SearchQueryLog:
    """Registra la consulta y marca la anterior como reformulada si llega enseguida."""
    redacted, _ = pii.redact(text or "")
    row = SearchQueryLog(
        channel=channel, query_text=redacted[:500], query_hash=query_hash(text), user_id=user_id,
        intent=result.intent if result else None, subtype=result.subtype if result else None,
        confidence=result.confidence if result else None, layer=result.layer if result else None,
        classify_ms=result.latency_ms if result else None, usage_log_id=result.usage_log_id if result else None,
        engine=engine_name, filters=filters or None, result_count=result_count, total_ms=total_ms,
    )
    if user_id is not None:
        previous = db.session.scalar(
            db.select(SearchQueryLog).where(SearchQueryLog.user_id == user_id,
                                            SearchQueryLog.created_at >= utcnow() - timedelta(seconds=REFORMULATION_SECONDS))
            .order_by(SearchQueryLog.id.desc()).limit(1))
        if previous is not None and previous.query_hash != row.query_hash and previous.first_click_at is None:
            previous.reformulated = True
    db.session.add(row)
    db.session.commit()
    return row


# ------------------------------------------------------------------ Destinos de un encargo
_OPP_REF = re.compile(r"(?:oportunidad|#)\s*(\d{1,9})\b", re.IGNORECASE)


def _target_opportunity(text: str, opportunity_id: int | None) -> Opportunity | None:
    if opportunity_id:
        opp = db.session.get(Opportunity, opportunity_id)
        return opp if opp is not None and opp.is_active else None
    if m := _OPP_REF.search(text):
        opp = db.session.get(Opportunity, int(m.group(1)))
        if opp is not None and opp.is_active:
            return opp
    # Un código de expediente escrito tal cual (p. ej. 2024/CONT-0387)
    for token in re.findall(r"[\w./-]{5,50}", text):
        if any(ch.isdigit() for ch in token):
            opp = db.session.scalar(db.select(Opportunity).where(Opportunity.code == token,
                                                                 Opportunity.is_active.is_(True)))
            if opp is not None:
                return opp
    return None


def _suggest(result: intent.IntentResult, data: AssistantQueryIn, ctx, viewer: Viewer) -> dict:
    action = result.subtype
    allowed_ai = set(ctx.ai_modules()) if not ctx.is_admin else {"document_analyzer", "proposal_generator"}
    out = {"type": "workflow_suggestion", "action": action, "target": None, "confirm": None}
    if action == "analyze_document":
        doc = None
        for doc_id in data.document_ids or []:
            candidate = db.session.get(Document, doc_id)
            if candidate is not None and candidate.is_active and viewer.can_view(candidate):
                doc = candidate
                break
        if doc is None:
            return {**out, "message": "Indica qué documento quieres analizar (selecciónalo y vuelve a pedirlo)."}
        allowed = ctx.can("documents", "read") and "document_analyzer" in allowed_ai
        return {**out, "target": {"kind": "document", "id": doc.id, "title": doc.title},
                "confirm": {"method": "POST", "path": f"/api/documents/{doc.id}/analysis"} if allowed else None,
                "message": (f"Puedo analizar «{doc.title}» (GO/NO-GO). Confirma para lanzarlo."
                            if allowed else "Tu rol no permite lanzar análisis con IA.")}
    opp = _target_opportunity(data.query, data.opportunity_id)
    if opp is None:
        return {**out, "message": "Indica la oportunidad (ábrela o escribe su código) y vuelve a pedirlo."}
    target = {"kind": "opportunity", "id": opp.id, "title": opp.title, "code": opp.code}
    if action == "analyze_opportunity":
        allowed = ctx.can("opportunities", "write") and "document_analyzer" in allowed_ai
        return {**out, "target": target,
                "confirm": {"method": "POST", "path": f"/api/opportunities/{opp.id}/analysis"} if allowed else None,
                "message": ("Puedo analizar si nos conviene presentarnos (GO/NO-GO). Confirma para lanzarlo."
                            if allowed else "Tu rol no permite lanzar análisis con IA.")}
    # generate_proposal (y cualquier otro encargo de redacción)
    allowed = ctx.can("proposals", "write") and "proposal_generator" in allowed_ai
    proposal = db.session.scalar(db.select(Proposal).where(Proposal.opportunity_id == opp.id,
                                                           Proposal.is_active.is_(True),
                                                           Proposal.status == "draft")
                                 .order_by(Proposal.id.desc()).limit(1))
    if not allowed:
        return {**out, "target": target, "message": "Tu rol no permite redactar propuestas con IA."}
    if proposal is None:
        return {**out, "target": target, "action": "create_proposal",
                "confirm": {"method": "POST", "path": "/api/proposals", "body": {"opportunity_id": opp.id}},
                "message": "Esta oportunidad aún no tiene propuesta en borrador. Confirma para crearla; "
                           "después podré redactarla."}
    return {**out, "target": {**target, "proposal_id": proposal.id},
            "confirm": {"method": "POST", "path": f"/api/proposals/{proposal.id}/generate", "body": {}},
            "message": f"Puedo redactar las secciones pendientes de «{proposal.title}». Confirma para empezar."}


# ------------------------------------------------------------------ Punto de entrada
def handle(data: AssistantQueryIn) -> dict:
    started = time.monotonic()
    ctx = g.security
    viewer = Viewer.current()
    context = ""
    if data.opportunity_id:
        opp = db.session.get(Opportunity, data.opportunity_id)
        if opp is not None and opp.is_active:
            context = f"La persona está viendo la oportunidad «{opp.title[:200]}»."
    result = intent.classify(data.query, ctx.user_id, context=context)
    response: dict = {"intent": result.to_dict()}
    engine_name, filters, count = "none", None, None

    if result.intent == "AGENT_TOOLS":
        response, engine_name, filters, count = _search(result, data, ctx, viewer, response)
    elif result.intent == "CHAT_RAG" or (result.intent == "WORKFLOW" and result.subtype == "summarize"):
        if not ctx.can("documents", "read") or (not ctx.is_admin and "document_analyzer" not in ctx.ai_modules()):
            raise ForbiddenError("Tu rol no tiene acceso a las preguntas sobre documentos.")
        answer = rag.ask(viewer, data.query, document_ids=data.document_ids,
                         history=[t.model_dump() for t in data.history])
        response.update(type="rag_answer", engine="rag", **answer)
        engine_name, count = "rag", len(answer.get("sources") or [])
    elif result.intent == "WORKFLOW":
        response.update(_suggest(result, data, ctx, viewer))
    else:
        response.update(type="off_topic", engine="none", message=OFF_TOPIC_MESSAGE)

    total_ms = int((time.monotonic() - started) * 1000)
    row = log_query("assistant", data.query, user_id=ctx.user_id, result=result, engine_name=engine_name,
                    filters=filters, result_count=count, total_ms=total_ms)
    log.info("assistant_query", intent=result.intent, subtype=result.subtype, layer=result.layer,
             confidence=round(result.confidence, 2), engine=engine_name, ms=total_ms)
    response["query_log_id"] = row.id
    return response


def _search(result, data: AssistantQueryIn, ctx, viewer, response: dict):
    found = merge(extract(data.query), result.filters if result.layer == "llm" else None)
    if result.subtype == "search_documents":
        if not ctx.can("documents", "read"):
            raise ForbiddenError("Permiso insuficiente.")
        words = found.keywords.split()
        doc_types = sorted({_DOC_WORDS[w] for w in words if w in _DOC_WORDS})
        q = " ".join(w for w in words if w not in _DOC_WORDS and w not in ("documento", "documentos",
                                                                          "fichero", "archivo", "anexo"))
        page = engine.search_documents(DocumentSearchIn(q=q[:200], doc_types=doc_types or None, per_page=10,
                                                        facets=False), viewer)
        filters = {"q": q, **({"doc_types": doc_types} if doc_types else {})}
        response.update(type="search_results", target="documents", filters=filters, **page.to_dict())
        return response, page.engine, filters, page.total
    if result.subtype == "search_clients":
        if not ctx.can("clients", "read"):
            raise ForbiddenError("Permiso insuficiente.")
        q = " ".join(w for w in found.keywords.split() if w not in ("cliente", "clientes", "empresa", "empresas"))
        quick = engine.quick_search(q or found.keywords, 10, viewer=viewer, can_opportunities=False,
                                    can_documents=False, can_clients=True)
        group = quick["groups"][0] if quick["groups"] else {"items": [], "total": 0}
        response.update(type="search_results", target="clients", filters={"q": q}, engine=quick["engine"],
                        items=group["items"], pagination={"page": 1, "per_page": 10, "total": group["total"],
                                                          "pages": 1 if group["total"] else 0})
        return response, quick["engine"], {"q": q}, group["total"]
    if not ctx.can("opportunities", "read"):
        raise ForbiddenError("Permiso insuficiente.")
    filters = found.to_filters()
    params = OpportunitySearchIn(per_page=10, facets=True,
                                 semantic=bool(filters.get("q")) and current_app.config.get("SEARCH_ASSISTANT_SEMANTIC", True),
                                 **filters)
    page = engine.search_opportunities(params, ctx.user_id)
    response.update(type="search_results", target="opportunities", filters=filters, **page.to_dict())
    return response, page.engine, filters, page.total
