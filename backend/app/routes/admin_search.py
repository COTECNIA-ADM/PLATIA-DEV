"""Buscador y clasificador de intención desde la app admin (Capítulo 13).

- Patrones de la capa 1: listar, crear, modificar, desactivar y probar una frase.
- Calidad del clasificador: reparto por intención y por capa, confianza,
  reformulaciones, clics, búsquedas sin resultados y clasificaciones que la
  persona marcó como erróneas, con avisos cuando algo se desvía.
- Índices de Meilisearch: estado frente a MySQL y reconstrucción sin cortes.

Todo exige ``X-App-Code: admin`` y el permiso ``search``.
"""
import statistics
from datetime import timedelta

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func

from ..api.common import iso, parse_body
from ..api.schemas import IntentPatternIn, IntentPatternPatch, IntentTestIn, ReindexIn
from ..errors import NotFoundError, ValidationError
from ..extensions import db
from ..models import AuditAction, IntentPattern, SearchQueryLog, utcnow
from ..queue import PRIORITY_USER, enqueue
from ..search import intent as intent_service
from ..search import sync as search_sync
from ..search.client import MeiliError, SearchUnavailableError
from ..search.indexes import SPECS
from ..security.audit import audit
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit
from .admin import _admin_app_only

admin_search_bp = Blueprint("admin_search", __name__, url_prefix="/api/admin/search")


def _changed(resource_id, **details) -> None:
    audit(AuditAction.SEARCH_CONFIG_CHANGED, "INFO", user_id=g.security.user_id, resource_type="intent_patterns",
          resource_id=resource_id, details=details or None)


def _pattern_dict(p: IntentPattern) -> dict:
    return {"id": p.id, "intent": p.intent, "subtype": p.subtype, "pattern": p.pattern, "priority": p.priority,
            "description": p.description, "is_active": p.is_active, "created_by": p.created_by,
            "created_at": iso(p.created_at), "updated_at": iso(p.updated_at)}


def _check_pattern(intent: str, subtype: str | None, pattern: str | None) -> None:
    if pattern is not None and (error := intent_service.validate_pattern(pattern)):
        raise ValidationError(error, fields={"pattern": error})
    if subtype is not None and subtype not in intent_service.SUBTYPES[intent] and subtype != "":
        options = ", ".join(s for s in intent_service.SUBTYPES[intent] if s) or "(vacío)"
        raise ValidationError(f"Subtipo no válido para {intent}. Opciones: {options}.")


# ------------------------------------------------------------------ Patrones
@admin_search_bp.get("/intent-patterns")
@platform_guard
@_admin_app_only
@require_permission("search", "read")
@rate_limit("RATE_LIMIT_READ")
def list_patterns():
    stmt = db.select(IntentPattern).order_by(IntentPattern.priority, IntentPattern.id)
    if request.args.get("include_inactive") != "true":
        stmt = stmt.where(IntentPattern.is_active.is_(True))
    return jsonify(items=[_pattern_dict(p) for p in db.session.scalars(stmt)])


@admin_search_bp.post("/intent-patterns")
@platform_guard
@_admin_app_only
@require_permission("search", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_pattern():
    data = parse_body(IntentPatternIn)
    _check_pattern(data.intent, data.subtype, data.pattern)
    p = IntentPattern(intent=data.intent, subtype=data.subtype, pattern=data.pattern, priority=data.priority,
                      description=data.description, created_by=g.security.user_id)
    db.session.add(p)
    db.session.commit()
    intent_service.invalidate_patterns()
    _changed(p.id, action="create", intent=p.intent, pattern=p.pattern)
    return jsonify(_pattern_dict(p)), 201


@admin_search_bp.patch("/intent-patterns/<int:pattern_id>")
@platform_guard
@_admin_app_only
@require_permission("search", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_pattern(pattern_id: int):
    p = db.session.get(IntentPattern, pattern_id)
    if p is None:
        raise NotFoundError("Patrón no encontrado.")
    data = parse_body(IntentPatternPatch)
    changes = data.model_dump(exclude_unset=True)
    new_intent = changes.get("intent", p.intent)
    _check_pattern(new_intent, changes.get("subtype", p.subtype if "intent" in changes else None),
                   changes.get("pattern"))
    before = _pattern_dict(p)
    for key, value in changes.items():
        setattr(p, key, value)
    db.session.commit()
    intent_service.invalidate_patterns()
    _changed(p.id, action="update", before={k: before[k] for k in changes}, after=changes)
    return jsonify(_pattern_dict(p))


@admin_search_bp.delete("/intent-patterns/<int:pattern_id>")
@platform_guard
@_admin_app_only
@require_permission("search", "write")
@rate_limit("RATE_LIMIT_WRITE")
def deactivate_pattern(pattern_id: int):
    p = db.session.get(IntentPattern, pattern_id)
    if p is None:
        raise NotFoundError("Patrón no encontrado.")
    p.is_active = False  # se desactiva, no se borra: queda el histórico
    db.session.commit()
    intent_service.invalidate_patterns()
    _changed(p.id, action="deactivate")
    return "", 204


@admin_search_bp.post("/intent/test")
@platform_guard
@_admin_app_only
@require_permission("search", "read")
@rate_limit("RATE_LIMIT_AI")
def test_intent():
    """Prueba una frase sin registrarla: qué patrones coinciden y qué decidiría el clasificador."""
    data = parse_body(IntentTestIn)
    patterns = intent_service.load_patterns()
    first = intent_service.classify_patterns(data.query, patterns)
    result = intent_service.classify(data.query, g.security.user_id, use_llm=data.use_llm)
    by_id = {p["id"]: p for p in patterns}
    return jsonify({"normalized": intent_service.normalize(data.query), "result": result.to_dict(),
                    "layer1": first.to_dict() | {"matched": [by_id[i] for i in first.matched]},
                    "llm_filters": result.filters or None, "usage_log_id": result.usage_log_id})


# ------------------------------------------------------------------ Calidad
def _days() -> int:
    try:
        return max(1, min(90, int(request.args.get("days", 7))))
    except ValueError as exc:
        raise ValidationError("'days' debe ser un número.") from exc


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


@admin_search_bp.get("/quality")
@platform_guard
@_admin_app_only
@require_permission("search", "read")
@rate_limit("RATE_LIMIT_READ")
def quality():
    days = _days()
    since = utcnow() - timedelta(days=days)
    Q = SearchQueryLog
    in_window = Q.created_at >= since
    assistant = db.and_(in_window, Q.channel == "assistant")

    totals = dict(db.session.execute(db.select(Q.channel, func.count()).where(in_window).group_by(Q.channel)).all())
    n_assistant = totals.get("assistant", 0)
    intents = [{"intent": i, "count": c, "avg_confidence": round(float(a or 0), 3)} for i, c, a in db.session.execute(
        db.select(Q.intent, func.count(), func.avg(Q.confidence)).where(assistant).group_by(Q.intent)).all()]
    layers = dict(db.session.execute(db.select(Q.layer, func.count()).where(assistant).group_by(Q.layer)).all())
    reformulated = db.session.scalar(db.select(func.count()).where(in_window, Q.reformulated.is_(True))) or 0
    total = sum(totals.values())
    with_results = db.session.scalar(db.select(func.count()).where(in_window, Q.result_count > 0)) or 0
    clicked = db.session.scalar(db.select(func.count()).where(in_window, Q.first_click_at.is_not(None))) or 0
    zero = db.session.scalar(db.select(func.count()).where(in_window, Q.result_count == 0)) or 0
    top_zero = [{"query": t, "count": c} for t, c in db.session.execute(
        db.select(func.min(Q.query_text), func.count()).where(in_window, Q.result_count == 0)
        .group_by(Q.query_hash).order_by(func.count().desc()).limit(10)).all()]
    wrong = [{"classified": i, "expected": e, "count": c} for i, e, c in db.session.execute(
        db.select(Q.intent, Q.expected_intent, func.count()).where(
            assistant, Q.expected_intent.is_not(None), Q.expected_intent != Q.intent)
        .group_by(Q.intent, Q.expected_intent)).all()]
    rated = db.session.execute(db.select(func.count(Q.user_rating), func.avg(Q.user_rating)).where(
        in_window, Q.user_rating.is_not(None))).one()

    sample = db.session.execute(db.select(Q.classify_ms, Q.created_at, Q.first_click_at).where(assistant)
                                .order_by(Q.id.desc()).limit(5000)).all()
    classify = sorted(r[0] for r in sample if r[0] is not None)
    clicks = db.session.execute(db.select(Q.created_at, Q.first_click_at).where(
        in_window, Q.first_click_at.is_not(None)).order_by(Q.id.desc()).limit(5000)).all()
    to_click = [(c - s).total_seconds() for s, c in clicks]
    daily = {}
    for day, i, c in db.session.execute(db.select(func.date(Q.created_at), Q.intent, func.count()).where(assistant)
                                        .group_by(func.date(Q.created_at), Q.intent)).all():
        daily.setdefault(str(day), {})[i or "none"] = c

    layer1 = layers.get("pattern", 0)
    warnings = []
    if n_assistant >= 50:
        share = layer1 / n_assistant
        if share < 0.7:
            warnings.append("La capa de patrones resuelve menos del 70 % de las consultas: faltan patrones "
                            "para formas nuevas de preguntar.")
        elif share > 0.95:
            warnings.append("La capa de patrones resuelve más del 95 %: revisa que no clasifique con falsa "
                            "confianza consultas ambiguas.")
        if layers.get("fallback", 0) / n_assistant > 0.1:
            warnings.append("Más del 10 % de las consultas acaban en el plan B: revisa el prompt "
                            "intent.classify o la disponibilidad de la IA.")
    if total >= 50 and reformulated / total > 0.3:
        warnings.append("Más del 30 % de las consultas se reformulan enseguida: los resultados no convencen.")

    return jsonify({
        "days": days, "totals": totals, "intents": intents,
        "layers": {k or "none": v for k, v in layers.items()},
        "layer1_share_pct": _pct(layer1, n_assistant),
        "reformulation_rate_pct": _pct(reformulated, total),
        "click_through_rate_pct": _pct(clicked, with_results),
        "median_seconds_to_first_click": round(statistics.median(to_click), 1) if to_click else None,
        "zero_results_pct": _pct(zero, total), "top_zero_result_queries": top_zero,
        "misclassified": wrong, "ratings": {"count": rated[0], "average": round(float(rated[1]), 2) if rated[1] else None},
        "classify_ms": {"p50": classify[len(classify) // 2] if classify else None,
                        "p95": classify[int(len(classify) * 0.95)] if classify else None},
        "daily": daily, "warnings": warnings,
    })


# ------------------------------------------------------------------ Índices
@admin_search_bp.get("/indexes")
@platform_guard
@_admin_app_only
@require_permission("search", "read")
@rate_limit("RATE_LIMIT_READ")
def indexes():
    try:
        items = search_sync.status()
    except MeiliError as exc:
        raise SearchUnavailableError(f"Meilisearch no responde: {exc}") from exc
    return jsonify(items=items)


@admin_search_bp.post("/reindex")
@platform_guard
@_admin_app_only
@require_permission("search", "write")
@rate_limit("RATE_LIMIT_EXPORT")
def reindex():
    """Reconstruye uno o todos los índices en segundo plano, sin cortar las búsquedas."""
    from ..tasks.search import rebuild_index

    data = parse_body(ReindexIn)
    names = [data.index] if data.index else list(SPECS)
    tasks = {name: enqueue(rebuild_index, name, priority=PRIORITY_USER) for name in names}
    audit(AuditAction.SEARCH_CONFIG_CHANGED, "INFO", user_id=g.security.user_id, resource_type="search_index",
          details={"action": "reindex", "indexes": names})
    return jsonify({"queued": names, "task_ids": tasks}), 202
