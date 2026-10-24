"""Notificaciones del usuario y alertas proactivas (Apéndice B, ``notifications`` y ``alerts``).

Cada usuario solo ve sus notificaciones: el filtro por usuario va en la consulta,
y una notificación ajena responde 404 (no 403) para no revelar que existe.
"""
from flask import Blueprint, g, jsonify, request
from sqlalchemy import func

from ..api.common import get_active, iso, paginate, record_audit
from ..errors import NotFoundError
from ..extensions import db
from ..models import Alert, AuditAction, Notification, utcnow
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit

inbox_bp = Blueprint("inbox", __name__, url_prefix="/api")


def notification_dict(n: Notification) -> dict:
    return {"id": n.id, "type": n.notification_type, "priority": n.priority, "title": n.title,
            "body": n.body, "link": n.link, "read_at": iso(n.read_at), "created_at": iso(n.created_at)}


def _mine():
    return Notification.select_active().where(Notification.user_id == g.security.user_id)


@inbox_bp.get("/notifications")
@platform_guard
@require_permission("notifications", "read")
@rate_limit("RATE_LIMIT_READ")
def list_notifications():
    stmt = _mine()
    if request.args.get("unread") == "true":
        stmt = stmt.where(Notification.read_at.is_(None))
    if ntype := request.args.get("type"):
        stmt = stmt.where(Notification.notification_type == ntype)
    return jsonify(paginate(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()),
                            notification_dict))


@inbox_bp.get("/notifications/unread-count")
@platform_guard
@require_permission("notifications", "read")
@rate_limit("RATE_LIMIT_READ")
def unread_count():
    count = db.session.scalar(
        db.select(func.count()).select_from(_mine().where(Notification.read_at.is_(None)).subquery())
    )
    return jsonify({"unread": count})


@inbox_bp.post("/notifications/<int:notification_id>/read")
@platform_guard
@require_permission("notifications", "read")
@rate_limit("RATE_LIMIT_WRITE")
def mark_read(notification_id: int):
    n = db.session.scalar(_mine().where(Notification.id == notification_id))
    if n is None:
        raise NotFoundError("Notificación no encontrada.")
    if n.read_at is None:
        n.read_at = utcnow()
        db.session.commit()
    return jsonify(notification_dict(n))


@inbox_bp.post("/notifications/read-all")
@platform_guard
@require_permission("notifications", "read")
@rate_limit("RATE_LIMIT_WRITE")
def mark_all_read():
    result = db.session.execute(
        db.update(Notification)
        .where(Notification.user_id == g.security.user_id, Notification.read_at.is_(None),
               Notification.is_active.is_(True))
        .values(read_at=utcnow())
    )
    db.session.commit()
    return jsonify({"updated": result.rowcount})


# ------------------------------------------------------------------ Alertas
def alert_dict(a: Alert) -> dict:
    return {"id": a.id, "alert_type": a.alert_type, "opportunity_id": a.opportunity_id,
            "score": a.score, "message": a.message, "resolved_at": iso(a.resolved_at),
            "created_at": iso(a.created_at)}


@inbox_bp.get("/alerts")
@platform_guard
@require_permission("alerts", "read")
@rate_limit("RATE_LIMIT_READ")
def list_alerts():
    stmt = Alert.select_active()
    if request.args.get("open") == "true":
        stmt = stmt.where(Alert.resolved_at.is_(None))
    if atype := request.args.get("alert_type"):
        stmt = stmt.where(Alert.alert_type == atype)
    return jsonify(paginate(stmt.order_by(Alert.created_at.desc(), Alert.id.desc()), alert_dict))


@inbox_bp.post("/alerts/<int:alert_id>/resolve")
@platform_guard
@require_permission("alerts", "write")
@rate_limit("RATE_LIMIT_WRITE")
def resolve_alert(alert_id: int):
    alert = get_active(Alert, alert_id, "Alerta")
    if alert.resolved_at is None:
        alert.resolved_at = utcnow()
        db.session.commit()
        record_audit(AuditAction.RECORD_UPDATED, alert, fields=["resolved_at"])
    return jsonify(alert_dict(alert))
