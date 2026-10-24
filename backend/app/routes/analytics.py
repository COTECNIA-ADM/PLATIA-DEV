"""Cuadro de mando de negocio (app ``analytics``, fase 6b).

Solo lectura y solo dentro de la app analytics (``X-App-Code: analytics``), con el
permiso ``dashboards.read``. Las cifras salen de ``app/services/analytics.py``.
"""
from flask import Blueprint, g, jsonify, request

from ..ai import roi as roi_service
from ..errors import ForbiddenError, ValidationError
from ..models import AuditAction
from ..security.audit import audit
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit
from ..services import analytics as service

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
