"""Notificaciones tipadas con enlace profundo y deduplicación (Capítulo 9).

Si el usuario ya tiene una notificación sin leer del mismo tipo y sobre el mismo
recurso (mismo enlace), no se crea otra: una tarea programada que se repite cada
hora no llena la bandeja de avisos iguales.
"""
import structlog

from ..extensions import db
from ..models import App, AppRole, Notification, User, UserAppMembership

log = structlog.get_logger(__name__)

DEFAULT_PRIORITY = {
    "NEW_OPPORTUNITY": "high",
    "OPPORTUNITY_MATCH": "high",
    "DEAL_STALLED": "normal",
    "ACCOUNT_RISK": "high",
    "REPORT_READY": "normal",
    "SYSTEM": "low",
}


def notify(user_id: int, notification_type: str, title: str, body: str | None = None,
           link: str | None = None, priority: str | None = None, extra_data: dict | None = None,
           commit: bool = True) -> Notification | None:
    if notification_type not in Notification.TYPES:
        raise ValueError(f"Tipo de notificación desconocido: {notification_type}")
    duplicate = db.session.scalar(
        db.select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.notification_type == notification_type,
            Notification.link == link if link is not None else Notification.link.is_(None),
            Notification.read_at.is_(None),
            Notification.is_active.is_(True),
        ).limit(1)
    )
    if duplicate:
        return None
    notification = Notification(
        user_id=user_id,
        notification_type=notification_type,
        priority=priority or DEFAULT_PRIORITY.get(notification_type, "normal"),
        title=title[:255],
        body=body,
        link=link,
        extra_data=extra_data,
    )
    db.session.add(notification)
    if commit:
        db.session.commit()
    log.info("notification_created", user_id=user_id, type=notification_type, link=link)
    return notification


def notify_many(user_ids, *args, **kwargs) -> int:
    created = 0
    for uid in sorted(set(user_ids)):
        if notify(uid, *args, commit=False, **kwargs):
            created += 1
    db.session.commit()
    return created


def operations_managers() -> list[int]:
    """Usuarios activos con rol admin o manager en operaciones, más los superadmin."""
    managers = db.session.scalars(
        db.select(UserAppMembership.user_id)
        .join(App, App.id == UserAppMembership.app_id)
        .join(AppRole, AppRole.id == UserAppMembership.role_id)
        .join(User, User.id == UserAppMembership.user_id)
        .where(App.code == "operations", AppRole.code.in_(("admin", "manager")),
               UserAppMembership.is_active.is_(True), User.is_active.is_(True))
    ).all()
    return sorted(set(managers) | set(superadmins()))


def superadmins() -> list[int]:
    return list(db.session.scalars(
        db.select(User.id).where(User.is_superadmin.is_(True), User.is_active.is_(True))
    ))
