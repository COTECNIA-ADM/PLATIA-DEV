"""Clasificador de intención en dos capas (Capítulo 13).

Cuatro intenciones:

- ``CHAT_RAG``: pregunta sobre conocimiento propio (documentos, propuestas) -> RAG.
- ``AGENT_TOOLS``: buscar o filtrar oportunidades, documentos o clientes -> Meilisearch.
- ``WORKFLOW``: encargo de generar o analizar algo -> se propone la acción.
- ``OFF_TOPIC``: fuera del ámbito de la plataforma -> mensaje orientativo.

**Capa 1** (microsegundos, sin coste): patrones de la tabla ``intent_patterns``
sobre el texto normalizado. Dos patrones de la misma intención dan confianza
0,92; uno, 0,78. Si dos intenciones empatan, la consulta es ambigua (0,6).

**Capa 2** (solo si la capa 1 no llega al umbral, 0,75 por defecto): el modelo
rápido clasifica con salida estructurada y propone filtros. La consulta pasa
antes por los guardarraíles de entrada.

**Plan B**: si la capa 2 falla o duda (confianza < 0,5), se usa la mejor
suposición de la capa 1 y, si no hay, ``CHAT_RAG``: es el modo más seguro porque
nunca cambia datos.
"""
import json
import re
import time
from dataclasses import dataclass, field

import structlog
from flask import current_app

from ..ai import gateway, guardrails
from ..ai.errors import AIDisabledError, AIRejectedError, AIUnavailableError, BudgetExceededError, GuardrailBlockedError
from ..extensions import db
from ..models import IntentPattern
from .extract import normalize

log = structlog.get_logger(__name__)

INTENTS = ("CHAT_RAG", "AGENT_TOOLS", "WORKFLOW", "OFF_TOPIC")
SUBTYPES = {
    "CHAT_RAG": ("rag_query",),
    "AGENT_TOOLS": ("search_opportunities", "search_documents", "search_clients"),
    "WORKFLOW": ("analyze_opportunity", "analyze_document", "generate_proposal", "summarize"),
    "OFF_TOPIC": ("",),
}
DEFAULT_SUBTYPE = {"CHAT_RAG": "rag_query", "AGENT_TOOLS": "search_opportunities", "WORKFLOW": "generate_proposal",
                   "OFF_TOPIC": ""}
# Ante un empate, esta prioridad decide la suposición del plan B (no la clasificación)
TIE_ORDER = ("OFF_TOPIC", "WORKFLOW", "AGENT_TOOLS", "CHAT_RAG")
CACHE_KEY = "intent_patterns:v1"
CACHE_TTL = 300  # 5 minutos (Capítulo 13)
MAX_QUERY_CHARS = 500
HIGH, MEDIUM, AMBIGUOUS = 0.92, 0.78, 0.6


@dataclass
class IntentResult:
    intent: str
    confidence: float
    subtype: str
    layer: str  # pattern, llm, fallback
    reasoning: str = ""
    filters: dict = field(default_factory=dict)  # los que propone la capa 2
    matched: list[int] = field(default_factory=list)  # ids de patrones que coincidieron
    usage_log_id: int | None = None
    latency_ms: int = 0

    def to_dict(self) -> dict:
        return {"type": self.intent, "subtype": self.subtype, "confidence": round(self.confidence, 3),
                "layer": self.layer, "latency_ms": self.latency_ms,
                **({"reasoning": self.reasoning} if self.reasoning else {})}


# ------------------------------------------------------------------ Patrones desde la BD con caché
def _redis():
    from ..security.redis_store import get_redis

    return get_redis()


def load_patterns() -> list[dict]:
    try:
        cached = _redis().get(CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception as exc:  # noqa: BLE001 - sin Redis se lee de la BD
        log.info("intent_cache_unavailable", error=str(exc))
    rows = db.session.scalars(db.select(IntentPattern).filter_by(is_active=True)
                              .order_by(IntentPattern.priority, IntentPattern.id)).all()
    patterns = [{"id": p.id, "intent": p.intent, "subtype": p.subtype, "pattern": p.pattern} for p in rows]
    try:
        _redis().setex(CACHE_KEY, CACHE_TTL, json.dumps(patterns))
    except Exception:  # noqa: BLE001
        pass
    return patterns


def invalidate_patterns() -> None:
    try:
        _redis().delete(CACHE_KEY)
    except Exception:  # noqa: BLE001
        pass


_compiled: dict[str, re.Pattern | None] = {}


def _compile(pattern: str) -> re.Pattern | None:
    if pattern not in _compiled:
        try:
            _compiled[pattern] = re.compile(pattern)
        except re.error:
            log.warning("intent_pattern_invalid", pattern=pattern[:80])
            _compiled[pattern] = None
        if len(_compiled) > 2000:
            _compiled.clear()
    return _compiled[pattern]


# Cuantificadores anidados como (a+)+ pueden tardar muchísimo con ciertos textos
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*[+*{]")


def validate_pattern(pattern: str) -> str | None:
    """Mensaje de error si el patrón no es válido o es peligroso."""
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"Expresión regular no válida: {exc}"
    if _NESTED_QUANTIFIER.search(pattern):
        return "El patrón tiene cuantificadores anidados (como (a+)+): puede bloquear el servidor."
    if re.search(r"[A-ZÁÉÍÓÚÑ]", re.sub(r"\\[A-Za-z]", "", pattern)):
        return "Escribe el patrón en minúsculas y sin tildes: se aplica sobre el texto normalizado."
    if re.compile(pattern).search(""):
        return "El patrón coincide con un texto vacío: coincidiría con todo."
    return None


# ------------------------------------------------------------------ Capa 1
def classify_patterns(text: str, patterns: list[dict] | None = None) -> IntentResult:
    """Devuelve la mejor intención por patrones (confianza 0 si no coincide ninguno)."""
    normalized = normalize(text, MAX_QUERY_CHARS)
    counts: dict[str, int] = {}
    first_subtype: dict[str, str] = {}
    matched: list[int] = []
    for p in patterns if patterns is not None else load_patterns():
        regex = _compile(p["pattern"])
        if regex is None or not regex.search(normalized):
            continue
        counts[p["intent"]] = counts.get(p["intent"], 0) + 1
        first_subtype.setdefault(p["intent"], p["subtype"] or DEFAULT_SUBTYPE.get(p["intent"], ""))
        matched.append(p["id"])
    if not counts:
        return IntentResult("CHAT_RAG", 0.0, "rag_query", "pattern")
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], TIE_ORDER.index(kv[0]) if kv[0] in TIE_ORDER else 9))
    best, n = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if second == n:
        confidence = AMBIGUOUS
    elif n >= 2:
        confidence = HIGH if second == 0 else MEDIUM
    else:
        confidence = MEDIUM
    return IntentResult(best, confidence, first_subtype[best], "pattern", matched=matched)


# ------------------------------------------------------------------ Capa 2
_FILTERS = {
    "type": "object",
    "properties": {
        "keywords": {"type": "string", "description": "Palabras a buscar en el texto, sin órdenes ni filtros"},
        "value_min_eur": {"type": "number", "description": "Importe mínimo en euros; 0 si no se indica"},
        "value_max_eur": {"type": "number", "description": "Importe máximo en euros; 0 si no se indica"},
        "deadline_within_days": {"type": "number", "description": "El plazo vence en los próximos N días; 0 si no se indica"},
        "published_within_days": {"type": "number", "description": "Publicadas en los últimos N días; 0 si no se indica"},
        "only_open": {"type": "boolean", "description": "true si solo interesan las que siguen abiertas"},
    },
    "required": ["keywords", "value_min_eur", "value_max_eur", "deadline_within_days", "published_within_days",
                 "only_open"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "subtype": {"type": "string", "enum": sorted({s for v in SUBTYPES.values() for s in v if s} | {"none"})},
        "confidence": {"type": "number", "description": "Confianza de 0 a 1"},
        "reasoning": {"type": "string", "description": "Una frase"},
        "filters": _FILTERS,
    },
    "required": ["intent", "subtype", "confidence", "reasoning", "filters"],
    "additionalProperties": False,
}


def classify_llm(text: str, user_id: int | None, context: str = "") -> IntentResult:
    """Capa 2. Lanza los errores de IA: quien llama decide el plan B."""
    result = gateway.run("intent_classification", variables={"query": text, "context": context or "(ninguno)"},
                         user_id=user_id, json_schema=SCHEMA)
    data = result.data if isinstance(result.data, dict) else {}
    intent = data.get("intent") if data.get("intent") in INTENTS else "CHAT_RAG"
    subtype = data.get("subtype") if data.get("subtype") in SUBTYPES[intent] else DEFAULT_SUBTYPE[intent]
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return IntentResult(intent, confidence, subtype, "llm", str(data.get("reasoning") or "")[:300],
                        data.get("filters") if isinstance(data.get("filters"), dict) else {},
                        usage_log_id=result.usage_log_id)


# ------------------------------------------------------------------ Punto de entrada
def clean_query(text: str) -> str:
    """Límite de longitud y sin caracteres de control (antes de cualquier capa)."""
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text or "")[:MAX_QUERY_CHARS].strip()


def classify(text: str, user_id: int | None = None, *, use_llm: bool = True, context: str = "") -> IntentResult:
    started = time.monotonic()
    text = clean_query(text)
    cfg = current_app.config
    first = classify_patterns(text)
    result = first
    if first.confidence < cfg.get("INTENT_LAYER1_THRESHOLD", 0.75):
        result = _second_layer(text, first, user_id, use_llm and cfg.get("INTENT_LLM_ENABLED", True), context)
    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result


def _fallback(first: IntentResult, reason: str) -> IntentResult:
    if first.confidence > 0:
        return IntentResult(first.intent, first.confidence, first.subtype, "fallback", reason, matched=first.matched)
    return IntentResult("CHAT_RAG", 0.5, "rag_query", "fallback", reason)


def _second_layer(text: str, first: IntentResult, user_id: int | None, use_llm: bool, context: str) -> IntentResult:
    if not use_llm:
        return _fallback(first, "Capa 2 desactivada")
    checked = guardrails.check_input(text, max_chars=MAX_QUERY_CHARS)
    if checked.blocked:
        raise GuardrailBlockedError("La consulta no se puede procesar: " + checked.user_message)
    try:
        llm = classify_llm(checked.text, user_id, context)
    except (AIDisabledError, AIUnavailableError, AIRejectedError, BudgetExceededError) as exc:
        log.info("intent_llm_unavailable", error=type(exc).__name__)
        return _fallback(first, "Clasificación por modelo no disponible")
    if llm.confidence < current_app.config.get("INTENT_MIN_CONFIDENCE", 0.5):
        fb = _fallback(first, f"El modelo dudaba ({llm.confidence:.2f})")
        fb.usage_log_id = llm.usage_log_id
        return fb
    llm.matched = first.matched
    return llm
