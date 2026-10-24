"""Búsquedas sobre Meilisearch con permisos, facetas y resaltado (Capítulo 13).

- Los resultados se leen después de MySQL por id: lo que se devuelve es siempre
  el dato actual y con el mismo formato que el resto de la API, y lo que ya no
  existe o la persona no puede ver se descarta aunque el índice vaya con retraso.
- El resaltado llega con ``<mark>``, pero el resto del texto va escapado: un
  título con HTML de un portal público no se puede inyectar en la interfaz.
- Consultas híbridas: Meilisearch filtra y ordena por texto; si se pide
  ``semantic``, los primeros resultados se reordenan por significado con los
  embeddings del servicio de IA (dos pasos secuenciales, como en el libro).
- Si Meilisearch no responde, las oportunidades y documentos se buscan en MySQL
  con los mismos filtros (más lento y sin facetas, pero la pantalla funciona).
"""
import html
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog
from flask import current_app
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from ..ai.access import Viewer
from ..ai.client import AIServiceError, get_ai_client
from ..api.common import iso, like_pattern, to_utc_naive
from ..api.schemas import DocumentSearchIn, OpportunitySearchIn
from ..extensions import db
from ..models import Client, Document, Opportunity, utcnow
from . import filters as F
from .client import MeiliError, SearchUnavailableError, get_search_client
from .indexes import OPEN_STATUSES, SPECS, ts

log = structlog.get_logger(__name__)

PRE, POST = "\u0002", "\u0003"  # marcas internas del resaltado, sustituidas tras escapar
HIGHLIGHT = {"highlightPreTag": PRE, "highlightPostTag": POST, "cropMarker": "…"}
OPPORTUNITY_FACETS = ["status", "phase", "sector", "service_line", "source", "cpv_divisions"]
DOCUMENT_FACETS = ["doc_type"]
PHASE_STATUSES = {p: [s for s, ph in Opportunity.STATUS_PHASE.items() if ph == p] for p in ("F1", "F2", "F3", "F4", "F5")}
SORTS = {
    "relevance": [], "-relevance_score": ["relevance_score:desc"], "deadline": ["deadline_ts:asc"],
    "-published": ["published_ts:desc"], "-value": ["estimated_value_eur:desc"],
    "value": ["estimated_value_eur:asc"], "-created": ["created_ts:desc"],
}


def safe_highlight(text: str | None) -> str | None:
    if text is None:
        return None
    return html.escape(text).replace(PRE, "<mark>").replace(POST, "</mark>")


@dataclass
class Page:
    items: list[dict]
    page: int
    per_page: int
    total: int
    engine: str
    processing_ms: int | None = None
    facets: dict | None = None
    reranked: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out = {"items": self.items,
               "pagination": {"page": self.page, "per_page": self.per_page, "total": self.total,
                              "pages": math.ceil(self.total / self.per_page) if self.total else 0},
               "engine": self.engine, "processing_ms": self.processing_ms, "reranked": self.reranked}
        if self.facets is not None:
            out["facets"] = self.facets
        if self.notes:
            out["notes"] = self.notes
        return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_ago(days: int) -> int:
    return int((_now() - timedelta(days=days)).timestamp())


def _ts_of(value: datetime | None) -> int | None:
    return ts(to_utc_naive(value)) if value else None


# ------------------------------------------------------------------ Oportunidades
def opportunity_filter(p: OpportunitySearchIn, user_id: int | None) -> F.Filter | None:
    statuses = set(p.status or [])
    for phase in p.phase or []:
        statuses |= set(PHASE_STATUSES[phase])
    if p.only_open:
        statuses = (statuses & set(OPEN_STATUSES)) if statuses else set(OPEN_STATUSES)
        if not statuses:
            statuses = {"__none__"}  # se pidieron solo estados cerrados y "abiertas": nada
    deadline_from = _ts_of(p.deadline_from)
    if p.only_open:
        now = int(_now().timestamp())
        deadline_from = max(deadline_from or now, now)
    deadline_to = _ts_of(p.deadline_to)
    if p.deadline_within_days is not None:
        limit = int((_now() + timedelta(days=p.deadline_within_days)).timestamp())
        deadline_to = min(deadline_to, limit) if deadline_to else limit
        deadline_from = deadline_from or int(_now().timestamp())
    published_from = _ts_of(p.published_from)
    if p.published_within_days is not None:
        published_from = max(published_from or 0, _days_ago(p.published_within_days))
    owner = user_id if p.owner == "me" else p.owner

    deadline = None
    if deadline_from is not None or deadline_to is not None:
        deadline = F.all_of(F.gte("deadline_ts", deadline_from) if deadline_from is not None else None,
                            F.lte("deadline_ts", deadline_to) if deadline_to is not None else None)
        if p.only_open and deadline_to is None and not p.deadline_from:
            # "Abiertas" incluye las que no tienen plazo publicado
            deadline = F.either(deadline, F.eq("has_deadline", False))
    return F.all_of(
        F.any_of("status", sorted(statuses)),
        F.any_of("sector", p.sector or []),
        F.any_of("service_line", p.service_line or []),
        F.any_of("source", p.source or []),
        F.any_of("cpv_prefixes", p.cpv or []),
        F.gte("estimated_value_eur", p.value_min) if p.value_min is not None else None,
        F.lte("estimated_value_eur", p.value_max) if p.value_max is not None else None,
        deadline,
        F.gte("published_ts", published_from) if published_from is not None else None,
        F.lte("published_ts", _ts_of(p.published_to)) if p.published_to else None,
        F.gte("relevance_score", p.min_relevance) if p.min_relevance is not None else None,
        F.eq("owner_user_id", owner) if owner is not None else None,
        F.eq("client_id", p.client_id) if p.client_id is not None else None,
    )


def _opportunity_sort(p: OpportunitySearchIn) -> list[str]:
    if p.sort == "relevance":
        # Con texto manda la relevancia textual y desempata la afinidad precalculada.
        # Sin texto, primero lo que más encaja con el portfolio y lo más reciente.
        return ["relevance_score:desc"] if p.q else ["relevance_score:desc", "published_ts:desc"]
    return SORTS[p.sort]


def _load_opportunities(ids: list[int]) -> dict[int, Opportunity]:
    if not ids:
        return {}
    rows = db.session.scalars(select(Opportunity).where(Opportunity.id.in_(ids), Opportunity.is_active.is_(True))
                              .options(selectinload(Opportunity.client)))
    return {o.id: o for o in rows}


def _opportunity_items(hits: list[dict]) -> list[dict]:
    from ..routes.opportunities import summary

    objs = _load_opportunities([h["id"] for h in hits])
    items = []
    for h in hits:
        o = objs.get(h["id"])
        if o is None:
            continue  # borrada después de indexar
        fmt = h.get("_formatted") or {}
        items.append({**summary(o), "contracting_entity": o.contracting_entity,
                      "published_at": iso(o.published_at),
                      "highlight": {"title": safe_highlight(fmt.get("title")),
                                    "snippet": safe_highlight(fmt.get("description") or fmt.get("ai_summary")) or None},
                      "score": round(h["_score"], 4) if h.get("_score") is not None else None})
    return items


def search_opportunities(p: OpportunitySearchIn, user_id: int | None) -> Page:
    cfg = current_app.config
    flt = opportunity_filter(p, user_id)
    rerank = bool(p.semantic and p.q and p.page == 1 and cfg.get("SEARCH_SEMANTIC_RERANK", True))
    per_page = p.per_page
    query = {
        "q": p.q, "sort": _opportunity_sort(p), "showRankingScore": True,
        "attributesToRetrieve": ["id", "title", "description", "ai_summary"],
        "attributesToHighlight": ["title", "description", "ai_summary"], "attributesToCrop": ["description:30",
                                                                                              "ai_summary:30"],
        **HIGHLIGHT,
    }
    if rerank:
        query.update(limit=max(per_page, cfg.get("SEARCH_RERANK_CANDIDATES", 50)), offset=0)
    else:
        query.update(page=p.page, hitsPerPage=per_page)
    if p.facets:
        query["facets"] = OPPORTUNITY_FACETS
    try:
        res = get_search_client().search(SPECS["opportunities"].uid, query, flt)
    except MeiliError as exc:
        log.warning("search_unavailable", index="opportunities", error=str(exc))
        return _sql_opportunities(p, user_id)
    hits = [{**h, "_score": h.get("_rankingScore")} for h in res.get("hits", [])]
    total = res.get("totalHits", res.get("estimatedTotalHits", len(hits)))
    page = Page([], p.page, per_page, total, "meilisearch", res.get("processingTimeMs"),
                res.get("facetDistribution") if p.facets else None)
    if rerank:
        hits, page.reranked = _rerank(p.q, hits, page)
        hits = hits[:per_page]
    page.items = _opportunity_items(hits)
    return page


def _rerank(q: str, hits: list[dict], page: Page) -> tuple[list[dict], bool]:
    """Segundo paso de una consulta híbrida: similitud de significado con la pregunta."""
    if len(hits) < 2:
        return hits, False
    objs = _load_opportunities([h["id"] for h in hits])
    texts = []
    for h in hits:
        o = objs.get(h["id"])
        texts.append(" ".join(filter(None, [o.title, o.contracting_entity, (o.description or "")[:600]]))
                     if o else h.get("title", ""))
    try:
        sims = get_ai_client().similarity([q], texts)[0]
    except (AIServiceError, KeyError, IndexError) as exc:
        log.info("search_rerank_skipped", error=str(exc))
        page.notes.append("No se ha podido reordenar por significado: se muestra el orden por texto.")
        return hits, False
    low, high = current_app.config.get("SEMANTIC_SIM_LOW", 0.15), current_app.config.get("SEMANTIC_SIM_HIGH", 0.65)
    weight = current_app.config.get("SEARCH_RERANK_WEIGHT", 0.5)
    for h, sim in zip(hits, sims):
        semantic = max(0.0, min(1.0, (sim - low) / (high - low))) if high > low else sim
        h["_score"] = (1 - weight) * (h.get("_rankingScore") or 0) + weight * semantic
    return sorted(hits, key=lambda h: h["_score"], reverse=True), True


def _sql_opportunities(p: OpportunitySearchIn, user_id: int | None) -> Page:
    """Plan B sin Meilisearch: mismos filtros sobre MySQL, búsqueda por subcadena."""
    if not current_app.config.get("SEARCH_SQL_FALLBACK", True):
        raise SearchUnavailableError("El buscador no está disponible en este momento.")
    O = Opportunity
    stmt = O.select_active()
    statuses = set(p.status or [])
    for phase in p.phase or []:
        statuses |= set(PHASE_STATUSES[phase])
    if p.only_open:
        statuses = (statuses & set(OPEN_STATUSES)) if statuses else set(OPEN_STATUSES)
        stmt = stmt.where(or_(O.deadline.is_(None), O.deadline >= utcnow()))
    if statuses or p.only_open:
        stmt = stmt.where(O.status.in_(statuses or {"__none__"}))
    for attr, values in (("sector", p.sector), ("service_line", p.service_line), ("source", p.source)):
        if values:
            stmt = stmt.where(getattr(O, attr).in_(values))
    if p.value_min is not None:
        stmt = stmt.where(O.estimated_value_eur >= p.value_min)
    if p.value_max is not None:
        stmt = stmt.where(O.estimated_value_eur <= p.value_max)
    if p.deadline_from:
        stmt = stmt.where(O.deadline >= to_utc_naive(p.deadline_from))
    if p.deadline_to:
        stmt = stmt.where(O.deadline <= to_utc_naive(p.deadline_to))
    if p.deadline_within_days is not None:
        stmt = stmt.where(O.deadline >= utcnow(), O.deadline <= utcnow() + timedelta(days=p.deadline_within_days))
    if p.published_within_days is not None:
        stmt = stmt.where(O.published_at >= utcnow() - timedelta(days=p.published_within_days))
    if p.published_from:
        stmt = stmt.where(O.published_at >= to_utc_naive(p.published_from))
    if p.published_to:
        stmt = stmt.where(O.published_at <= to_utc_naive(p.published_to))
    if p.min_relevance is not None:
        stmt = stmt.where(O.relevance_score >= p.min_relevance)
    owner = user_id if p.owner == "me" else p.owner
    if owner is not None:
        stmt = stmt.where(O.owner_user_id == owner)
    if p.client_id is not None:
        stmt = stmt.where(O.client_id == p.client_id)
    if p.cpv:
        # cpv_codes es JSON: aproximación por subcadena, suficiente como plan B
        stmt = stmt.where(or_(*[db.cast(O.cpv_codes, db.String).like(f'%"{c}%') for c in p.cpv]))
    for word in (p.q or "").split()[:6]:
        pattern = like_pattern(word)
        stmt = stmt.where(or_(O.title.like(pattern, escape="\\"), O.code.like(pattern, escape="\\"),
                              O.contracting_entity.like(pattern, escape="\\"),
                              O.description.like(pattern, escape="\\")))
    order = {"deadline": O.deadline.asc(), "-published": O.published_at.desc(),
             "-value": O.estimated_value_eur.desc(), "value": O.estimated_value_eur.asc(),
             "-created": O.created_at.desc()}.get(p.sort, O.relevance_score.desc())
    total = db.session.scalar(select(db.func.count()).select_from(stmt.subquery())) or 0
    rows = db.session.scalars(stmt.options(selectinload(O.client)).order_by(order, O.id.desc())
                              .offset((p.page - 1) * p.per_page).limit(p.per_page)).all()
    hits = [{"id": o.id} for o in rows]
    page = Page(_opportunity_items(hits), p.page, p.per_page, total, "mysql",
                notes=["El buscador rápido no responde: resultados de la base de datos, sin facetas."])
    return page


# ------------------------------------------------------------------ Documentos
def document_access_filter(viewer: Viewer) -> F.Filter | None:
    """La misma regla que ``Viewer.can_view``, expresada como filtro de Meilisearch."""
    if viewer.manage:
        return None
    return F.either(F.eq("allowed_roles", "*"),
                    F.eq("created_by", viewer.user_id) if viewer.user_id is not None else None,
                    F.eq("allowed_roles", viewer.role) if viewer.role else None)


def search_documents(p: DocumentSearchIn, viewer: Viewer) -> Page:
    flt = F.all_of(document_access_filter(viewer),
                   None if p.include_old_versions else F.eq("is_current", True),
                   F.any_of("doc_type", p.doc_types or []))
    query = {"q": p.q, "page": p.page, "hitsPerPage": p.per_page, "showRankingScore": True,
             "attributesToRetrieve": ["id", "title", "content", "ai_summary"],
             "attributesToHighlight": ["title", "content", "ai_summary"],
             "attributesToCrop": ["content:30", "ai_summary:30"], **HIGHLIGHT}
    if not p.q:
        query["sort"] = ["created_ts:desc"]
    if p.facets:
        query["facets"] = DOCUMENT_FACETS
    try:
        res = get_search_client().search(SPECS["documents"].uid, query, flt)
    except MeiliError as exc:
        log.warning("search_unavailable", index="documents", error=str(exc))
        return _sql_documents(p, viewer)
    hits = res.get("hits", [])
    return Page(_document_items(hits, viewer), p.page, p.per_page, res.get("totalHits", len(hits)), "meilisearch",
                res.get("processingTimeMs"), res.get("facetDistribution") if p.facets else None)


def _document_items(hits: list[dict], viewer: Viewer) -> list[dict]:
    from ..routes.documents import summary

    ids = [h["id"] for h in hits]
    docs = {d.id: d for d in db.session.scalars(select(Document).where(Document.id.in_(ids)))} if ids else {}
    items = []
    for h in hits:
        d = docs.get(h["id"])
        # Segundo filtro: borrado o con permisos cambiados desde que se indexó
        if d is None or not d.is_active or not viewer.can_view(d):
            continue
        fmt = h.get("_formatted") or {}
        items.append({**summary(d), "highlight": {
            "title": safe_highlight(fmt.get("title")),
            "snippet": safe_highlight(fmt.get("content") or fmt.get("ai_summary")) or None},
            "score": round(h["_rankingScore"], 4) if h.get("_rankingScore") is not None else None})
    return items


def _sql_documents(p: DocumentSearchIn, viewer: Viewer) -> Page:
    if not current_app.config.get("SEARCH_SQL_FALLBACK", True):
        raise SearchUnavailableError("El buscador no está disponible en este momento.")
    D = Document
    stmt = select(D).where(D.is_active.is_(True))
    if (cond := viewer.sql_filter()) is not None:
        stmt = stmt.where(cond)
    if not p.include_old_versions:
        stmt = stmt.where(D.is_current_version.is_(True))
    if p.doc_types:
        stmt = stmt.where(D.doc_type.in_(p.doc_types))
    for word in (p.q or "").split()[:6]:
        pattern = like_pattern(word)
        stmt = stmt.where(or_(D.title.like(pattern, escape="\\"), D.original_filename.like(pattern, escape="\\"),
                              D.ai_summary.like(pattern, escape="\\")))
    total = db.session.scalar(select(db.func.count()).select_from(stmt.subquery())) or 0
    rows = db.session.scalars(stmt.order_by(D.created_at.desc(), D.id.desc())
                              .offset((p.page - 1) * p.per_page).limit(p.per_page)).all()
    return Page(_document_items([{"id": d.id} for d in rows], viewer), p.page, p.per_page, total, "mysql",
                notes=["El buscador rápido no responde: resultados de la base de datos, sin facetas."])


# ------------------------------------------------------------------ Búsqueda rápida (cuadro de búsqueda)
def quick_search(q: str, limit: int, *, viewer: Viewer, can_opportunities: bool, can_documents: bool,
                 can_clients: bool) -> dict:
    """Un cuadro de búsqueda para todo: oportunidades, documentos y clientes a la vez,
    cada grupo con los permisos de la persona. Pensada para buscar mientras se escribe."""
    plan = []
    if can_opportunities:
        plan.append(("opportunities", {"attributesToRetrieve": ["id", "title", "code", "contracting_entity",
                                                                "status"],
                                       "attributesToHighlight": ["title"]}, None))
    if can_documents:
        plan.append(("documents", {"attributesToRetrieve": ["id", "title", "doc_type"],
                                   "attributesToHighlight": ["title"]},
                     F.all_of(document_access_filter(viewer), F.eq("is_current", True))))
    if can_clients:
        plan.append(("clients", {"attributesToRetrieve": ["id", "name", "sector"],
                                 "attributesToHighlight": ["name"]}, None))
    if not plan:
        return {"query": q, "groups": [], "engine": "meilisearch", "processing_ms": 0}
    queries = [(SPECS[kind].uid, {"q": q, "limit": limit, **opts, **HIGHLIGHT}, flt) for kind, opts, flt in plan]
    try:
        results = get_search_client().multi_search(queries)
        engine = "meilisearch"
    except MeiliError as exc:
        log.warning("search_unavailable", index="multi", error=str(exc))
        results, engine = [_sql_quick(kind, q, limit, viewer) for kind, _, _ in plan], "mysql"
    groups = []
    for (kind, _, _), res in zip(plan, results):
        groups.append({"type": kind, "total": res.get("estimatedTotalHits", len(res.get("hits", []))),
                       "items": _quick_items(kind, res.get("hits", []), viewer)})
    return {"query": q, "groups": groups, "engine": engine,
            "processing_ms": max((r.get("processingTimeMs") or 0) for r in results) if results else 0}


def _quick_items(kind: str, hits: list[dict], viewer: Viewer) -> list[dict]:
    ids = [h["id"] for h in hits]
    if not ids:
        return []
    model = {"opportunities": Opportunity, "documents": Document, "clients": Client}[kind]
    objs = {o.id: o for o in db.session.scalars(select(model).where(model.id.in_(ids), model.is_active.is_(True)))}
    items = []
    for h in hits:
        o = objs.get(h["id"])
        if o is None or (kind == "documents" and not viewer.can_view(o)):
            continue
        fmt = h.get("_formatted") or {}
        if kind == "opportunities":
            items.append({"id": o.id, "title": o.title, "subtitle": " · ".join(filter(None, [o.code, o.contracting_entity])),
                          "status": o.status, "highlight": safe_highlight(fmt.get("title"))})
        elif kind == "documents":
            items.append({"id": o.id, "title": o.title, "subtitle": o.doc_type,
                          "highlight": safe_highlight(fmt.get("title"))})
        else:
            items.append({"id": o.id, "title": o.name, "subtitle": o.sector,
                          "highlight": safe_highlight(fmt.get("name"))})
    return items


def _sql_quick(kind: str, q: str, limit: int, viewer: Viewer) -> dict:
    pattern = like_pattern(q)
    if kind == "opportunities":
        stmt = select(Opportunity.id).where(Opportunity.is_active.is_(True), or_(
            Opportunity.title.like(pattern, escape="\\"), Opportunity.code.like(pattern, escape="\\")))
    elif kind == "documents":
        stmt = select(Document.id).where(Document.is_active.is_(True), Document.is_current_version.is_(True),
                                         Document.title.like(pattern, escape="\\"))
        if (cond := viewer.sql_filter()) is not None:
            stmt = stmt.where(cond)
    else:
        stmt = select(Client.id).where(Client.is_active.is_(True), Client.name.like(pattern, escape="\\"))
    ids = list(db.session.scalars(stmt.limit(limit))) if pattern else []
    return {"hits": [{"id": i} for i in ids], "estimatedTotalHits": len(ids)}
