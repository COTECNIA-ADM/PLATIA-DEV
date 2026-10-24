"""Memoria del copiloto entre conversaciones (Capítulo 14).

- Pocas y útiles: como mucho ``MEMORY_MAX_PER_USER`` por persona (50) en cuatro
  categorías: preferencias, datos de clientes, forma de trabajar y conclusiones.
- En cada conversación se inyectan las ``MEMORY_INJECT`` mejores (10), ordenadas
  por ``0,6 · recencia + 0,4 · frecuencia de uso``.
- Las extrae Haiku en segundo plano al terminar un intercambio (como mucho 3 por
  vez), sin datos personales y sin duplicados (hash del texto normalizado).
- La persona las ve, las edita y las borra; el borrado es real (RGPD).
"""
import hashlib
import math
import unicodedata

import structlog
from flask import current_app

from ..ai import gateway, guardrails, pii
from ..extensions import db
from ..models import ChatConversation, ChatMessage, UserMemory, utcnow

log = structlog.get_logger(__name__)
CATEGORIES = UserMemory.CATEGORIES
CATEGORY_LABELS = {"preference": "Preferencia", "client_fact": "Dato de cliente", "workflow": "Forma de trabajar",
                   "insight": "Conclusión"}
RECENCY_HALF_LIFE_DAYS = 30

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"category": {"type": "string", "enum": list(CATEGORIES)},
                               "content": {"type": "string"}},
                "required": ["category", "content"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["memories"],
    "additionalProperties": False,
}


def content_hash(text: str) -> str:
    flat = unicodedata.normalize("NFKD", " ".join(text.lower().split()))
    flat = "".join(ch for ch in flat if not unicodedata.combining(ch)).strip(" .")
    return hashlib.sha256(flat.encode()).hexdigest()


def score(memory: UserMemory, now=None, max_count: int = 1) -> float:
    now = now or utcnow()
    last = memory.last_accessed_at or memory.updated_at or memory.created_at
    days = max(0.0, (now - last).total_seconds() / 86400)
    recency = math.exp(-math.log(2) * days / RECENCY_HALF_LIFE_DAYS)
    frequency = math.log1p(memory.access_count) / math.log1p(max(max_count, 1))
    return 0.6 * recency + 0.4 * frequency


def ranked(user_id: int) -> list[UserMemory]:
    rows = db.session.scalars(db.select(UserMemory).filter_by(user_id=user_id)).all()
    if not rows:
        return []
    now, top = utcnow(), max(m.access_count for m in rows)
    return sorted(rows, key=lambda m: score(m, now, top), reverse=True)


def for_prompt(user_id: int) -> str:
    """Las memorias más útiles, como texto para el contexto. Cuenta el uso."""
    limit = current_app.config.get("MEMORY_INJECT", 10)
    chosen = ranked(user_id)[:limit]
    if not chosen:
        return ""
    now = utcnow()
    for m in chosen:
        m.access_count += 1
        m.last_accessed_at = now
    db.session.commit()
    return "\n".join(f"- [{CATEGORY_LABELS[m.category]}] {m.content}" for m in chosen)


def add(user_id: int, category: str, content: str, *, source: str = "user",
        conversation_id: int | None = None) -> UserMemory | None:
    """Guarda una memoria (sin datos personales). Si ya existe, la refresca. No hace commit."""
    text, _ = pii.redact(" ".join(content.split())[:500])
    if len(text) < 5:
        return None
    digest = content_hash(text)
    existing = db.session.scalar(db.select(UserMemory).filter_by(user_id=user_id, content_hash=digest))
    if existing is not None:
        existing.updated_at = utcnow()
        return existing
    memory = UserMemory(user_id=user_id, category=category, content=text, content_hash=digest, source=source,
                        source_conversation_id=conversation_id)
    db.session.add(memory)
    _prune(user_id)
    return memory


def _prune(user_id: int) -> None:
    """Por encima del máximo se olvidan las de menor puntuación."""
    limit = current_app.config.get("MEMORY_MAX_PER_USER", 50)
    db.session.flush()
    rows = ranked(user_id)
    for m in rows[limit:]:
        db.session.delete(m)


def extract(conversation_id: int) -> int:
    """Extrae memorias del último intercambio de una conversación (tarea en segundo plano)."""
    conv = db.session.get(ChatConversation, conversation_id)
    if conv is None or not conv.is_active or not current_app.config.get("MEMORY_EXTRACT_ENABLED", True):
        return 0
    last = db.session.scalars(db.select(ChatMessage).filter_by(conversation_id=conv.id)
                              .order_by(ChatMessage.id.desc()).limit(6)).all()[::-1]
    if not any(m.role == "user" for m in last):
        return 0
    transcript = "\n".join(f"{'Persona' if m.role == 'user' else 'Copiloto'}: {m.content[:1500]}" for m in last)
    known = "\n".join(f"- {m.content}" for m in ranked(conv.user_id)[:30])
    result = gateway.run("memory_extraction", variables={"conversation": transcript, "known": known or "(ninguna)"},
                         user_id=conv.user_id, json_schema=EXTRACTION_SCHEMA)
    created = 0
    for item in ((result.data or {}).get("memories") or [])[:3]:
        if item.get("category") not in CATEGORIES:
            continue
        # Lo que se guarda pasa los mismos filtros que la entrada de la persona
        checked = guardrails.check_input(item.get("content") or "", max_chars=500)
        if checked.blocked:
            continue
        if add(conv.user_id, item["category"], checked.text, source="auto", conversation_id=conv.id) is not None:
            created += 1
    db.session.commit()
    log.info("memories_extracted", conversation=conv.id, created=created)
    return created


def to_dict(m: UserMemory) -> dict:
    from ..api.common import iso

    return {"id": m.id, "category": m.category, "content": m.content, "source": m.source,
            "access_count": m.access_count, "last_accessed_at": iso(m.last_accessed_at),
            "created_at": iso(m.created_at), "updated_at": iso(m.updated_at)}
