"""Clientes, contactos y proyectos (Apéndice B, blueprint ``clients``)."""
from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from ..api.common import (apply_changes, check_version, get_active, iso, like_pattern, money,
                          paginate, parse_body, record_audit)
from ..api.schemas import ClientIn, ClientPatch, ContactIn, ContactPatch, ProjectIn, ProjectPatch
from ..errors import ConflictError, NotFoundError
from ..extensions import db
from ..models import AuditAction, Client, Contact, Opportunity, Project
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit

clients_bp = Blueprint("clients", __name__, url_prefix="/api/clients")


def client_summary(c: Client) -> dict:
    return {"id": c.id, "name": c.name, "sector": c.sector, "segment": c.segment,
            "risk_level": c.risk_level, "owner_user_id": c.owner_user_id, "version": c.row_version,
            "updated_at": iso(c.updated_at)}


def client_detail(c: Client) -> dict:
    open_opps = db.session.scalar(
        db.select(func.count()).select_from(Opportunity).where(
            Opportunity.client_id == c.id, Opportunity.is_active.is_(True),
            Opportunity.status.notin_(("won", "lost", "discarded")))
    )
    return {**client_summary(c), "tax_id": c.tax_id, "website": c.website, "notes": c.notes,
            "created_at": iso(c.created_at), "open_opportunities": open_opps,
            "contacts": [contact_dict(x) for x in c.contacts if x.is_active],
            "projects": [project_dict(p) for p in c.projects if p.is_active]}


def contact_dict(c: Contact) -> dict:
    return {"id": c.id, "client_id": c.client_id, "full_name": c.full_name, "email": c.email,
            "phone": c.phone, "position": c.position, "is_primary": c.is_primary,
            "version": c.row_version}


def project_dict(p: Project) -> dict:
    return {"id": p.id, "client_id": p.client_id, "name": p.name, "description": p.description,
            "status": p.status, "start_date": p.start_date.isoformat() if p.start_date else None,
            "end_date": p.end_date.isoformat() if p.end_date else None,
            "budget_eur": money(p.budget_eur), "version": p.row_version}


def _commit_unique(message: str) -> None:
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ConflictError(message) from exc


# ------------------------------------------------------------------ Clientes
@clients_bp.get("")
@platform_guard
@require_permission("clients", "read")
@rate_limit("RATE_LIMIT_READ")
def list_clients():
    stmt = Client.select_active().order_by(Client.name)
    if pattern := like_pattern(request.args.get("q")):
        stmt = stmt.where(or_(Client.name.like(pattern, escape="\\"),
                              Client.tax_id.like(pattern, escape="\\")))
    for field in ("sector", "segment", "risk_level"):
        if value := request.args.get(field):
            stmt = stmt.where(getattr(Client, field) == value)
    return jsonify(paginate(stmt, client_summary))


@clients_bp.post("")
@platform_guard
@require_permission("clients", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_client():
    data = parse_body(ClientIn)
    client = Client(**data.model_dump(), created_by=g.security.user_id)
    db.session.add(client)
    _commit_unique("Ya existe un cliente con ese NIF/CIF.")
    record_audit(AuditAction.RECORD_CREATED, client)
    return jsonify(client_detail(client)), 201


@clients_bp.get("/<int:client_id>")
@platform_guard
@require_permission("clients", "read")
@rate_limit("RATE_LIMIT_READ")
def get_client(client_id: int):
    return jsonify(client_detail(get_active(Client, client_id, "Cliente")))


@clients_bp.patch("/<int:client_id>")
@platform_guard
@require_permission("clients", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_client(client_id: int):
    client = get_active(Client, client_id, "Cliente")
    data = parse_body(ClientPatch)
    check_version(client, data.version)
    changed = apply_changes(client, data.model_dump(exclude_unset=True, exclude={"version"}),
                            required=("name",))
    _commit_unique("Ya existe un cliente con ese NIF/CIF.")
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, client, fields=changed)
    return jsonify(client_detail(client))


@clients_bp.delete("/<int:client_id>")
@platform_guard
@require_permission("clients", "delete")
@rate_limit("RATE_LIMIT_WRITE")
def delete_client(client_id: int):
    client = get_active(Client, client_id, "Cliente")
    open_opps = db.session.scalar(
        db.select(func.count()).select_from(Opportunity).where(
            Opportunity.client_id == client.id, Opportunity.is_active.is_(True),
            Opportunity.status.notin_(("won", "lost", "discarded")))
    )
    if open_opps:
        raise ConflictError("El cliente tiene oportunidades abiertas.", open_opportunities=open_opps)
    client.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, client)
    return "", 204


# ------------------------------------------------------------------ Contactos
def _child(model, client_id: int, child_id: int, label: str):
    obj = get_active(model, child_id, label)
    if obj.client_id != client_id:
        raise NotFoundError(f"{label} no encontrado.")
    return obj


@clients_bp.post("/<int:client_id>/contacts")
@platform_guard
@require_permission("clients", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_contact(client_id: int):
    client = get_active(Client, client_id, "Cliente")
    data = parse_body(ContactIn)
    contact = Contact(client_id=client.id, **data.model_dump(), created_by=g.security.user_id)
    db.session.add(contact)
    if contact.is_primary:
        _clear_primary(client, contact)
    db.session.commit()
    record_audit(AuditAction.RECORD_CREATED, contact)
    return jsonify(contact_dict(contact)), 201


def _clear_primary(client: Client, keep: Contact) -> None:
    for other in client.contacts:
        if other is not keep and other.is_primary:
            other.is_primary = False


@clients_bp.patch("/<int:client_id>/contacts/<int:contact_id>")
@platform_guard
@require_permission("clients", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_contact(client_id: int, contact_id: int):
    contact = _child(Contact, client_id, contact_id, "Contacto")
    data = parse_body(ContactPatch)
    check_version(contact, data.version)
    changed = apply_changes(contact, data.model_dump(exclude_unset=True, exclude={"version"}),
                            required=("full_name", "is_primary"))
    if contact.is_primary:
        _clear_primary(contact.client, contact)
    db.session.commit()
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, contact, fields=changed)
    return jsonify(contact_dict(contact))


@clients_bp.delete("/<int:client_id>/contacts/<int:contact_id>")
@platform_guard
@require_permission("clients", "write")
@rate_limit("RATE_LIMIT_WRITE")
def delete_contact(client_id: int, contact_id: int):
    contact = _child(Contact, client_id, contact_id, "Contacto")
    contact.soft_delete()
    contact.is_primary = False
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, contact)
    return "", 204


# ------------------------------------------------------------------ Proyectos
@clients_bp.post("/<int:client_id>/projects")
@platform_guard
@require_permission("clients", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_project(client_id: int):
    client = get_active(Client, client_id, "Cliente")
    data = parse_body(ProjectIn)
    project = Project(client_id=client.id, **data.model_dump(), created_by=g.security.user_id)
    db.session.add(project)
    db.session.commit()
    record_audit(AuditAction.RECORD_CREATED, project)
    return jsonify(project_dict(project)), 201


@clients_bp.patch("/<int:client_id>/projects/<int:project_id>")
@platform_guard
@require_permission("clients", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_project(client_id: int, project_id: int):
    project = _child(Project, client_id, project_id, "Proyecto")
    data = parse_body(ProjectPatch)
    check_version(project, data.version)
    changed = apply_changes(project, data.model_dump(exclude_unset=True, exclude={"version"}),
                            required=("name", "status"))
    db.session.commit()
    if changed:
        record_audit(AuditAction.RECORD_UPDATED, project, fields=changed)
    return jsonify(project_dict(project))


@clients_bp.delete("/<int:client_id>/projects/<int:project_id>")
@platform_guard
@require_permission("clients", "write")
@rate_limit("RATE_LIMIT_WRITE")
def delete_project(client_id: int, project_id: int):
    project = _child(Project, client_id, project_id, "Proyecto")
    project.soft_delete()
    db.session.commit()
    record_audit(AuditAction.RECORD_DELETED, project)
    return "", 204
