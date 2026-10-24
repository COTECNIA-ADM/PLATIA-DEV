"""Envío de correo por SMTP (Capítulo 22).

Configuración solo por variables de entorno (SMTP_*). Sin SMTP_HOST el servicio está
desactivado y nadie recibe correos: la plataforma funciona igual con los avisos internos.
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import structlog
from flask import current_app

log = structlog.get_logger(__name__)


class EmailError(RuntimeError):
    pass


def enabled() -> bool:
    cfg = current_app.config
    return bool(cfg.get("SMTP_HOST") and cfg.get("EMAIL_FROM"))


def _one_line(text: str) -> str:
    """Una cabecera nunca lleva saltos de línea (evita inyectar cabeceras)."""
    return " ".join(str(text).split())


def build_message(to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
    cfg = current_app.config
    msg = EmailMessage()
    msg["From"] = formataddr((_one_line(cfg["EMAIL_FROM_NAME"]), cfg["EMAIL_FROM"]))
    msg["To"] = _one_line(to)
    msg["Subject"] = _one_line(subject)[:200]
    msg["Message-ID"] = make_msgid(domain=cfg["EMAIL_FROM"].rsplit("@", 1)[-1])
    msg["Auto-Submitted"] = "auto-generated"  # que no respondan los autorrespondedores
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def send(messages: list[EmailMessage]) -> int:
    """Envía varios mensajes en una sola conexión. Devuelve cuántos se enviaron."""
    if not messages:
        return 0
    cfg = current_app.config
    context = ssl.create_default_context()
    try:
        if cfg["SMTP_SECURITY"] == "ssl":
            server = smtplib.SMTP_SSL(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=cfg["SMTP_TIMEOUT"], context=context)
        else:
            server = smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=cfg["SMTP_TIMEOUT"])
        with server:
            if cfg["SMTP_SECURITY"] == "starttls":
                server.starttls(context=context)
            if cfg["SMTP_USER"]:
                server.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            for msg in messages:
                server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("email_send_failed", error=type(exc).__name__, host=cfg["SMTP_HOST"])
        raise EmailError(f"No se ha podido enviar el correo: {type(exc).__name__}") from exc
    log.info("email_sent", count=len(messages))
    return len(messages)
