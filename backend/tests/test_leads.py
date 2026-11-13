"""Solicitudes del formulario web (caso P2 del portal Low-Code, ADR-020).

n8n entrega la solicitud con la clave de integración; PLATIA solo la guarda y avisa. Una
persona de comercial decide si la convierte en contacto, en oportunidad o la descarta.
"""
import pytest

from app.extensions import db
from app.models import Client, Contact, InboundLead, Notification, Opportunity

KEY = {"X-Platia-Integration-Key": "test-callback-key"}
LEAD = {"source": "formulario_web", "external_ref": "exec-1", "workflow_id": "platiaSolWeb01",
        "full_name": "Lucía Pérez", "email": "lucia@cliente.example", "phone": "600000000",
        "company": "Construcciones Ejemplo", "tax_id": "B00000000", "subject": "Mantenimiento de edificios",
        "message": "Queremos una oferta para tres edificios.", "consent": True, "ack_sent": True}


def send(client, body=None, headers=KEY):
    return client.post("/api/leads/inbound", json=LEAD if body is None else body, headers=headers)


@pytest.fixture()
def manager(as_role):
    return as_role("manager")


def test_inbound_needs_the_integration_key(client):
    assert send(client, headers={}).status_code == 401
    assert send(client, headers={"X-Platia-Integration-Key": "otra"}).status_code == 401
    assert db.session.scalar(db.select(db.func.count()).select_from(InboundLead)) == 0


def test_inbound_requires_consent_and_rejects_unknown_fields(client):
    assert send(client, {**LEAD, "consent": False}).status_code == 422
    assert send(client, {k: v for k, v in LEAD.items() if k != "consent"}).status_code == 422
    assert send(client, {**LEAD, "owner_user_id": 1}).status_code == 422
    assert send(client, {**LEAD, "email": "no-es-un-correo"}).status_code == 422
    assert send(client, {**LEAD, "message": "x" * 5001}).status_code == 422


def test_inbound_stores_notifies_and_creates_nothing_else(client, manager, as_role):
    viewer = as_role("viewer")
    resp = send(client)
    assert resp.status_code == 201, resp.json
    lead = db.session.get(InboundLead, resp.json["id"])
    assert lead.status == "new" and lead.created_by is None and lead.ack_sent
    # Solo quien gestiona solicitudes recibe el aviso
    notes = db.session.scalars(db.select(Notification).where(Notification.notification_type == "NEW_LEAD")).all()
    assert [n.user_id for n in notes] == [int(manager["X-User-Id"])]
    assert notes[0].link == f"/leads/{lead.id}" and "Construcciones Ejemplo" in notes[0].title
    assert int(viewer["X-User-Id"]) not in [n.user_id for n in notes]
    # Lo de fuera nunca crea registros
    for model in (Client, Contact, Opportunity):
        assert db.session.scalar(db.select(db.func.count()).select_from(model)) == 0


def test_inbound_is_idempotent_by_reference(client, manager):
    first = send(client)
    again = send(client)
    assert again.status_code == 200 and again.json == {"id": first.json["id"], "status": "new", "duplicate": True}
    assert db.session.scalar(db.select(db.func.count()).select_from(InboundLead)) == 1
    assert db.session.scalar(db.select(db.func.count()).select_from(Notification)) == 1
    # Sin referencia, cada envío es una solicitud
    body = {k: v for k, v in LEAD.items() if k != "external_ref"}
    assert send(client, body).status_code == 201 and send(client, body).status_code == 201


def test_list_and_detail_need_leads_permission(client, manager, as_role):
    lead_id = send(client).json["id"]
    for role in ("viewer", "analyst"):
        headers = as_role(role)
        assert client.get("/api/leads", headers=headers).status_code == 403
        assert client.get(f"/api/leads/{lead_id}", headers=headers).status_code == 403
    page = client.get("/api/leads?status=new", headers=manager).json
    assert page["pagination"]["total"] == 1 and page["items"][0]["full_name"] == "Lucía Pérez"
    assert "message" not in page["items"][0]
    detail = client.get(f"/api/leads/{lead_id}", headers=manager).json
    assert detail["message"].startswith("Queremos") and detail["matches"] == []
    assert client.get("/api/leads?status=converted", headers=manager).json["items"] == []


def _resolve(client, headers, lead_id, **body):
    version = client.get(f"/api/leads/{lead_id}", headers=headers).json["version"]
    return client.post(f"/api/leads/{lead_id}/resolve", json={"version": version, **body}, headers=headers)


def test_convert_to_contact_of_a_new_client(client, manager):
    lead_id = send(client).json["id"]
    resp = _resolve(client, manager, lead_id, action="contact")
    assert resp.status_code == 200, resp.json
    assert resp.json["status"] == "converted" and resp.json["resolution"] == "contact"
    new_client = db.session.get(Client, resp.json["client_id"])
    contact = db.session.get(Contact, resp.json["contact_id"])
    assert new_client.name == "Construcciones Ejemplo" and new_client.tax_id == "B00000000"
    assert contact.email == "lucia@cliente.example" and contact.is_primary
    assert db.session.scalar(db.select(db.func.count()).select_from(Opportunity)) == 0
    # Una sola vez
    assert _resolve(client, manager, lead_id, action="discard").status_code == 409


def test_convert_to_opportunity_of_an_existing_client(client, manager):
    existing = Client(name="Cliente de siempre", tax_id="B00000000", created_by=1)
    db.session.add(existing)
    db.session.flush()
    db.session.add(Contact(client_id=existing.id, full_name="Lucía", email="LUCIA@cliente.example",
                           is_primary=True, created_by=1))
    db.session.commit()
    lead_id = send(client).json["id"]
    detail = client.get(f"/api/leads/{lead_id}", headers=manager).json
    assert [m["id"] for m in detail["matches"]] == [existing.id]
    # Con el mismo NIF no se crea otro cliente
    assert _resolve(client, manager, lead_id, action="contact").status_code == 409
    resp = _resolve(client, manager, lead_id, action="opportunity", client_id=existing.id,
                    opportunity_title="Mantenimiento de tres edificios")
    assert resp.status_code == 200, resp.json
    opp = db.session.get(Opportunity, resp.json["opportunity_id"])
    assert opp.client_id == existing.id and opp.source == "formulario_web" and opp.status == "detected"
    assert opp.owner_user_id == int(manager["X-User-Id"]) and opp.title == "Mantenimiento de tres edificios"
    # Reutiliza el contacto con el mismo correo
    assert db.session.scalar(db.select(db.func.count()).select_from(Contact)) == 1


def test_discard_and_validation(client, manager):
    lead_id = send(client).json["id"]
    assert _resolve(client, manager, lead_id, action="discard", client_id=1).status_code == 422
    assert _resolve(client, manager, lead_id, action="contact", client_id=1,
                    new_client_name="Otro").status_code == 422
    assert _resolve(client, manager, lead_id, action="contact", client_id=999).status_code == 404
    resp = _resolve(client, manager, lead_id, action="discard", note="Spam")
    assert resp.status_code == 200 and resp.json["status"] == "discarded"
    assert resp.json["resolution_note"] == "Spam" and resp.json["resolved_by"] == int(manager["X-User-Id"])
    assert client.post(f"/api/leads/{lead_id}/resolve", json={"version": 1, "action": "discard"},
                       headers=manager).status_code == 409


def test_new_client_needs_a_name(client, manager):
    lead_id = send(client, {**LEAD, "company": None, "tax_id": None}).json["id"]
    assert _resolve(client, manager, lead_id, action="contact").status_code == 422
    resp = _resolve(client, manager, lead_id, action="contact", new_client_name="Lucía Pérez (particular)")
    assert resp.status_code == 200


def test_converting_needs_client_and_opportunity_permissions(client, make_user, login):
    """Un rol con ``leads.manage`` pero sin permiso de escritura solo puede descartar."""
    from app.models import App, AppRole

    app_row = db.session.scalar(db.select(App).filter_by(code="operations"))
    db.session.add(AppRole(app_id=app_row.id, code="recepcion", name="Recepción",
                           permissions={"leads": ["read", "manage"], "clients": ["read", "write"]}))
    db.session.commit()
    make_user(email="recepcion@example.com", roles={"operations": "recepcion"})
    headers = login("recepcion@example.com")
    lead_id = send(client).json["id"]
    assert _resolve(client, headers, lead_id, action="opportunity").status_code == 403
    assert db.session.get(InboundLead, lead_id).status == "new"
    assert _resolve(client, headers, lead_id, action="contact").status_code == 200


def test_existing_manager_roles_get_the_leads_module(seeded):
    """Los roles de serie que ya existían reciben ``leads`` al volver a sembrar."""
    from app.models import App, AppRole
    from app.seeds import run_seeds

    app_row = db.session.scalar(db.select(App).filter_by(code="operations"))
    role = db.session.scalar(db.select(AppRole).filter_by(app_id=app_row.id, code="manager"))
    role.permissions = {k: v for k, v in role.permissions.items() if k != "leads"}
    db.session.commit()
    run_seeds()
    assert db.session.get(AppRole, role.id).permissions["leads"] == ["read", "manage"]
