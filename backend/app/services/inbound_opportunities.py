"""Oportunidades que entregan los flujos de n8n (casos P8 y P6 del portal Low-Code, ADR-020).

Un flujo de entrada (por ejemplo, el conector de TED) consulta una fuente de licitaciones y
entrega aquí los anuncios por lotes, con la clave de integración. PLATIA hace lo mismo que con
los feeds ATOM (``tasks.sync.scan_opportunities``): deduplica por fuente e identificador,
actualiza si el anuncio cambió sin tocar el estado de trabajo, y deja las nuevas como
``detected``. La relevancia y los avisos los pone después ``tasks.alerts.proactive_scan``.

Dos formatos:
- ``platia``: ítems ya normalizados (``id``, ``title``, ``description``, ``link``, ``entity``,
  ``cpv_codes``, ``estimated_value``, ``deadline``, ``published_at``).
- ``ted``: anuncios tal como los devuelve la búsqueda de la API v3 de TED. Se normalizan aquí,
  con tolerancia: un campo que no llega o llega con otra forma se deja vacío.
"""
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import func

from ..errors import BusinessRuleError, ConflictError, NotFoundError
from ..extensions import db
from ..models import Document, Opportunity, OpportunityDocument
from . import opportunities as opp_service
from . import storage

log = structlog.get_logger(__name__)

# Fuentes que pueden entregar flujos de n8n. Una nueva se añade aquí y en la documentación.
SOURCES = ("ted", "buzon_pliegos")
LANGS = ("spa", "eng", "fra", "por", "ita", "deu")
TED_NOTICE_URL = "https://ted.europa.eu/es/notice/{number}/html"
PUB_NUMBER = re.compile(r"^\d{1,8}-\d{4}$")
DATE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")


def _text(value) -> str | None:
    """Texto de un campo de TED: cadena, lista o mapa por idioma (``{"spa": [...]}``)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return next((t for t in (_text(v) for v in value) if t), None)
    if isinstance(value, dict):
        for lang in LANGS:
            if (found := _text(value.get(lang))) is not None:
                return found
        return next((t for t in (_text(v) for v in value.values()) if t), None)
    return None


def _list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _date(value, end_of_day: bool = False) -> datetime | None:
    """La primera fecha que se pueda leer (TED las da como ``2026-12-01+01:00`` o ``20261201``).
    Sin hora, un plazo vence al final del día y una publicación cuenta desde el principio."""
    for item in _list(value):
        match = DATE.search(str(item)) if item is not None else None
        if not match:
            continue
        y, m, d, hh, mm, ss, zone = match.groups()
        if hh is None:
            hh, mm, ss = ("23", "59", "59") if end_of_day else ("0", "0", "0")
        try:
            value = datetime(int(y), int(m), int(d), int(hh), int(mm or 0), int(ss or 0))
        except ValueError:
            continue
        if zone and zone != "Z":  # hora local del anuncio: se guarda en UTC
            sign = 1 if zone[0] == "+" else -1
            value -= sign * timedelta(hours=int(zone[1:3]), minutes=int(zone[-2:]))
        return value
    return None


def _earliest(value) -> datetime | None:
    dates = [d for d in (_date(v, end_of_day=True) for v in _list(value)) if d is not None]
    return min(dates) if dates else None


def _amount(values, currencies) -> Decimal | None:
    """Importe en euros: el mayor de los que vienen en EUR (o sin moneda)."""
    amounts = []
    currencies = [str(c).upper() for c in _list(currencies)]
    for i, value in enumerate(_list(values)):
        currency = currencies[i] if i < len(currencies) else (currencies[0] if currencies else "EUR")
        if currency != "EUR":
            continue
        try:
            amount = Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            continue
        if 0 <= amount < Decimal("1e12"):
            amounts.append(amount)
    return max(amounts) if amounts else None


def normalize_ted(notice: dict) -> dict | None:
    """Un anuncio de la API de TED a ítem común; ``None`` si no trae número de publicación."""
    number = _text(notice.get("publication-number"))
    if not number or not PUB_NUMBER.match(number):
        return None
    title = _text(notice.get("notice-title")) or _text(notice.get("title-proc")) or f"Anuncio TED {number}"
    entity = _text(notice.get("buyer-name")) or _text(notice.get("organisation-name-buyer"))
    cpv = []
    for code in _list(notice.get("classification-cpv")):
        code = str(code).strip()[:10]
        if code[:8].isdigit() and code not in cpv:
            cpv.append(code)
    value = None
    for level in ("proc", "glo", "lot"):
        value = _amount(notice.get(f"estimated-value-{level}"), notice.get(f"estimated-value-cur-{level}"))
        if value is not None:
            break
    deadline = _earliest(notice.get("deadline-receipt-tender-date-lot")) or _earliest(notice.get("deadline"))
    parts = [f"Anuncio {number} publicado en TED."]
    if entity:
        parts.append(f"Poder adjudicador: {entity}.")
    if description := _text(notice.get("description-proc")) or _text(notice.get("description-lot")):
        parts.append(description)
    return {
        "id": number,
        "title": title,
        "description": "\n\n".join(parts),
        "link": TED_NOTICE_URL.format(number=number),
        "entity": entity,
        "cpv_codes": cpv[:50] or None,
        "estimated_value": value,
        "deadline": deadline,
        "published_at": _date(notice.get("publication-date")),
    }


def normalize_platia(item: dict) -> dict:
    """Un ítem ya validado con ``InboundOpportunityItem``: fechas a UTC sin zona."""
    from ..api.common import to_utc_naive

    return {**item, **{k: to_utc_naive(item[k]) if item.get(k) else None for k in ("deadline", "published_at")}}


def receive(source: str, fmt: str, items: list[dict], workflow_id: str | None = None) -> dict:
    """Crea o actualiza las oportunidades. No hace commit. Devuelve los recuentos y los ids nuevos."""
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    created_ids = []
    seen = set()
    for raw in items:
        item = normalize_ted(raw) if fmt == "ted" else normalize_platia(raw)
        if item is None or item["id"] in seen:
            counts["skipped"] += 1
            continue
        seen.add(item["id"])
        opp, outcome = opp_service.upsert_from_feed(item, source)
        counts[outcome] += 1
        if outcome == "created":
            db.session.flush()
            opp.extra_data = {**(opp.extra_data or {}), "workflow_id": workflow_id} if workflow_id else opp.extra_data
            created_ids.append(opp.id)
    log.info("inbound_opportunities_received", source=source, format=fmt, workflow_id=workflow_id, **counts)
    return {**counts, "created_ids": created_ids}


# ------------------------------------------------------------------ Adjuntos (P6 buzón de pliegos)
# Fuentes que pueden traer ficheros: solo las que vienen de un buzón propio
ATTACH_SOURCES = ("buzon_pliegos",)
MAX_DOCUMENTS = 20


def attach(opp: Opportunity, source: str, upload, title: str | None = None) -> tuple[Document, bool]:
    """Guarda un adjunto del correo y lo vincula a la oportunidad. No hace commit.

    Solo para oportunidades que el propio flujo creó (misma fuente) y que nadie ha empezado a
    trabajar (``detected``): un flujo no puede añadir ficheros a cualquier oportunidad. El fichero
    pasa las mismas comprobaciones que una subida de persona (tipo, firma y tamaño).
    """
    if source not in ATTACH_SOURCES or opp.source != source or not opp.is_active:
        raise NotFoundError("Oportunidad no encontrada.")
    if opp.status != "detected":
        raise ConflictError("La oportunidad ya se está trabajando: añade los ficheros desde PLATIA.")
    links = db.session.scalar(db.select(func.count()).select_from(OpportunityDocument).where(
        OpportunityDocument.opportunity_id == opp.id, OpportunityDocument.is_active.is_(True)))
    if links >= MAX_DOCUMENTS:
        raise BusinessRuleError(f"La oportunidad ya tiene {MAX_DOCUMENTS} documentos.")
    stored = storage.save_upload(upload)
    document = db.session.scalar(db.select(Document).filter_by(file_hash=stored.sha256, is_active=True,
                                                               is_current_version=True))
    created = document is None
    if not created:
        storage.delete_file(stored.storage_path)
        if document.allowed_roles:  # restringido: no se enlaza desde fuera
            raise ConflictError("Este fichero ya está subido.")
    else:
        document = Document(
            title=(title or stored.original_filename)[:500], doc_type="pliego",
            original_filename=stored.original_filename, mime_type=stored.mime_type,
            storage_path=stored.storage_path, file_hash=stored.sha256, file_size_bytes=stored.size,
            processing_status="pending",
        )
        db.session.add(document)
        db.session.flush()
    link = db.session.scalar(db.select(OpportunityDocument).filter_by(opportunity_id=opp.id,
                                                                      document_id=document.id))
    if link is None:
        db.session.add(OpportunityDocument(opportunity_id=opp.id, document_id=document.id, role="requirements"))
    elif not link.is_active:
        link.restore()
    log.info("inbound_document_attached", opportunity_id=opp.id, document_id=document.id, created=created)
    return document, created
