"""Acceso a objetos ajenos a través de rutas anidadas (fase 7a, OWASP API1: BOLA).

El patrón de ataque: tengo acceso al recurso padre A y uso el id de un hijo que
pertenece a B (``/proposals/{A}/sections/{sección de B}``). Debe dar 404, como si no
existiera, y no tocar nada. Los casos de clientes, oportunidades, conversaciones y
documentos restringidos y recuerdos del copiloto ya están en sus propios ficheros de tests.
"""
import io

from conftest import uid

from app.extensions import db
from app.models import Notification, ProposalSection


def _proposal(client, h, title):
    opp = client.post("/api/opportunities", json={"title": title}, headers=h).json
    template = client.get("/api/proposal-templates?proposal_type=base", headers=h).json["items"][0]
    resp = client.post("/api/proposals", json={"opportunity_id": opp["id"], "proposal_type": "base",
                                               "template_id": template["id"]}, headers=h)
    assert resp.status_code == 201, resp.json
    return resp.json


def test_section_of_another_proposal_through_mine_is_404(client, as_role):
    manager = as_role("manager")
    mine, theirs = _proposal(client, manager, "Mía"), _proposal(client, manager, "Ajena")
    foreign = theirs["sections"][0]
    url = f"/api/proposals/{mine['id']}/sections/{foreign['id']}"
    patched = client.patch(url, json={"version": foreign["version"], "edited_content": "Pisado"}, headers=manager)
    assert patched.status_code == 404
    assert client.delete(url, headers=manager).status_code == 404
    section = db.session.get(ProposalSection, foreign["id"])
    assert section.edited_content is None and section.is_active


def test_attachment_of_another_proposal_through_mine_is_404(client, as_role):
    manager = as_role("manager")
    mine, theirs = _proposal(client, manager, "Mía"), _proposal(client, manager, "Ajena")
    upload = client.post(f"/api/proposals/{theirs['id']}/attachments", headers=manager,
                         data={"file": (io.BytesIO(b"Anexo confidencial"), "anexo.txt"), "kind": "other"},
                         content_type="multipart/form-data")
    assert upload.status_code == 201, upload.json
    url = f"/api/proposals/{mine['id']}/attachments/{upload.json['id']}"
    assert client.get(url, headers=manager).status_code == 404
    assert client.delete(url, headers=manager).status_code == 404


def test_other_peoples_notifications_are_invisible(client, as_role):
    ana, luis = as_role("analyst", "ana@example.com"), as_role("analyst", "luis@example.com")
    note = Notification(user_id=uid(luis), notification_type="SYSTEM", priority="high", title="Solo para Luis")
    db.session.add(note)
    db.session.commit()
    assert client.post(f"/api/notifications/{note.id}/read", headers=ana).status_code == 404
    listed = client.get("/api/notifications", headers=ana).json["items"]
    assert note.id not in [n["id"] for n in listed]
    db.session.refresh(note)
    assert note.read_at is None

