"""RAG sobre los documentos de la plataforma (Capítulo 12).

Indexado: el texto extraído se trocea (chunking.py), cada fragmento se
vectoriza en el servicio de IA y se guarda en Qdrant con el control de acceso
del documento en el payload.

Consulta (``ask``):

1. Guardarraíles de entrada sobre la pregunta.
2. Reescritura de la pregunta en consultas autónomas (modelo rápido). Si falla,
   se busca con la pregunta tal cual.
3. Búsqueda con el filtro de acceso del usuario, y filtro otra vez en el backend.
4. Se pasan al modelo los bloques padre de MySQL (más contexto que el fragmento).
5. Respuesta estructurada con citas y la marca ``sufficient_context``: si las
   fuentes no bastan, el modelo lo dice en lugar de inventar.
6. Guardarraíles de salida y, para una muestra, evaluación automática de calidad.
"""
import random
import time
import uuid
from dataclasses import dataclass

import structlog
from flask import current_app
from sqlalchemy import or_

from ..extensions import db
from ..models import AuditAction, Document, utcnow
from ..security.audit import audit
from . import gateway, guardrails, prompts, roi
from .access import Viewer, payload_roles
from .chunking import chunk_document
from .client import AIServiceError, get_ai_client
from .errors import AIUnavailableError, BudgetExceededError, GuardrailBlockedError
from .schemas import QUERY_REWRITE, RAG_ANSWER

log = structlog.get_logger(__name__)
COLLECTION = "documents"
NO_CONTEXT_ANSWER = ("No he encontrado información sobre esto en los documentos a los que tienes acceso. "
                     "Prueba a reformular la pregunta o a indicar el documento.")


# ------------------------------------------------------------------ Indexado
def _versions(doc: Document) -> list[Document]:
    root = doc.parent_version_id or doc.id
    return list(db.session.scalars(db.select(Document).where(
        or_(Document.id == root, Document.parent_version_id == root))))


def index_document(doc: Document) -> dict:
    """Indexa (o reindexa) un documento. No hace commit."""
    if not doc.is_active:
        deindex_document(doc)
        return {"status": "deleted"}
    if not (doc.extracted_text or "").strip():
        doc.set_system_fields(index_status="skipped", vector_count=0)
        return {"status": "skipped"}
    children, truncated = chunk_document(doc.extracted_text, doc.doc_type, doc.mime_type)
    chunks = [{"text": c.text[:20000], "metadata": {"parent_start": c.parent_start, "parent_end": c.parent_end,
                                                   "page": c.page}} for c in children]
    common = {"title": (doc.title or "")[:300], "doc_type": doc.doc_type or "", "owner_user_id": doc.created_by,
              "allowed_roles": payload_roles(doc), "is_current": bool(doc.is_current_version),
              "root_id": doc.parent_version_id or doc.id, "version_number": doc.version_number}
    result = get_ai_client().index(COLLECTION, doc.id, chunks, common)
    doc.set_system_fields(index_status="indexed", vector_count=result.get("points", len(chunks)),
                          embedding_model=result.get("model"), indexed_at=utcnow())
    # Las versiones anteriores dejan de salir en las búsquedas normales
    if doc.is_current_version:
        for other in _versions(doc):
            if other.id != doc.id and other.index_status == "indexed":
                get_ai_client().set_payload(COLLECTION, other.id, {"is_current": False})
    log.info("document_indexed", document_id=doc.id, chunks=doc.vector_count, truncated=truncated)
    return {"status": "indexed", "points": doc.vector_count, "truncated": truncated}


def deindex_document(doc: Document) -> None:
    get_ai_client().delete(COLLECTION, doc.id)
    doc.set_system_fields(index_status="none", vector_count=0)


def sync_access(doc: Document) -> None:
    """Copia a Qdrant los roles permitidos de todas las versiones del documento."""
    for version in _versions(doc):
        if version.index_status == "indexed":
            get_ai_client().set_payload(COLLECTION, version.id, {"allowed_roles": payload_roles(version)})


# ------------------------------------------------------------------ Búsqueda
@dataclass
class Hit:
    document: Document
    score: float
    text: str
    parent_start: int | None
    parent_end: int | None
    page: int | None

    def parent_text(self, max_chars: int = 3000) -> str:
        full = self.document.extracted_text or ""
        if self.parent_start is None or self.parent_end is None or not full:
            return self.text
        return full[self.parent_start:self.parent_end][:max_chars].strip() or self.text

    def to_dict(self) -> dict:
        return {"document_id": self.document.id, "title": self.document.title, "doc_type": self.document.doc_type,
                "score": self.score, "page": self.page, "excerpt": self.text[:400]}


def search(viewer: Viewer, query: str, *, limit: int | None = None, document_ids: list[int] | None = None,
           doc_types: list[str] | None = None, threshold: float | None = None,
           include_old_versions: bool = False) -> list[Hit]:
    cfg = current_app.config
    limit = limit or cfg.get("RAG_MAX_CHUNKS", 6)
    payload = {"collections": [COLLECTION], "query": query[:4000], "limit": min(limit * 3, 50),
               "score_threshold": cfg.get("RAG_SCORE_THRESHOLD", 0.35) if threshold is None else threshold,
               "only_current": not include_old_versions, "access": viewer.qdrant_access()}
    if document_ids:
        payload["ref_ids"] = document_ids[:500]
    if doc_types:
        payload["doc_types"] = doc_types[:20]
    try:
        raw = get_ai_client().search(payload)
    except AIServiceError as exc:
        log.warning("rag_search_failed", error=str(exc))
        raise AIUnavailableError("La búsqueda semántica no está disponible en este momento.") from exc
    ids = {h["ref_id"] for h in raw if h.get("ref_id") is not None}
    docs = {d.id: d for d in db.session.scalars(db.select(Document).where(Document.id.in_(ids)))} if ids else {}
    hits: list[Hit] = []
    for h in raw:
        doc = docs.get(h.get("ref_id"))
        # Segundo filtro: borrados o con permisos cambiados desde que se indexaron
        if doc is None or not doc.is_active or not viewer.can_view(doc):
            continue
        p = h.get("payload") or {}
        hits.append(Hit(doc, h["score"], h.get("text", ""), p.get("parent_start"), p.get("parent_end"), p.get("page")))
        if len(hits) >= limit * 2:
            break
    return hits


def _dedupe_parents(hits: list[Hit], limit: int) -> list[Hit]:
    """Un bloque padre aparece una sola vez aunque varios de sus fragmentos coincidan."""
    seen, out = set(), []
    for h in sorted(hits, key=lambda x: x.score, reverse=True):
        key = (h.document.id, h.parent_start, h.parent_end)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
        if len(out) >= limit:
            break
    return out


def format_sources(hits: list[Hit], max_chars: int = 3000) -> str:
    blocks = []
    for n, h in enumerate(hits, start=1):
        page = f", página {h.page}" if h.page else ""
        blocks.append(f'<source n="{n}" title="{h.document.title}{page}">\n{h.parent_text(max_chars)}\n</source>')
    return "\n\n".join(blocks)


# ------------------------------------------------------------------ Preguntas
def check_question(text: str, user_id: int | None) -> str:
    result = guardrails.check_input(text)
    if result.blocked:
        audit(AuditAction.AI_REQUEST_BLOCKED, "WARNING", user_id=user_id,
              details={"reasons": result.reasons, "length": len(text)})
        raise GuardrailBlockedError("La pregunta no se puede procesar: " + result.user_message)
    return result.text


def rewrite_queries(question: str, history: list[dict] | None, user_id: int | None, correlation_id: str) -> list[str]:
    if not current_app.config.get("RAG_QUERY_REWRITE", True):
        return [question]
    conversation = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in (history or [])[-6:])
    try:
        result = gateway.run("rag_query_rewrite", variables={"question": question, "conversation": conversation},
                             user_id=user_id, json_schema=QUERY_REWRITE, correlation_id=correlation_id)
        queries = [q.strip()[:500] for q in (result.data or {}).get("queries", []) if q and q.strip()]
    except BudgetExceededError:
        raise
    except Exception as exc:  # noqa: BLE001 - sin reescritura se busca con la pregunta original
        log.info("rag_rewrite_skipped", error=str(exc))
        return [question]
    return list(dict.fromkeys([question, *queries]))[:4]


def ask(viewer: Viewer, question: str, *, document_ids: list[int] | None = None,
        history: list[dict] | None = None) -> dict:
    started = time.monotonic()
    question = check_question(question, viewer.user_id)
    correlation_id = str(uuid.uuid4())
    cfg = current_app.config
    max_chunks = cfg.get("RAG_MAX_CHUNKS", 6)
    hits: list[Hit] = []
    for query in rewrite_queries(question, history, viewer.user_id, correlation_id):
        hits += search(viewer, query, limit=max_chunks, document_ids=document_ids)
    hits = _dedupe_parents(hits, max_chunks)
    if not hits:
        return {"answer": NO_CONTEXT_ANSWER, "sufficient_context": False, "sources": [], "citations": [],
                "correlation_id": correlation_id, "usage_log_id": None}

    context = format_sources(hits)
    result = gateway.run("chat_rag", variables={"question": question, "sources": context}, user_id=viewer.user_id,
                         json_schema=RAG_ANSWER, correlation_id=correlation_id)
    data = result.data if isinstance(result.data, dict) else {"answer": result.text, "sufficient_context": True,
                                                              "citations": []}
    checked = guardrails.check_output(data.get("answer") or "", prompts.get_active(result.prompt_name).system_prompt)
    if checked.blocked:
        audit(AuditAction.AI_OUTPUT_BLOCKED, "WARNING", user_id=viewer.user_id,
              details={"reasons": checked.reasons, "usage_log_id": result.usage_log_id})
        raise GuardrailBlockedError("La respuesta generada no se puede mostrar por seguridad.")
    citations = [c for c in data.get("citations") or [] if isinstance(c.get("source"), int)
                 and 1 <= c["source"] <= len(hits)]
    cited = {c["source"] for c in citations}
    sources = [{"n": n, **h.to_dict(), "cited": n in cited} for n, h in enumerate(hits, start=1)]

    roi.record("chat_rag", subject_type="question", subject_id=None, user_id=viewer.user_id,
               correlation_id=correlation_id, duration_seconds=time.monotonic() - started,
               cost_usd=gateway.correlation_cost(correlation_id))
    db.session.commit()
    if random.random() < cfg.get("RAG_EVAL_SAMPLE_RATE", 0.05):
        from ..queue import PRIORITY_MAINTENANCE, enqueue
        from ..tasks.ai import evaluate_rag

        enqueue(evaluate_rag, result.usage_log_id, question, context[:30000], checked.text,
                priority=PRIORITY_MAINTENANCE)
    return {"answer": checked.text, "sufficient_context": bool(data.get("sufficient_context", True)),
            "citations": citations, "sources": sources, "correlation_id": correlation_id,
            "usage_log_id": result.usage_log_id, "model": result.model, "is_fallback": result.is_fallback}
