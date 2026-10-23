"""Escritura del registro de auditoría.

Usa una sesión propia: si la petición hace rollback (por ejemplo, un acceso
denegado), la entrada de auditoría se conserva igualmente.
"""
import structlog
from flask import g, has_request_context, request
from sqlalchemy.orm import Session

from ..extensions import db
from ..models import AuditLog

log = structlog.get_logger("audit")


def audit(
    action: str,
    severity: str = "INFO",
    user_id: int | None = None,
    details: dict | None = None,
    resource_type: str | None = None,
    resource_id: str | int | None = None,
) -> None:
    entry = AuditLog(
        action=action,
        severity=severity,
        user_id=user_id,
        details=details,
        resource_type=resource_type,
        resource_id=None if resource_id is None else str(resource_id),
    )
    if has_request_context():
        entry.ip_address = request.remote_addr
        entry.user_agent = (request.user_agent.string or "")[:500] or None
        entry.request_id = g.get("request_id")
    try:
        with Session(db.engines["core"]) as session:
            session.add(entry)
            session.commit()
    except Exception as exc:  # noqa: BLE001 - la auditoría nunca tumba la petición
        log.error("audit_write_failed", action=action, error=str(exc))
    log_fn = log.error if severity == "CRITICAL" else log.warning if severity == "WARNING" else log.info
    log_fn("audit", action=action, severity=severity, user_id=user_id, details=details)
