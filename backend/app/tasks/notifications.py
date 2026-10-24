"""Avisos por correo (cola ``default``, Capítulo 22).

Cada dos minutos envía por correo los avisos de prioridad alta o urgente que nadie ha
leído todavía. Es idempotente: ``emailed_at`` marca los enviados y solo se miran los
avisos recientes, así que activar el SMTP no manda de golpe el histórico.
"""
from datetime import timedelta

import structlog
from flask import current_app

from ..extensions import db
from ..models import Notification, User, utcnow
from ..queue import PlatformTask, celery
from ..services import email

log = structlog.get_logger(__name__)
BATCH = 50


def _render(n: Notification, user: User) -> tuple[str, str]:
    base = current_app.config.get("PUBLIC_BASE_URL", "")
    lines = [f"Hola, {user.full_name}:", "", n.title]
    if n.body:
        lines += ["", n.body]
    if n.link and base:
        lines += ["", f"Ábrelo en la plataforma: {base}{n.link if n.link.startswith('/') else '/' + n.link}"]
    lines += ["", "—", "Aviso automático de PLATIA. Puedes verlo también en el centro de avisos."]
    prefix = "[Urgente] " if n.priority == "urgent" else ""
    return f"{prefix}{n.title}", "\n".join(lines)


@celery.task(name="tasks.notifications.send_pending_emails", base=PlatformTask, bind=True)
def send_pending_emails(self) -> dict:
    if not email.enabled():
        return {"sent": 0, "reason": "SMTP sin configurar"}
    cfg = current_app.config
    since = utcnow() - timedelta(hours=cfg["EMAIL_MAX_AGE_HOURS"])
    pending = db.session.scalars(
        Notification.select_active().where(
            Notification.priority.in_(cfg["EMAIL_PRIORITIES"]),
            Notification.read_at.is_(None),
            Notification.emailed_at.is_(None),
            Notification.created_at >= since,
        ).order_by(Notification.id).limit(BATCH)
    ).all()
    if not pending:
        return {"sent": 0}
    users = {
        u.id: u
        for u in db.session.scalars(
            User.select_active().where(User.id.in_({n.user_id for n in pending}), User.status == "active")
        )
    }
    sent = skipped = 0
    for n in pending:
        user = users.get(n.user_id)
        if user is None:
            # Usuario dado de baja o bloqueado: se marca para no volver a mirarlo
            n.emailed_at = utcnow()
            skipped += 1
            continue
        subject, text = _render(n, user)
        try:
            email.send([email.build_message(user.email, subject, text)])
        except email.EmailError:
            db.session.commit()
            # Fallo del servidor de correo: se reintenta en la siguiente pasada
            return {"sent": sent, "skipped": skipped, "error": "smtp"}
        n.emailed_at = utcnow()
        db.session.commit()  # uno a uno: un fallo a mitad no reenvía los anteriores
        sent += 1
    db.session.commit()
    log.info("notification_emails", sent=sent, skipped=skipped)
    return {"sent": sent, "skipped": skipped}
