"""Gobernanza de la IA desde la app admin (Capítulo 11).

- Prompts versionados: publicar, activar una versión anterior, probar el render.
- Modelo por tipo de tarea (LLM Factory) y tabla de precios.
- Presupuestos con aviso, frenado y bloqueo.
- Uso y costes, retorno de la inversión y calidad.
- Colecciones de Qdrant y reindexado.
- Cumplimiento: datos personales en respuestas, peticiones bloqueadas, integridad
  de prompts, y exportación o borrado de los datos de IA de una persona (RGPD).

Todo exige ``X-App-Code: admin``. Los cambios de configuración quedan auditados.
"""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..ai import budget as budget_service
from ..ai import prompts as prompt_service
from ..ai import roi as roi_service
from ..ai.client import AIServiceError, get_ai_client
from ..api.common import iso, paginate, parse_body
from ..api.schemas import BaselineIn, BudgetIn, PricingIn, PromptPreviewIn, PromptPublishIn, ServiceConfigPatch
from ..errors import ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (AuditAction, AuditLog, BudgetConfig, Document, HumanBaselineConfig, LLMModelPricing,
                      LLMQualityScore, LLMServiceConfig, LLMUsageLog, Prompt, SearchQueryLog, TaskCompletionLog, User,
                      utcnow)
from ..queue import PRIORITY_MAINTENANCE, enqueue
from ..security.audit import audit
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit
from .admin import _admin_app_only

admin_ai_bp = Blueprint("admin_ai", __name__, url_prefix="/api/admin/ai")


def _days(default: int = 30) -> int:
    try:
        return max(1, min(366, int(request.args.get("days", default))))
    except ValueError as exc:
        raise ValidationError("'days' debe ser un número.") from exc


def _changed(resource_type: str, resource_id, **details) -> None:
    audit(AuditAction.AI_CONFIG_CHANGED, "INFO", user_id=g.security.user_id, resource_type=resource_type,
          resource_id=resource_id, details=details or None)


# ------------------------------------------------------------------ Prompts
def _prompt_dict(p: Prompt, full: bool = False) -> dict:
    out = {"id": p.id, "name": p.name, "version": p.version, "service_type": p.service_type,
           "description": p.description, "notes": p.notes, "is_active": p.is_active,
           "variables": sorted(prompt_service.variables_of(p.system_prompt, p.user_template)),
           "content_hash": p.content_hash, "created_by": p.created_by, "created_at": iso(p.created_at),
           "archived_at": iso(p.archived_at)}
    if full:
        out.update(system_prompt=p.system_prompt, user_template=p.user_template)
    return out


@admin_ai_bp.get("/prompts")
@platform_guard
@_admin_app_only
@require_permission("prompts", "read")
@rate_limit("RATE_LIMIT_READ")
def list_prompts():
    rows = db.session.scalars(db.select(Prompt).filter_by(is_active=True).order_by(Prompt.name)).all()
    integrity = {v["name"] for v in prompt_service.verify_integrity()}
    return jsonify(items=[{**_prompt_dict(p), "integrity_ok": p.name not in integrity} for p in rows])


@admin_ai_bp.get("/prompts/<name>/versions")
@platform_guard
@_admin_app_only
@require_permission("prompts", "read")
@rate_limit("RATE_LIMIT_READ")
def prompt_versions(name: str):
    rows = db.session.scalars(db.select(Prompt).filter_by(name=name).order_by(Prompt.version.desc())).all()
    if not rows:
        raise NotFoundError("Prompt no encontrado.")
    return jsonify(items=[_prompt_dict(p, full=True) for p in rows])


@admin_ai_bp.post("/prompts")
@platform_guard
@_admin_app_only
@require_permission("prompts", "write")
@rate_limit("RATE_LIMIT_WRITE")
def publish_prompt():
    data = parse_body(PromptPublishIn)
    prompt = prompt_service.publish(data.name, data.system_prompt, data.user_template, author_id=g.security.user_id,
                                    notes=data.notes, service_type=data.service_type, description=data.description,
                                    activate=data.activate)
    db.session.commit()
    audit(AuditAction.PROMPT_PUBLISHED, "INFO", user_id=g.security.user_id, resource_type="prompts",
          resource_id=prompt.id, details={"name": prompt.name, "version": prompt.version, "active": prompt.is_active})
    return jsonify(_prompt_dict(prompt, full=True)), 201


@admin_ai_bp.post("/prompts/<name>/versions/<int:version>/activate")
@platform_guard
@_admin_app_only
@require_permission("prompts", "write")
@rate_limit("RATE_LIMIT_WRITE")
def activate_prompt(name: str, version: int):
    prompt = db.session.scalar(db.select(Prompt).filter_by(name=name, version=version))
    if prompt is None:
        raise NotFoundError("Versión de prompt no encontrada.")
    prompt_service.activate_version(prompt)
    db.session.commit()
    audit(AuditAction.PROMPT_ACTIVATED, "INFO", user_id=g.security.user_id, resource_type="prompts",
          resource_id=prompt.id, details={"name": name, "version": version})
    return jsonify(_prompt_dict(prompt))


@admin_ai_bp.post("/prompts/<name>/preview")
@platform_guard
@_admin_app_only
@require_permission("prompts", "read")
@rate_limit("RATE_LIMIT_WRITE")
def preview_prompt(name: str):
    """Muestra el prompt con variables de ejemplo. No llama al modelo."""
    data = parse_body(PromptPreviewIn)
    active = prompt_service.get_active(name)
    missing = prompt_service.variables_of(active.system_prompt, active.user_template) - set(data.variables)
    variables = {**{v: f"<{v}>" for v in missing}, **data.variables}
    system, user = active.render(variables)
    return jsonify({"name": name, "version": active.version, "system": system, "user": user,
                    "placeholders": sorted(missing)})


# ------------------------------------------------------------------ Servicios y precios
def _service_dict(c: LLMServiceConfig) -> dict:
    return {"service_type": c.service_type, "provider": c.provider, "model_name": c.model_name,
            "fallback_provider": c.fallback_provider, "fallback_model": c.fallback_model,
            "max_tokens": c.max_tokens, "effort": c.effort, "prompt_name": c.prompt_name,
            "description": c.description, "is_active": c.is_active, "updated_at": iso(c.updated_at)}


@admin_ai_bp.get("/services")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "read")
@rate_limit("RATE_LIMIT_READ")
def list_services():
    rows = db.session.scalars(db.select(LLMServiceConfig).order_by(LLMServiceConfig.service_type)).all()
    return jsonify(items=[_service_dict(c) for c in rows])


@admin_ai_bp.patch("/services/<service_type>")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_service(service_type: str):
    config = db.session.get(LLMServiceConfig, service_type)
    if config is None:
        raise NotFoundError("Tipo de tarea no encontrado.")
    changes = parse_body(ServiceConfigPatch).model_dump(exclude_unset=True)
    if "prompt_name" in changes and changes["prompt_name"]:
        prompt_service.get_active(changes["prompt_name"])  # 404 si no existe
    before = {k: getattr(config, k) for k in changes}
    for key, value in changes.items():
        if key in ("provider", "model_name", "max_tokens") and value is None:
            raise ValidationError(f"'{key}' no puede quedar vacío.")
        setattr(config, key, value)
    db.session.commit()
    _changed("llm_service_config", service_type, before=before, after=changes)
    return jsonify(_service_dict(config))


def _pricing_dict(p: LLMModelPricing) -> dict:
    def f(v):
        return None if v is None else f"{v:.4f}"

    return {"provider": p.provider, "model_name": p.model_name, "effective_date": p.effective_date.isoformat(),
            "input_usd_per_mtok": f(p.input_usd_per_mtok), "output_usd_per_mtok": f(p.output_usd_per_mtok),
            "cache_read_usd_per_mtok": f(p.cache_read_usd_per_mtok),
            "cache_write_usd_per_mtok": f(p.cache_write_usd_per_mtok)}


@admin_ai_bp.get("/pricing")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "read")
@rate_limit("RATE_LIMIT_READ")
def list_pricing():
    rows = db.session.scalars(db.select(LLMModelPricing).order_by(
        LLMModelPricing.provider, LLMModelPricing.model_name, LLMModelPricing.effective_date.desc())).all()
    return jsonify(items=[_pricing_dict(p) for p in rows])


@admin_ai_bp.post("/pricing")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "write")
@rate_limit("RATE_LIMIT_WRITE")
def add_pricing():
    """Un precio nuevo es una fila nueva con su fecha: los costes ya registrados no cambian."""
    data = parse_body(PricingIn)
    row = LLMModelPricing(**data.model_dump())
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ConflictError("Ya hay un precio para ese modelo con esa fecha.") from exc
    _changed("llm_model_pricing", f"{row.provider}:{row.model_name}:{row.effective_date}")
    return jsonify(_pricing_dict(row)), 201


# ------------------------------------------------------------------ Presupuestos
@admin_ai_bp.get("/budgets")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "read")
@rate_limit("RATE_LIMIT_READ")
def list_budgets():
    return jsonify(items=budget_service.overview())


def _check_budget_scope(data: BudgetIn) -> None:
    if data.scope == "global" and data.scope_id:
        raise ValidationError("Un presupuesto global no lleva 'scope_id'.")
    if data.scope == "service" and db.session.get(LLMServiceConfig, data.scope_id) is None:
        raise ValidationError("'scope_id' debe ser un tipo de tarea existente.")
    if data.scope == "user" and data.scope_id and (not data.scope_id.isdigit()
                                                   or db.session.get(User, int(data.scope_id)) is None):
        raise ValidationError("'scope_id' debe ser el id de un usuario (o vacío para cada usuario).")


@admin_ai_bp.post("/budgets")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_budget():
    data = parse_body(BudgetIn)
    _check_budget_scope(data)
    row = BudgetConfig(**data.model_dump(), created_by=g.security.user_id)
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ConflictError("Ya existe un presupuesto con ese ámbito; modifícalo.") from exc
    _changed("budget_configs", row.id, **data.model_dump(mode="json"))
    return jsonify(next(b for b in budget_service.overview() if b["id"] == row.id)), 201


@admin_ai_bp.put("/budgets/<int:budget_id>")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "write")
@rate_limit("RATE_LIMIT_WRITE")
def replace_budget(budget_id: int):
    row = db.session.get(BudgetConfig, budget_id)
    if row is None:
        raise NotFoundError("Presupuesto no encontrado.")
    data = parse_body(BudgetIn)
    _check_budget_scope(data)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ConflictError("Ya existe otro presupuesto con ese ámbito.") from exc
    _changed("budget_configs", row.id, **data.model_dump(mode="json"))
    return jsonify(next(b for b in budget_service.overview() if b["id"] == row.id))


# ------------------------------------------------------------------ Uso, ROI y calidad
def _usage_dict(u: LLMUsageLog) -> dict:
    return {"id": u.id, "service_type": u.service_type, "provider": u.provider, "model": u.model_name,
            "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
            "cache_read_tokens": u.cache_read_tokens, "cache_write_tokens": u.cache_write_tokens,
            "cost_usd": f"{u.cost_usd or 0:.6f}", "latency_ms": u.latency_ms, "success": u.success,
            "error_type": u.error_type, "stop_reason": u.stop_reason, "is_fallback": u.is_fallback,
            "prompt_id": u.prompt_id, "user_id": u.user_id, "correlation_id": u.correlation_id,
            "contained_pii": u.contained_pii, "created_at": iso(u.created_at)}


@admin_ai_bp.get("/usage")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "read")
@rate_limit("RATE_LIMIT_READ")
def list_usage():
    stmt = db.select(LLMUsageLog).where(LLMUsageLog.created_at >= utcnow() - timedelta(days=_days()))
    for field in ("service_type", "model_name", "correlation_id"):
        if value := request.args.get(field):
            stmt = stmt.where(getattr(LLMUsageLog, field) == value)
    if request.args.get("success") in ("true", "false"):
        stmt = stmt.where(LLMUsageLog.success.is_(request.args["success"] == "true"))
    if (user_id := request.args.get("user_id", "")).isdigit():
        stmt = stmt.where(LLMUsageLog.user_id == int(user_id))
    return jsonify(paginate(stmt.order_by(LLMUsageLog.id.desc()), _usage_dict))


@admin_ai_bp.get("/usage/summary")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "read")
@rate_limit("RATE_LIMIT_READ")
def usage_summary():
    since = utcnow() - timedelta(days=_days())
    u = LLMUsageLog
    rows = db.session.execute(
        db.select(u.service_type, u.model_name, db.func.count(), db.func.sum(u.input_tokens),
                  db.func.sum(u.output_tokens), db.func.sum(u.cache_read_tokens), db.func.sum(u.cost_usd),
                  db.func.sum(db.case((u.success.is_(False), 1), else_=0)),
                  db.func.sum(db.case((u.is_fallback.is_(True), 1), else_=0)), db.func.avg(u.latency_ms))
        .where(u.created_at >= since).group_by(u.service_type, u.model_name).order_by(u.service_type)
    ).all()
    items, total = [], Decimal(0)
    for service, model, calls, tin, tout, tcache, cost, errors, fallbacks, latency in rows:
        cost = Decimal(str(cost or 0))
        total += cost
        items.append({"service_type": service, "model": model, "calls": calls, "input_tokens": int(tin or 0),
                      "output_tokens": int(tout or 0), "cache_read_tokens": int(tcache or 0),
                      "cost_usd": f"{cost:.4f}", "errors": int(errors or 0), "fallbacks": int(fallbacks or 0),
                      "error_rate": round((errors or 0) / calls, 3) if calls else 0,
                      "avg_latency_ms": round(float(latency)) if latency is not None else None})
    return jsonify({"days": _days(), "items": items, "total_cost_usd": f"{total:.4f}"})


@admin_ai_bp.get("/roi")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "read")
@rate_limit("RATE_LIMIT_READ")
def roi():
    return jsonify(roi_service.summary(utcnow() - timedelta(days=_days())))


@admin_ai_bp.get("/baselines")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "read")
@rate_limit("RATE_LIMIT_READ")
def list_baselines():
    rows = db.session.scalars(db.select(HumanBaselineConfig).order_by(HumanBaselineConfig.service_type)).all()
    return jsonify(items=[{"service_type": b.service_type, "task_name": b.task_name,
                           "human_time_minutes": b.human_time_minutes,
                           "human_hourly_cost_eur": f"{b.human_hourly_cost_eur:.2f}"} for b in rows])


@admin_ai_bp.put("/baselines/<service_type>")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "write")
@rate_limit("RATE_LIMIT_WRITE")
def put_baseline(service_type: str):
    if db.session.get(LLMServiceConfig, service_type) is None:
        raise NotFoundError("Tipo de tarea no encontrado.")
    data = parse_body(BaselineIn)
    row = db.session.get(HumanBaselineConfig, service_type) or HumanBaselineConfig(service_type=service_type)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    db.session.add(row)
    db.session.commit()
    _changed("human_baseline_config", service_type, **data.model_dump(mode="json"))
    return jsonify({"service_type": service_type, **data.model_dump(mode="json")})


@admin_ai_bp.get("/quality")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "read")
@rate_limit("RATE_LIMIT_READ")
def quality():
    since = utcnow() - timedelta(days=_days())
    q = LLMQualityScore
    rows = db.session.execute(
        db.select(q.service_type, q.reviewer_type, db.func.count(), db.func.avg(q.composite_score),
                  db.func.avg(q.faithfulness_score), db.func.avg(q.relevance_score),
                  db.func.avg(q.hallucination_score), db.func.avg(q.user_rating))
        .where(q.created_at >= since).group_by(q.service_type, q.reviewer_type)
    ).all()

    def r(v):
        return None if v is None else round(float(v), 3)

    return jsonify(items=[{"service_type": s, "reviewer_type": t, "count": n, "composite": r(c),
                           "faithfulness": r(f), "relevance": r(rel), "hallucination": r(h), "user_rating": r(ur)}
                          for s, t, n, c, f, rel, h, ur in rows])


# ------------------------------------------------------------------ RAG
@admin_ai_bp.get("/rag/collections")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "read")
@rate_limit("RATE_LIMIT_READ")
def rag_collections():
    statuses = dict(db.session.execute(
        db.select(Document.index_status, db.func.count()).where(Document.is_active.is_(True))
        .group_by(Document.index_status)).all())
    try:
        qdrant = get_ai_client().collections()
    except AIServiceError as exc:
        qdrant = {"error": str(exc)}
    return jsonify({"documents_by_index_status": statuses, "qdrant": qdrant})


@admin_ai_bp.post("/rag/reindex")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "write")
@rate_limit("RATE_LIMIT_EXPORT")
def rag_reindex():
    """Reindexa los documentos (todos o solo los fallidos con ?only_failed=true)."""
    from ..tasks.ai import index_document

    stmt = db.select(Document.id).where(Document.is_active.is_(True), Document.extracted_text.is_not(None))
    if request.args.get("only_failed") == "true":
        stmt = stmt.where(Document.index_status.in_(("failed", "pending", "none")))
    ids = db.session.scalars(stmt).all()
    for doc_id in ids:
        enqueue(index_document, doc_id, priority=PRIORITY_MAINTENANCE)
    _changed("documents", None, action="reindex", count=len(ids))
    return jsonify({"queued": len(ids)}), 202


@admin_ai_bp.get("/health")
@platform_guard
@_admin_app_only
@require_permission("llm_config", "read")
@rate_limit("RATE_LIMIT_READ")
def ai_health():
    try:
        return jsonify(get_ai_client().health())
    except AIServiceError as exc:
        return jsonify({"status": "unreachable", "error": str(exc)}), 503


# ------------------------------------------------------------------ Cumplimiento
@admin_ai_bp.get("/compliance")
@platform_guard
@_admin_app_only
@require_permission("audit", "read")
@rate_limit("RATE_LIMIT_READ")
def compliance():
    since = utcnow() - timedelta(days=_days())
    actions = (AuditAction.AI_REQUEST_BLOCKED, AuditAction.AI_OUTPUT_BLOCKED, AuditAction.AI_BUDGET_EXCEEDED,
               AuditAction.PII_DETECTED_IN_OUTPUT, AuditAction.PROMPT_INTEGRITY_VIOLATION)
    counts = dict(db.session.execute(
        db.select(AuditLog.action, db.func.count()).where(AuditLog.action.in_(actions), AuditLog.created_at >= since)
        .group_by(AuditLog.action)).all())
    scanned = db.session.scalar(db.select(db.func.count()).select_from(LLMUsageLog).where(
        LLMUsageLog.created_at >= since, LLMUsageLog.contained_pii.is_not(None))) or 0
    with_pii = db.session.scalar(db.select(db.func.count()).select_from(LLMUsageLog).where(
        LLMUsageLog.created_at >= since, LLMUsageLog.contained_pii.is_(True))) or 0
    return jsonify({"days": _days(), "events": {a: counts.get(a, 0) for a in actions},
                    "outputs_scanned": scanned, "outputs_with_pii": with_pii,
                    "prompt_integrity": prompt_service.verify_integrity()})


@admin_ai_bp.get("/gdpr/users/<int:user_id>")
@platform_guard
@_admin_app_only
@require_permission("users", "write")
@rate_limit("RATE_LIMIT_EXPORT")
def gdpr_export(user_id: int):
    """Derecho de acceso: todo lo que la plataforma guarda del uso de IA de una persona."""
    if db.session.get(User, user_id) is None:
        raise NotFoundError("Usuario no encontrado.")
    usage = db.session.scalars(db.select(LLMUsageLog).filter_by(user_id=user_id).order_by(LLMUsageLog.id)).all()
    ratings = db.session.scalars(db.select(LLMQualityScore).filter_by(reviewer_type="user", reviewer_id=user_id)).all()
    tasks = db.session.scalars(db.select(TaskCompletionLog).filter_by(user_id=user_id)).all()
    queries = db.session.scalars(db.select(SearchQueryLog).filter_by(user_id=user_id).order_by(SearchQueryLog.id)).all()
    audit(AuditAction.GDPR_AI_EXPORT, "INFO", user_id=g.security.user_id, resource_type="users", resource_id=user_id)
    return jsonify({
        "user_id": user_id, "generated_at": iso(utcnow()),
        "llm_calls": [{**_usage_dict(u), "output_sample": u.output_sample} for u in usage],
        "ratings": [{"usage_log_id": r.usage_log_id, "rating": r.user_rating, "comment": r.notes,
                     "created_at": iso(r.created_at)} for r in ratings],
        "tasks": [{"service_type": t.service_type, "subject_type": t.subject_type, "subject_id": t.subject_id,
                   "created_at": iso(t.created_at)} for t in tasks],
        "search_queries": [{"channel": q.channel, "query": q.query_text, "intent": q.intent, "rating": q.user_rating,
                            "created_at": iso(q.created_at)} for q in queries],
    })


@admin_ai_bp.post("/gdpr/users/<int:user_id>/erase")
@platform_guard
@_admin_app_only
@require_permission("users", "write")
@rate_limit("RATE_LIMIT_EXPORT")
def gdpr_erase(user_id: int):
    """Derecho de supresión: desvincula el uso de IA de la persona. Se conservan los
    importes y tokens (contabilidad) sin nada que la identifique."""
    if db.session.get(User, user_id) is None:
        raise NotFoundError("Usuario no encontrado.")
    calls = db.session.execute(db.update(LLMUsageLog).where(LLMUsageLog.user_id == user_id)
                               .values(user_id=None, output_sample=None, request_id=None)).rowcount
    ratings = db.session.execute(db.update(LLMQualityScore).where(
        LLMQualityScore.reviewer_type == "user", LLMQualityScore.reviewer_id == user_id)
        .values(reviewer_id=None, notes=None)).rowcount
    tasks = db.session.execute(db.update(TaskCompletionLog).where(TaskCompletionLog.user_id == user_id)
                               .values(user_id=None)).rowcount
    # Las consultas se conservan para las métricas del buscador, sin texto ni persona
    queries = db.session.execute(db.update(SearchQueryLog).where(SearchQueryLog.user_id == user_id)
                                 .values(user_id=None, query_text=None)).rowcount
    db.session.commit()
    audit(AuditAction.GDPR_AI_ERASURE, "WARNING", user_id=g.security.user_id, resource_type="users",
          resource_id=user_id, details={"llm_calls": calls, "ratings": ratings, "tasks": tasks, "search_queries": queries})
    return jsonify({"user_id": user_id, "llm_calls": calls, "ratings": ratings, "tasks": tasks,
                    "search_queries": queries})
