"""Avisos por correo: servidor SMTP falso, sin red."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import Notification, utcnow
from app.services import email
from app.tasks import notifications as tasks


class FakeSMTP:
    sent: list = []
    fail = False

    def __init__(self, host, port, timeout=None, **kwargs):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise email.smtplib.SMTPServerDisconnected("caído")
        FakeSMTP.sent.append(msg)


@pytest.fixture()
def smtp(seeded, monkeypatch):
    FakeSMTP.sent = []
    FakeSMTP.fail = False
    monkeypatch.setattr(email.smtplib, "SMTP", FakeSMTP)
    seeded.config.update(SMTP_HOST="smtp.example.com", EMAIL_FROM="avisos@example.com",
                         PUBLIC_BASE_URL="https://platia.example.com")
    return FakeSMTP


def _notif(user_id, priority="high", **kw):
    n = Notification(user_id=user_id, notification_type="SYSTEM", priority=priority,
                     title=kw.pop("title", "Oportunidad urgente"), body="Detalle", link="/opportunities/1", **kw)
    db.session.add(n)
    db.session.commit()
    return n


def test_disabled_without_smtp(seeded, make_user):
    user = make_user()
    _notif(user.id)
    assert tasks.send_pending_emails.apply().get() == {"sent": 0, "reason": "SMTP sin configurar"}


def test_sends_only_high_unread_recent_once(smtp, make_user):
    user = make_user()
    high = _notif(user.id)
    _notif(user.id, priority="normal")
    _notif(user.id, read_at=utcnow())
    old = _notif(user.id)
    old.created_at = utcnow() - timedelta(days=3)
    db.session.commit()

    assert tasks.send_pending_emails.apply().get()["sent"] == 1
    msg = smtp.sent[0]
    assert msg["To"] == user.email
    assert msg["Subject"] == "Oportunidad urgente"
    assert "https://platia.example.com/opportunities/1" in msg.get_content()
    db.session.refresh(high)
    assert high.emailed_at is not None
    # Idempotente: la segunda pasada no reenvía
    assert tasks.send_pending_emails.apply().get()["sent"] == 0
    assert len(smtp.sent) == 1


def test_subject_cannot_inject_headers(smtp, make_user):
    user = make_user()
    _notif(user.id, priority="urgent", title="Hola\r\nBcc: otro@example.com")
    tasks.send_pending_emails.apply().get()
    msg = smtp.sent[0]
    assert msg["Bcc"] is None
    assert msg["Subject"] == "[Urgente] Hola Bcc: otro@example.com"


def test_inactive_user_is_skipped(smtp, make_user):
    user = make_user()
    user.status = "locked"
    db.session.commit()
    n = _notif(user.id)
    assert tasks.send_pending_emails.apply().get() == {"sent": 0, "skipped": 1}
    db.session.refresh(n)
    assert n.emailed_at is not None and smtp.sent == []


def test_smtp_failure_retries_later(smtp, make_user):
    user = make_user()
    n = _notif(user.id)
    smtp.fail = True
    assert tasks.send_pending_emails.apply().get()["error"] == "smtp"
    db.session.refresh(n)
    assert n.emailed_at is None
    smtp.fail = False
    assert tasks.send_pending_emails.apply().get()["sent"] == 1
