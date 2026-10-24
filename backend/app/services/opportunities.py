"""Motor de oportunidades (Capítulo 9).

- Máquina de estados de las 12 fases del embudo.
- Puntuación de relevancia (0-10) contra las líneas de servicio del portfolio:
  similitud semántica con embeddings (fase 5) combinada con palabras clave. Si
  el servicio de IA no responde, se puntúa solo con palabras clave.
- Ingesta de feeds ATOM públicos con deduplicación por hash.
"""
import hashlib
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal

import structlog

from ..errors import BusinessRuleError
from ..extensions import db
from ..models import Opportunity, ServiceLine, utcnow

log = structlog.get_logger(__name__)

# ------------------------------------------------------------------ Estados
TRANSITIONS: dict[str, set[str]] = {
    "detected": {"qualifying", "discarded"},
    "qualifying": {"qualified", "discarded"},
    "qualified": {"analyzing", "go_no_go", "discarded"},
    "analyzing": {"go_no_go", "discarded"},
    "go_no_go": {"preparing_proposal", "discarded"},
    "preparing_proposal": {"proposal_review", "discarded"},
    "proposal_review": {"proposal_sent", "preparing_proposal"},
    "proposal_sent": {"negotiation", "won", "lost"},
    "negotiation": {"won", "lost"},
    "won": set(),
    "lost": set(),
    "discarded": {"qualifying"},  # se puede reabrir
}
NEEDS_COMMENT = {"discarded", "lost"}  # descartar o perder exige motivo
CLOSED = {"won", "lost", "discarded"}


def allowed_transitions(status: str) -> list[str]:
    return sorted(TRANSITIONS.get(status, set()))


def change_status(opp: Opportunity, target: str, comment: str | None = None) -> str:
    """Valida y aplica la transición. Devuelve el estado anterior. No hace commit."""
    if target not in Opportunity.STATUSES:
        raise BusinessRuleError(f"Estado desconocido: {target}.")
    if target not in TRANSITIONS.get(opp.status, set()):
        raise BusinessRuleError(
            f"No se puede pasar de '{opp.status}' a '{target}'.",
            allowed=allowed_transitions(opp.status),
        )
    if target in NEEDS_COMMENT and not comment:
        raise BusinessRuleError("Indica el motivo en 'comment'.")
    previous = opp.status
    opp.status = target
    if target == "won":
        opp.probability = 100
    elif target in ("lost", "discarded"):
        opp.probability = 0
    return previous


# ------------------------------------------------------------------ Relevancia
WEIGHT_TEXT, WEIGHT_TAXONOMY, WEIGHT_WIN_RATE = 0.5, 0.3, 0.2
# Dentro del componente de texto: semántica 70 %, palabras clave 30 %
WEIGHT_SEMANTIC = 0.7
KEYWORDS_FOR_FULL_SCORE = 3
MIN_CLOSED_FOR_WIN_RATE = 3


def _normalize(text: str) -> str:
    text = text.lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        text = text.replace(a, b)
    return text


def keyword_score(text: str, keywords: list[str]) -> float:
    """0-10 según cuántas palabras clave de la línea aparecen (palabra completa)."""
    if not keywords:
        return 0.0
    haystack = _normalize(text)
    hits = sum(1 for kw in keywords if re.search(rf"\b{re.escape(_normalize(kw))}\b", haystack))
    return min(hits / KEYWORDS_FOR_FULL_SCORE, 1.0) * 10


def taxonomy_match(cpv_codes: list[str] | None, prefixes: list[str]) -> float:
    if not cpv_codes or not prefixes:
        return 0.0
    codes = [c.split("-")[0] for c in cpv_codes]
    return 1.0 if any(code.startswith(p) for code in codes for p in prefixes) else 0.0


def historical_win_rate(service_line: str) -> float:
    """Tasa de éxito (0-1) de la línea en los dos últimos años; 0,5 si hay pocos datos."""
    since = utcnow() - timedelta(days=730)
    rows = db.session.execute(
        db.select(Opportunity.status, db.func.count())
        .where(Opportunity.service_line == service_line, Opportunity.status.in_(("won", "lost")),
               Opportunity.updated_at >= since, Opportunity.is_active.is_(True))
        .group_by(Opportunity.status)
    ).all()
    counts = {status: n for status, n in rows}
    closed = counts.get("won", 0) + counts.get("lost", 0)
    if closed < MIN_CLOSED_FOR_WIN_RATE:
        return 0.5
    return counts.get("won", 0) / closed


def line_profile(line: ServiceLine) -> str:
    """Texto con el que se compara cada oportunidad en la puntuación semántica."""
    return f"{line.name}. {line.description or ''} {', '.join(line.keywords or [])}".strip()


_semantic_down_until = 0.0


def semantic_scores(opp: Opportunity, lines: list[ServiceLine]) -> dict[str, float] | None:
    """Similitud 0-10 con cada línea, o None si la IA no está disponible."""
    from flask import current_app

    global _semantic_down_until
    cfg = current_app.config
    if not cfg.get("SEMANTIC_SCORING", True) or not lines or time.monotonic() < _semantic_down_until:
        return None
    from ..ai.client import AIServiceError, get_ai_client

    try:
        sims = get_ai_client().similarity([f"{opp.title}. {(opp.description or '')[:3000]}"],
                                          [line_profile(line) for line in lines])[0]
    except (AIServiceError, KeyError, IndexError) as exc:
        # Sin IA no se espera en cada oportunidad de un feed: se reintenta en un minuto
        log.info("semantic_scoring_unavailable", error=str(exc))
        _semantic_down_until = time.monotonic() + 60
        return None
    low, high = cfg.get("SEMANTIC_SIM_LOW", 0.15), cfg.get("SEMANTIC_SIM_HIGH", 0.65)
    return {line.code: round(max(0.0, min(1.0, (sim - low) / (high - low))) * 10, 2)
            for line, sim in zip(lines, sims)}


def score_against(opp: Opportunity, line: ServiceLine, semantic: float | None = None) -> dict:
    """Puntuación 0-10: texto 50 %, taxonomía CPV 30 %, histórico de éxito 20 % (Capítulo 9)."""
    keywords = keyword_score(f"{opp.title} {opp.description or ''}", line.keywords or [])
    text_score = keywords if semantic is None else WEIGHT_SEMANTIC * semantic + (1 - WEIGHT_SEMANTIC) * keywords
    taxonomy = taxonomy_match(opp.cpv_codes, line.cpv_prefixes or [])
    win_rate = historical_win_rate(line.code)
    total = text_score * WEIGHT_TEXT + taxonomy * 10 * WEIGHT_TAXONOMY + win_rate * 10 * WEIGHT_WIN_RATE
    return {
        "service_line": line.code,
        "score": round(min(total, 10.0), 2),
        "text": round(text_score, 2),
        "keywords": round(keywords, 2),
        "semantic": semantic,
        "taxonomy": taxonomy,
        "win_rate": round(win_rate, 2),
    }


def score_opportunity(opp: Opportunity, lines: list[ServiceLine] | None = None) -> dict | None:
    """Puntúa contra todas las líneas activas y guarda la mejor. No hace commit."""
    if lines is None:
        lines = list(db.session.scalars(ServiceLine.select_active()))
    if not lines:
        return None
    semantic = semantic_scores(opp, lines) or {}
    best = max((score_against(opp, line, semantic.get(line.code)) for line in lines), key=lambda r: r["score"])
    opp.relevance_score = Decimal(str(best["score"]))
    opp.scored_at = utcnow()
    if not opp.service_line:
        opp.service_line = best["service_line"]
    opp.extra_data = {**(opp.extra_data or {}), "score_breakdown": best}
    return best


# ------------------------------------------------------------------ Feeds ATOM
def content_hash(external_id: str, title: str, description: str) -> str:
    return hashlib.sha256(f"{external_id}|{title}|{description}".encode()).hexdigest()


def upsert_from_feed(item: dict, source: str) -> tuple[Opportunity | None, str]:
    """Crea o actualiza una oportunidad a partir de un ítem normalizado del feed.
    Devuelve (oportunidad, "created" | "updated" | "unchanged"). No hace commit."""
    external_id = item["id"][:255]
    title = (item.get("title") or "(sin título)")[:500]
    description = item.get("description") or ""
    digest = content_hash(external_id, title, description)
    existing = db.session.scalar(
        db.select(Opportunity).filter_by(source=source, external_id=external_id)
    )
    if existing is not None and existing.content_hash == digest:
        return existing, "unchanged"
    values = {
        "title": title,
        "description": description[:20000] or None,
        "content_hash": digest,
        "contracting_entity": (item.get("entity") or None) and item["entity"][:255],
        "cpv_codes": item.get("cpv_codes") or None,
        "estimated_value_eur": item.get("estimated_value"),
        "deadline": item.get("deadline"),
        "published_at": item.get("published_at") or utcnow(),
        "extra_data": {"link": item.get("link")} if item.get("link") else None,
    }
    if existing is not None:
        # Una actualización del anuncio no cambia el estado de trabajo del equipo
        for key, value in values.items():
            setattr(existing, key, value)
        return existing, "updated"
    opp = Opportunity(source=source, external_id=external_id, status="detected", **values)
    db.session.add(opp)
    return opp, "created"


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    from ..api.common import to_utc_naive

    return to_utc_naive(parsed)
