"""Sincronización y mantenimiento (cola ``sync``): feeds, RGPD y limpieza."""
from datetime import timedelta

import requests
import structlog
from defusedxml import ElementTree
from flask import current_app

from ..extensions import db
from ..models import AuditLog, Notification, UserSession, utcnow
from ..queue import PlatformTask, TaskAlreadyRunning, TransientError, celery, task_lock
from ..services import opportunities as opp_service

log = structlog.get_logger(__name__)
ATOM = "{http://www.w3.org/2005/Atom}"


def configured_feeds() -> list[tuple[str, str]]:
    """OPPORTUNITY_FEEDS="nombre|https://...,otro|https://..." """
    feeds = []
    for item in (current_app.config.get("OPPORTUNITY_FEEDS") or "").split(","):
        name, _, url = item.strip().partition("|")
        if name and url.startswith("https://"):
            feeds.append((name.strip()[:50], url.strip()))
    return feeds


def _local(element, name: str) -> list:
    """Elementos descendientes con ese nombre local, sea cual sea su espacio de nombres."""
    return [e for e in element.iter() if isinstance(e.tag, str) and e.tag.rsplit("}", 1)[-1] == name]


def _first_text(element, *names: str) -> str | None:
    for name in names:
        for found in _local(element, name):
            if found.text and found.text.strip():
                return found.text.strip()
    return None


def _amount(text: str | None):
    from decimal import Decimal, InvalidOperation

    try:
        return Decimal(text).quantize(Decimal("0.01")) if text else None
    except InvalidOperation:
        return None


def _codice_fields(entry) -> dict:
    """Campos de la extensión CODICE que usa la Plataforma de Contratación del Sector
    Público (PLACSP) dentro de cada entrada ATOM: CPV, importe, órgano y plazo."""
    end_date = _first_text(entry, "EndDate")
    end_time = _first_text(entry, "EndTime") or "23:59:59"
    return {
        "cpv_codes": [e.text.strip() for e in _local(entry, "ItemClassificationCode")
                      if e.text and e.text.strip()[:2].isdigit()][:50] or None,
        "estimated_value": _amount(_first_text(entry, "EstimatedOverallContractAmount",
                                                "TaxExclusiveAmount", "TotalAmount")),
        "entity": next((_first_text(p, "Name") for p in _local(entry, "LocatedContractingParty")), None),
        "deadline": opp_service.parse_datetime(f"{end_date}T{end_time[:8]}") if end_date else None,
    }


def parse_atom(xml_bytes: bytes) -> list[dict]:
    """Normaliza un feed ATOM a ítems comunes. defusedxml bloquea entidades
    externas y bombas XML (XXE). Entiende las entradas ATOM genéricas y, además,
    la extensión CODICE de los feeds de licitaciones públicas españolas."""
    root = ElementTree.fromstring(xml_bytes)
    items = []
    for entry in root.iter(f"{ATOM}entry"):
        entry_id = (entry.findtext(f"{ATOM}id") or "").strip()
        if not entry_id:
            continue
        link = entry.find(f"{ATOM}link")
        summary = entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content") or ""
        cpv = [c.get("term") for c in entry.findall(f"{ATOM}category") if c.get("term")]
        codice = _codice_fields(entry)
        items.append({
            **{k: v for k, v in codice.items() if v},
            "id": entry_id,
            "title": (entry.findtext(f"{ATOM}title") or "").strip(),
            "description": summary.strip(),
            "link": link.get("href") if link is not None else None,
            "published_at": opp_service.parse_datetime(entry.findtext(f"{ATOM}updated")
                                                       or entry.findtext(f"{ATOM}published")),
            "entity": codice["entity"] or (entry.findtext(f"{ATOM}author/{ATOM}name") or "").strip() or None,
            "cpv_codes": [c for c in cpv if c[:2].isdigit()][:50] or codice["cpv_codes"],
        })
    return items


def fetch_feed(url: str) -> bytes:
    max_bytes = current_app.config["FEED_MAX_MB"] * 1024 * 1024
    try:
        with requests.get(url, timeout=30, stream=True,
                          headers={"User-Agent": "PLATIA/1.0 (+opportunity-scanner)"}) as resp:
            if resp.status_code >= 500 or resp.status_code == 429:
                raise TransientError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            data = b""
            for chunk in resp.iter_content(1024 * 256):
                data += chunk
                if len(data) > max_bytes:
                    raise ValueError("El feed supera el tamaño máximo.")
            return data
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise TransientError(str(exc)) from exc


def ingest_feed(name: str, xml_bytes: bytes) -> dict:
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    for item in parse_atom(xml_bytes):
        _, outcome = opp_service.upsert_from_feed(item, name)
        counts[outcome] += 1
    db.session.commit()
    return counts


@celery.task(name="tasks.sync.scan_opportunities", base=PlatformTask, bind=True, max_retries=3)
def scan_opportunities(self) -> dict:
    feeds = configured_feeds()
    if not feeds:
        return {"feeds": 0, "reason": "OPPORTUNITY_FEEDS vacío"}
    results = {}
    try:
        with task_lock("scan_opportunities", expire=3600):
            for name, url in feeds:
                try:
                    results[name] = ingest_feed(name, fetch_feed(url))
                except TransientError:
                    raise
                except Exception as exc:  # noqa: BLE001 - un feed roto no para los demás
                    db.session.rollback()
                    log.warning("feed_failed", feed=name, error=str(exc))
                    results[name] = {"error": type(exc).__name__}
    except TaskAlreadyRunning:
        return {"status": "already_running"}
    except TransientError as exc:
        raise self.retry_later(exc) from exc
    log.info("feeds_scanned", results=results)
    return results


@celery.task(name="tasks.sync.gdpr_cleanup", base=PlatformTask)
def gdpr_cleanup() -> dict:
    """Borra las notificaciones leídas más antiguas que el periodo de retención."""
    cutoff = utcnow() - timedelta(days=current_app.config["NOTIFICATION_RETENTION_DAYS"])
    result = db.session.execute(db.delete(Notification).where(Notification.read_at.is_not(None),
                                                              Notification.read_at < cutoff))
    db.session.commit()
    return {"notifications_deleted": result.rowcount}


@celery.task(name="tasks.sync.anonymize_audit_logs", base=PlatformTask)
def anonymize_audit_logs() -> dict:
    """RGPD: la auditoría se conserva, pero sin IP ni navegador pasado un año."""
    cutoff = utcnow() - timedelta(days=current_app.config["AUDIT_ANONYMIZE_DAYS"])
    result = db.session.execute(
        db.update(AuditLog)
        .where(AuditLog.created_at < cutoff,
               (AuditLog.ip_address.is_not(None)) | (AuditLog.user_agent.is_not(None)))
        .values(ip_address=None, user_agent=None)
    )
    db.session.commit()
    return {"anonymized": result.rowcount}


@celery.task(name="tasks.sync.cleanup_sessions", base=PlatformTask)
def cleanup_sessions() -> dict:
    """Borra las sesiones caducadas o revocadas hace más de N días."""
    cutoff = utcnow() - timedelta(days=current_app.config["SESSION_RETENTION_DAYS"])
    result = db.session.execute(
        db.delete(UserSession).where(UserSession.expires_at < cutoff)
    )
    db.session.commit()
    return {"sessions_deleted": result.rowcount}
