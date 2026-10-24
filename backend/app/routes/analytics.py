"""Inteligencia de negocio (app ``analytics``, fases 6b y 9a).

Solo dentro de la app analytics (``X-App-Code: analytics``).

- Cuadro de mando y valor de la IA (``dashboards.read``).
- Mapa de oportunidad: puntuación por sector y línea; los pesos y el recálculo
  piden ``dashboards.write``.
- Objetivos de negocio (``dashboards``) y competidores (``competitors``).
- Importación desde Excel con comprobación previa (``dashboards.write``).
- «Pregunta a tus datos» (módulo de IA ``analytics_assistant``).
"""
from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from ..ai import analytics_qa
from ..ai import roi as roi_service
from ..api.common import (apply_changes, check_version, get_active, iso, like_pattern, money, paginate,
                          parse_body, record_audit)
from ..api.schemas import AnalyticsAskIn, CompetitorIn, CompetitorPatch, HeatmapConfigIn, TargetIn, TargetPatch
from ..errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from ..extensions import db
from ..models import AuditAction, BusinessTarget, CompetitorProfile, ServiceLine
from ..security.audit import audit
from ..security.context import platform_guard, require_ai_module, require_permission
from ..security.ratelimit import rate_limit
from ..services import analytics as service
from ..services import bi_import, market

IMPORT_MAX_BYTES = 5 * 1024 * 1024
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


def _analytics_app_only(fn):
    """Estas rutas solo existen dentro de la app analytics."""
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.security.app_code != "analytics":
            audit(AuditAction.ACCESS_DENIED, "WARNING", user_id=g.security.user_id,
                  details={"path": request.path, "app": g.security.app_code})
            raise ForbiddenError("Usa la aplicación analytics (cabecera X-App-Code: analytics).")
        return fn(*args, **kwargs)

    return wrapper


def _months() -> int:
    try:
        return max(1, min(36, int(request.args.get("months", 12))))
    except ValueError as exc:
        raise ValidationError("'months' debe ser un número.") from exc


def _text(name: str) -> str | None:
    value = (request.args.get(name) or "").strip()
    return value[:100] or None


@analytics_bp.get("/overview")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "read")
@rate_limit("RATE_LIMIT_READ")
def overview():
    return jsonify(service.overview(_months(), service_line=_text("service_line"), sector=_text("sector")))


@analytics_bp.get("/ai")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "read")
@rate_limit("RATE_LIMIT_READ")
def ai_value():
    """Valor de la IA para negocio: ahorro estimado frente a su coste, y gasto por mes."""
    months = _months()
    since = service.period_start(months)
    return jsonify({"months": months, "roi": roi_service.summary(since), "monthly": service.ai_costs(months)})


# ---------------------------------------------------------------- Mapa de oportunidad (fase 9a)
@analytics_bp.get("/heatmap")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "read")
@rate_limit("RATE_LIMIT_READ")
def heatmap():
    period = market.validate_period(request.args.get("period") or market.current_period())
    data = market.heatmap(period)
    config = market.config_dict(market.get_config())
    db.session.commit()  # la configuración por defecto se crea la primera vez
    available = market.periods()
    if data is None:
        raise NotFoundError(f"No hay puntuaciones de {period}. Último mes calculado: "
                            f"{available[0] if available else 'ninguno'}.")
    return jsonify({**data, "config": config, "periods": available})


@analytics_bp.put("/heatmap/config")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_heatmap_config():
    data = parse_body(HeatmapConfigIn)
    config = market.get_config()
    check_version(config, data.version)
    changed = apply_changes(config, data.model_dump(exclude={"version"}))
    db.session.commit()
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, config, fields=changed)
        market.compute()  # el mes en curso, con los pesos nuevos
    return jsonify(market.config_dict(config))


@analytics_bp.post("/heatmap/recalculate")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "write")
@rate_limit("RATE_LIMIT_WRITE")
def recalculate_heatmap():
    return jsonify(market.compute())


@analytics_bp.get("/service-lines")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "read")
@rate_limit("RATE_LIMIT_READ")
def service_lines():
    """Catálogo de líneas para los formularios de Analítica (sin permiso de portfolio)."""
    return jsonify(paginate(ServiceLine.select_active().order_by(ServiceLine.name),
                            lambda line: {"code": line.code, "name": line.name}))


# ---------------------------------------------------------------- Objetivos
def target_dict(t: BusinessTarget) -> dict:
    return {"id": t.id, "metric": t.metric, "period": t.period, "service_line": t.service_line,
            "target_value": money(t.target_value), "version": t.row_version, "updated_at": iso(t.updated_at)}


@analytics_bp.get("/targets")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "read")
@rate_limit("RATE_LIMIT_READ")
def list_targets():
    stmt = BusinessTarget.select_active().order_by(BusinessTarget.period.desc(), BusinessTarget.metric,
                                                   BusinessTarget.service_line)
    if year := (request.args.get("year") or "").strip():
        if not year.isdigit() or len(year) != 4:
            raise ValidationError("'year' debe ser un año de cuatro cifras.")
        stmt = stmt.where(BusinessTarget.period.like(f"{year}-%"))
    return jsonify(paginate(stmt, target_dict))


def _check_line(code: str) -> None:
    if code and db.session.scalar(db.select(ServiceLine.code).filter_by(code=code)) is None:
        raise ValidationError(f"Línea de servicio desconocida: {code}.")


@analytics_bp.post("/targets")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_target():
    data = parse_body(TargetIn)
    _check_line(data.service_line)
    target = db.session.scalar(db.select(BusinessTarget).filter_by(
        metric=data.metric, period=data.period, service_line=data.service_line))
    if target is not None and target.is_active:
        raise ConflictError("Ya hay un objetivo para esa métrica, mes y línea: edítalo.")
    if target is None:
        target = BusinessTarget(**data.model_dump(), created_by=g.security.user_id)
        db.session.add(target)
    else:  # estaba borrado: se recupera con el valor nuevo
        target.restore()
        target.target_value = data.target_value
    db.session.commit()
    record_audit(AuditAction.RECORD_CREATED, target)
    return jsonify(target_dict(target)), 201


@analytics_bp.patch("/targets/<int:target_id>")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_target(target_id: int):
    target = get_active(BusinessTarget, target_id, "Objetivo")
    data = parse_body(TargetPatch)
    check_version(target, data.version)
    if apply_changes(target, {"target_value": data.target_value}):
        db.session.commit()
        record_audit(AuditAction.RECORD_UPDATED, target, fields=["target_value"])
    return jsonify(target_dict(target))


@analytics_bp.delete("/targets/<int:target_id>")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "write")
@rate_limit("RATE_LIMIT_WRITE")
def delete_target(target_id: int):
    target = get_active(BusinessTarget, target_id, "Objetivo")
    target.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, target)
    return "", 204


# ---------------------------------------------------------------- Competidores
def competitor_dict(c: CompetitorProfile) -> dict:
    return {"id": c.id, "name": c.name, "competitor_type": c.competitor_type, "website": c.website,
            "description": c.description, "strengths": c.strengths, "weaknesses": c.weaknesses,
            "opportunities": c.opportunities, "threats": c.threats, "service_lines": c.service_lines,
            "sectors": c.sectors, "price_positioning": c.price_positioning, "version": c.row_version,
            "updated_at": iso(c.updated_at)}


def _check_lines(codes: list[str] | None) -> None:
    if not codes:
        return
    known = set(db.session.scalars(db.select(ServiceLine.code)))
    unknown = [c for c in codes if c not in known]
    if unknown:
        raise ValidationError(f"Línea de servicio desconocida: {unknown[0]}.")


def _commit_competitor() -> None:
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ConflictError("Ya hay un competidor con ese nombre.") from exc


@analytics_bp.get("/competitors")
@platform_guard
@_analytics_app_only
@require_permission("competitors", "read")
@rate_limit("RATE_LIMIT_READ")
def list_competitors():
    stmt = CompetitorProfile.select_active().order_by(CompetitorProfile.name)
    if pattern := like_pattern(request.args.get("q")):
        stmt = stmt.where(or_(CompetitorProfile.name.like(pattern, escape="\\"),
                              CompetitorProfile.description.like(pattern, escape="\\")))
    if kind := request.args.get("type"):
        stmt = stmt.where(CompetitorProfile.competitor_type == kind)
    items = paginate(stmt, competitor_dict)
    # Filtros que viven en listas JSON: se aplican sobre la página (los competidores son decenas)
    if line := request.args.get("service_line"):
        items["items"] = [c for c in items["items"] if line in c["service_lines"]]
    return jsonify(items)


@analytics_bp.post("/competitors")
@platform_guard
@_analytics_app_only
@require_permission("competitors", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_competitor():
    data = parse_body(CompetitorIn)
    _check_lines(data.service_lines)
    existing = db.session.scalar(db.select(CompetitorProfile).where(CompetitorProfile.name == data.name))
    if existing is not None and not existing.is_active:
        existing.restore()
        apply_changes(existing, data.model_dump())
        competitor = existing
    else:
        competitor = CompetitorProfile(**data.model_dump(), created_by=g.security.user_id)
        db.session.add(competitor)
    _commit_competitor()
    record_audit(AuditAction.RECORD_CREATED, competitor)
    return jsonify(competitor_dict(competitor)), 201


@analytics_bp.get("/competitors/<int:competitor_id>")
@platform_guard
@_analytics_app_only
@require_permission("competitors", "read")
@rate_limit("RATE_LIMIT_READ")
def get_competitor(competitor_id: int):
    return jsonify(competitor_dict(get_active(CompetitorProfile, competitor_id, "Competidor")))


@analytics_bp.patch("/competitors/<int:competitor_id>")
@platform_guard
@_analytics_app_only
@require_permission("competitors", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_competitor(competitor_id: int):
    competitor = get_active(CompetitorProfile, competitor_id, "Competidor")
    data = parse_body(CompetitorPatch)
    check_version(competitor, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    _check_lines(changes.get("service_lines"))
    for field in ("strengths", "weaknesses", "opportunities", "threats", "service_lines", "sectors"):
        if field in changes and changes[field] is None:
            changes[field] = []
    changed = apply_changes(competitor, changes, required=("name", "competitor_type", "price_positioning"))
    _commit_competitor()
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, competitor, fields=changed)
    return jsonify(competitor_dict(competitor))


@analytics_bp.delete("/competitors/<int:competitor_id>")
@platform_guard
@_analytics_app_only
@require_permission("competitors", "delete")
@rate_limit("RATE_LIMIT_WRITE")
def delete_competitor(competitor_id: int):
    competitor = get_active(CompetitorProfile, competitor_id, "Competidor")
    competitor.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, competitor)
    return "", 204


# ---------------------------------------------------------------- Importación desde Excel
@analytics_bp.get("/import/template")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "read")
@rate_limit("RATE_LIMIT_EXPORT")
def import_template():
    return Response(bi_import.template(), mimetype=XLSX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="plantilla-analitica.xlsx"'})


@analytics_bp.post("/import")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "write")
@rate_limit("RATE_LIMIT_UPLOAD")
def import_excel():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ValidationError("Adjunta un fichero Excel (.xlsx) en el campo «file».")
    if not upload.filename.lower().endswith(".xlsx"):
        raise ValidationError("Solo se admiten ficheros .xlsx.")
    content = upload.read(IMPORT_MAX_BYTES + 1)
    if len(content) > IMPORT_MAX_BYTES:
        raise ValidationError("El fichero supera los 5 MB.")
    if not content.startswith(b"PK"):
        raise ValidationError("El fichero no es un Excel (.xlsx) válido.")
    dry_run = request.args.get("dry_run", "true").lower() != "false"
    ctx = g.security
    result = bi_import.process(content, dry_run=dry_run, user_id=ctx.user_id,
                               can_competitors=ctx.can("competitors", "write"),
                               can_targets=ctx.can("dashboards", "write"))
    if result["applied"]:
        audit(AuditAction.RECORD_UPDATED, "INFO", user_id=ctx.user_id, resource_type="bi_import",
              details={"file": upload.filename[:200], **{name: {"create": s["create"], "update": s["update"]}
                                                       for name, s in result["sheets"].items()}})
    return jsonify(result)


# ---------------------------------------------------------------- Pregunta a tus datos
@analytics_bp.post("/ask")
@platform_guard
@_analytics_app_only
@require_permission("dashboards", "read")
@require_ai_module("analytics_assistant")
@rate_limit("RATE_LIMIT_AI")
def ask():
    data = parse_body(AnalyticsAskIn)
    return jsonify(analytics_qa.ask(data.question, user_id=g.security.user_id, months=data.months,
                                    service_line=data.service_line, sector=data.sector))
