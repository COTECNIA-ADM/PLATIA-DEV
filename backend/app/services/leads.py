"""Solicitudes que llegan de fuera (caso P2 del portal Low-Code, ADR-020).

Un flujo de n8n recoge el formulario web, envía el acuse a quien escribe y entrega aquí la
solicitud con la clave de integración. Lo que llega de fuera nunca crea registros por sí
solo: la solicitud queda pendiente y avisa a quien gestiona solicitudes (``leads.read``).
Una persona con ``leads.manage`` decide si la convierte en contacto (de un cliente nuevo o
existente), en contacto más oportunidad, o la descarta.
"""
import structlog
from sqlalchemy import func

from ..api.common import iso
from ..errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from ..extensions import db
from ..models import Client, Contact, InboundLead, Opportunity, utcnow
from . import notifications
from . import opportunities as opportunities_service

log = structlog.get_logger(__name__)

OPPORTUNITY_SOURCE = "formulario_web"


def lead_dict(lead: InboundLead, full: bool = False) -> dict:
    data = {
        "id": lead.id, "source": lead.source, "status": lead.status, "resolution": lead.resolution,
        "full_name": lead.full_name, "email": lead.email, "company": lead.company, "subject": lead.subject,
        "created_at": iso(lead.created_at), "resolved_at": iso(lead.resolved_at), "version": lead.row_version,
    }
    if full:
        data |= {
            "phone": lead.phone, "tax_id": lead.tax_id, "message": lead.message, "ack_sent": lead.ack_sent,
            "workflow_id": lead.workflow_id, "client_id": lead.client_id, "contact_id": lead.contact_id,
            "opportunity_id": lead.opportunity_id, "resolved_by": lead.resolved_by,
            "resolution_note": lead.resolution_note, "matches": matches(lead) if lead.status == "new" else [],
        }
    return data


def matches(lead: InboundLead) -> list[dict]:
    """Clientes que podrían ser el de la solicitud: mismo NIF, mismo nombre o un contacto con
    el mismo correo. Solo como sugerencia; decide la persona."""
    stmt = db.select(Client).join(Contact, Contact.client_id == Client.id, isouter=True).where(
        Client.is_active.is_(True))
    ors = [func.lower(Contact.email) == lead.email.lower()]
    if lead.tax_id:
        ors.append(Client.tax_id == lead.tax_id)
    if lead.company:
        ors.append(func.lower(Client.name) == lead.company.lower())
    clients = db.session.scalars(stmt.where(db.or_(*ors)).distinct().limit(5)).all()
    return [{"id": c.id, "name": c.name, "tax_id": c.tax_id} for c in clients]


def receive(data: dict) -> tuple[InboundLead, bool]:
    """Guarda la solicitud. Si n8n la reenvía con la misma referencia, devuelve la que ya
    había (``False``) sin avisar otra vez."""
    data = {k: v for k, v in data.items() if k != "consent"}
    if data.get("external_ref"):
        existing = db.session.scalar(db.select(InboundLead).where(
            InboundLead.source == data["source"], InboundLead.external_ref == data["external_ref"]))
        if existing is not None:
            return existing, False
    lead = InboundLead(**data)
    db.session.add(lead)
    db.session.flush()
    who = lead.company or lead.full_name
    notifications.notify_many(
        notifications.holders_of("operations", "leads", "read"), "NEW_LEAD",
        f"Nueva solicitud desde el formulario web: {who}"[:255], lead.subject or None,
        link=f"/leads/{lead.id}", extra_data={"lead_id": lead.id},
    )
    log.info("lead_received", lead_id=lead.id, source=lead.source, ack_sent=lead.ack_sent)
    return lead, True


def resolve(lead: InboundLead, action: str, user_id: int, can, client_id: int | None = None,
            new_client_name: str | None = None, opportunity_title: str | None = None,
            note: str | None = None) -> None:
    """Convierte o descarta una solicitud pendiente. No hace commit.

    ``can(módulo, acción)`` son los permisos de quien decide: crear el contacto exige
    ``clients.write`` y la oportunidad, además, ``opportunities.write``.
    """
    if lead.status != "new":
        raise ConflictError("Esta solicitud ya está resuelta.")
    lead.resolved_by, lead.resolved_at, lead.resolution_note = user_id, utcnow(), note
    if action == "discard":
        lead.status = "discarded"
        return
    if not can("clients", "write"):
        raise ForbiddenError("Necesitas permiso para crear clientes y contactos.")
    if action == "opportunity" and not can("opportunities", "write"):
        raise ForbiddenError("Necesitas permiso para crear oportunidades.")
    client = _client_for(lead, client_id, new_client_name, user_id)
    contact = _contact_for(lead, client, user_id)
    lead.status, lead.resolution, lead.client_id, lead.contact_id = "converted", action, client.id, contact.id
    if action == "opportunity":
        opp = Opportunity(
            title=opportunity_title or lead.subject or f"Solicitud de {client.name}"[:500],
            client=client, source=OPPORTUNITY_SOURCE, description=lead.message, owner_user_id=user_id,
            created_by=user_id, extra_data={"lead_id": lead.id},
        )
        with db.session.no_autoflush:
            db.session.add(opp)
            opportunities_service.score_opportunity(opp)
            opportunities_service.record_status(opp, None, user_id, "Desde una solicitud del formulario web")
        db.session.flush()
        lead.opportunity_id = opp.id


def _client_for(lead: InboundLead, client_id: int | None, new_client_name: str | None, user_id: int) -> Client:
    if client_id:
        client = db.session.get(Client, client_id)
        if client is None or not client.is_active:
            raise NotFoundError("Cliente no encontrado.")
        return client
    name = new_client_name or lead.company
    if not name:
        raise BusinessRuleError("Indica el nombre del cliente nuevo o elige uno existente.")
    if lead.tax_id and db.session.scalar(db.select(Client.id).where(Client.tax_id == lead.tax_id)):
        raise ConflictError("Ya existe un cliente con ese NIF/CIF: elígelo en lugar de crear otro.")
    client = Client(name=name, tax_id=lead.tax_id, owner_user_id=user_id, created_by=user_id,
                    notes="Alta desde una solicitud del formulario web.")
    db.session.add(client)
    db.session.flush()
    return client


def _contact_for(lead: InboundLead, client: Client, user_id: int) -> Contact:
    """El contacto del cliente con el mismo correo, o uno nuevo."""
    existing = db.session.scalar(Contact.select_active().where(
        Contact.client_id == client.id, func.lower(Contact.email) == lead.email.lower()))
    if existing is not None:
        return existing
    has_primary = db.session.scalar(db.select(Contact.id).where(
        Contact.client_id == client.id, Contact.is_primary.is_(True), Contact.is_active.is_(True)).limit(1))
    contact = Contact(client_id=client.id, full_name=lead.full_name, email=lead.email, phone=lead.phone,
                      is_primary=not has_primary, created_by=user_id)
    db.session.add(contact)
    db.session.flush()
    return contact
