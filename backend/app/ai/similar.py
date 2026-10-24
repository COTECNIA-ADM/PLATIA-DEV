"""Oportunidades parecidas (Capítulo 12, colección ``opportunities``).

Solo se vectorizan las oportunidades con relevancia alta (``OPPORTUNITY_VECTOR_THRESHOLD``):
son las que el equipo trabaja y las que interesa comparar. El payload lleva la
fecha de cierre (``expires_ts``): las caducadas se conservan para consultar el
histórico ("¿a qué concursos parecidos nos presentamos y qué pasó?").
"""
import calendar

import structlog
from flask import current_app

from ..extensions import db
from ..models import Opportunity
from .client import AIServiceError, get_ai_client
from .errors import AIUnavailableError

log = structlog.get_logger(__name__)
COLLECTION = "opportunities"


def _text(opp: Opportunity) -> str:
    parts = [opp.title, opp.contracting_entity or "", opp.ai_summary or (opp.description or "")[:3000]]
    return "\n".join(p for p in parts if p).strip()


def should_index(opp: Opportunity) -> bool:
    threshold = current_app.config.get("OPPORTUNITY_VECTOR_THRESHOLD", 7.0)
    return bool(opp.is_active and opp.relevance_score is not None and float(opp.relevance_score) >= threshold)


def index_opportunity(opp: Opportunity) -> dict:
    client = get_ai_client()
    if not should_index(opp):
        client.delete(COLLECTION, opp.id)
        return {"status": "not_indexed"}
    common = {"title": opp.title[:300], "allowed_roles": ["*"], "is_current": True, "status": opp.status,
              "service_line": opp.service_line or "", "doc_type": "opportunity"}
    if opp.deadline:
        common["expires_ts"] = calendar.timegm(opp.deadline.utctimetuple())
    result = client.index(COLLECTION, opp.id, [{"text": _text(opp)[:20000]}], common)
    return {"status": "indexed", "points": result.get("points")}


def similar(opp: Opportunity, limit: int = 5, only_open: bool = False) -> list[dict]:
    try:
        hits = get_ai_client().search({"collections": [COLLECTION], "query": _text(opp)[:4000],
                                       "limit": limit + 1, "only_current": True, "not_expired": only_open,
                                       "score_threshold": current_app.config.get("RAG_SCORE_THRESHOLD", 0.35),
                                       "access": {"bypass": True}})
    except AIServiceError as exc:
        raise AIUnavailableError("La búsqueda de oportunidades parecidas no está disponible.") from exc
    ids = [h["ref_id"] for h in hits if h.get("ref_id") not in (None, opp.id)]
    rows = {o.id: o for o in db.session.scalars(db.select(Opportunity).where(Opportunity.id.in_(ids)))} if ids else {}
    out = []
    for h in hits:
        other = rows.get(h.get("ref_id"))
        if other is None or not other.is_active:
            continue
        out.append({"opportunity_id": other.id, "title": other.title, "status": other.status,
                    "contracting_entity": other.contracting_entity, "score": h["score"],
                    "relevance_score": None if other.relevance_score is None else float(other.relevance_score)})
    return out[:limit]
