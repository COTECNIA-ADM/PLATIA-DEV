import io

from conftest import uid

from app.extensions import db
from app.models import Notification, ProposalAttachment


def _opportunity(client, h):
    return client.post("/api/opportunities", json={"title": "Plataforma de datos"}, headers=h).json


def _proposal(client, h, ptype="base", template=True, **extra):
    opp = _opportunity(client, h)
    body = {"opportunity_id": opp["id"], "proposal_type": ptype, **extra}
    if template:
        templates = client.get(f"/api/proposal-templates?proposal_type={ptype}", headers=h).json["items"]
        body["template_id"] = templates[0]["id"]
    resp = client.post("/api/proposals", json=body, headers=h)
    assert resp.status_code == 201, resp.json
    return resp.json


def _fill(client, h, proposal):
    section = proposal["sections"][0]
    resp = client.patch(f"/api/proposals/{proposal['id']}/sections/{section['id']}",
                        json={"version": section["version"], "edited_content": "Texto revisado."}, headers=h)
    assert resp.status_code == 200, resp.json
    return client.get(f"/api/proposals/{proposal['id']}", headers=h).json


def _status(client, h, proposal, status, **extra):
    return client.post(f"/api/proposals/{proposal['id']}/status",
                       json={"version": proposal["version"], "status": status, **extra}, headers=h)


def _review(client, h, proposal, kind="general", decision="approve", comment=None):
    body = {"kind": kind, "decision": decision}
    if comment:
        body["comment"] = comment
    return client.post(f"/api/proposals/{proposal['id']}/reviews", json=body, headers=h)


def test_sections_from_template_and_editing(client, as_role):
    h = as_role("analyst")
    p = _proposal(client, h, "competitive")
    keys = [s["key"] for s in p["sections"]]
    assert "diferenciales" in keys and p["version_number"] == 1 and p["owner_user_id"] == uid(h)
    p = _fill(client, h, p)
    assert p["sections"][0]["final_content"] == "Texto revisado."
    assert p["sections"][0]["ai_content"] is None  # lo de la IA y lo editado van por separado


def test_base_flow_with_send_permission_and_opportunity_sync(client, as_role):
    analyst, manager = as_role("analyst"), as_role("manager")
    p = _fill(client, analyst, _proposal(client, analyst, "base"))
    # Enviar exige permiso de envío e importe
    assert _status(client, analyst, p, "sent").status_code == 403
    assert _status(client, manager, p, "sent").status_code == 422
    p = client.patch(f"/api/proposals/{p['id']}", json={"version": p["version"],
                                                       "total_amount_eur": "45000.00"}, headers=analyst).json
    # El gestor puede enviarla directamente desde borrador (tipo base)
    resp = _status(client, manager, p, "sent")
    assert resp.status_code == 200 and resp.json["status"] == "sent"
    p = resp.json
    # Ya enviada no se edita
    sec = p["sections"][0]
    assert client.patch(f"/api/proposals/{p['id']}/sections/{sec['id']}",
                        json={"version": sec["version"], "edited_content": "x"}, headers=manager).status_code == 422
    assert _status(client, manager, p, "lost").status_code == 422  # perder exige motivo
    resp = _status(client, manager, p, "won")
    assert resp.json["status"] == "won"
    opp = client.get(f"/api/opportunities/{p['opportunity_id']}", headers=manager).json
    # La oportunidad estaba en "detected": no se fuerza una transición no permitida
    assert opp["status"] == "detected"


def test_competitive_needs_analysis_before_review(client, as_role):
    analyst, manager = as_role("analyst"), as_role("manager")
    p = _fill(client, analyst, _proposal(client, analyst, "competitive"))
    resp = _status(client, analyst, p, "in_review")
    assert resp.status_code == 422 and "competencia" in resp.json["error"]
    upload = client.post(f"/api/proposals/{p['id']}/attachments",
                         data={"file": (io.BytesIO(b"Competidor A: precio bajo"), "competencia.txt"),
                               "kind": "competitive_analysis"},
                         headers=analyst, content_type="multipart/form-data")
    assert upload.status_code == 201
    p = client.get(f"/api/proposals/{p['id']}", headers=analyst).json
    resp = _status(client, analyst, p, "in_review")
    assert resp.status_code == 200 and resp.json["review_round"] == 1
    # Aprobar a mano no vale: hay que revisar
    assert _status(client, analyst, resp.json, "approved").status_code == 422
    # El analista no tiene permiso de aprobación; el gestor sí
    assert _review(client, analyst, resp.json).status_code == 403
    resp = _review(client, manager, resp.json)
    assert resp.status_code == 201 and resp.json["status"] == "approved"


def test_premium_needs_technical_and_executive_and_four_eyes(client, as_role):
    owner = as_role("manager", "owner@example.com")
    tech, exec_ = as_role("manager", "tech@example.com"), as_role("manager", "exec@example.com")
    p = _fill(client, owner, _proposal(client, owner, "premium", total_amount_eur="250000.00"))
    p = _status(client, owner, p, "in_review").json
    assert p["required_reviews"] == ["executive", "technical"]
    assert _review(client, owner, p, "technical").status_code == 403  # cuatro ojos
    assert _review(client, tech, p, "area").status_code == 422
    resp = _review(client, tech, p, "technical")
    assert resp.json["status"] == "in_review" and resp.json["pending_reviews"] == ["executive"]
    assert _review(client, tech, p, "technical").status_code == 422  # repetida
    resp = _review(client, exec_, p, "executive")
    assert resp.json["status"] == "approved"
    # Al aprobarse se genera el paquete (DOCX, PDF y PPTX) y se avisa al responsable
    generated = db.session.scalars(db.select(ProposalAttachment).filter_by(proposal_id=p["id"], kind="generated")
                                   .order_by(ProposalAttachment.id)).all()
    assert [a.filename.rsplit(".", 1)[1] for a in generated] == ["docx", "pdf", "pptx"]
    note = db.session.scalar(db.select(Notification).filter_by(user_id=uid(owner),
                                                               notification_type="REPORT_READY"))
    assert note.link == f"/proposals/{p['id']}"
    download = client.get(f"/api/proposals/{p['id']}/attachments/{generated[0].id}", headers=owner)
    assert download.status_code == 200 and download.data[:2] == b"PK"


def test_reject_returns_to_draft_and_new_round(client, as_role):
    owner, reviewer = as_role("manager", "o@example.com"), as_role("manager", "r@example.com")
    p = _fill(client, owner, _proposal(client, owner, "custom"))
    p = _status(client, owner, p, "in_review").json
    assert _review(client, reviewer, p, "area", "reject").status_code == 422  # falta el motivo
    resp = _review(client, reviewer, p, "area", "reject", "Falta el plan de calidad")
    assert resp.json["status"] == "draft"
    p = _status(client, owner, resp.json, "in_review").json
    assert p["review_round"] == 2 and p["reviews"] == []
    assert _review(client, reviewer, p, "area").json["status"] == "approved"


def test_empty_proposal_cannot_go_to_review(client, as_role):
    h = as_role("manager")
    p = _proposal(client, h, "base", template=False)
    assert [s["key"] for s in p["sections"]][0] == "resumen_ejecutivo"
    assert _status(client, h, p, "in_review").status_code == 422


def test_other_analyst_cannot_edit(client, as_role):
    owner, other = as_role("analyst", "a@example.com"), as_role("analyst", "b@example.com")
    p = _proposal(client, owner)
    sec = p["sections"][0]
    resp = client.patch(f"/api/proposals/{p['id']}/sections/{sec['id']}",
                        json={"version": sec["version"], "edited_content": "intruso"}, headers=other)
    assert resp.status_code == 403


def test_template_validation(client, as_role):
    h = as_role("manager")
    bad = {"name": "X", "proposal_type": "base",
           "sections": [{"key": "a", "title": "A", "order": 1}, {"key": "a", "title": "B", "order": 2}]}
    assert client.post("/api/proposal-templates", json=bad, headers=h).status_code == 422
    bad["sections"][1] = {"key": "b", "title": "B", "order": 2, "script": "<x>"}
    assert client.post("/api/proposal-templates", json=bad, headers=h).status_code == 422
    bad["sections"][1].pop("script")
    assert client.post("/api/proposal-templates", json=bad, headers=h).status_code == 201


def test_proposal_moves_the_opportunity_along_the_funnel(client, as_role):
    h, reviewer = as_role("manager"), as_role("manager", "rev@example.com")
    opp = _opportunity(client, h)
    for status in ("qualifying", "qualified", "go_no_go", "preparing_proposal"):
        opp = client.post(f"/api/opportunities/{opp['id']}/status",
                          json={"version": opp["version"], "status": status}, headers=h).json
    p = client.post("/api/proposals", json={"opportunity_id": opp["id"], "total_amount_eur": "1000"},
                    headers=h).json
    p = _fill(client, h, p)
    p = _status(client, h, p, "in_review").json
    assert client.get(f"/api/opportunities/{opp['id']}", headers=h).json["status"] == "proposal_review"
    p = _review(client, reviewer, p).json
    p = _status(client, h, p, "sent").json
    assert client.get(f"/api/opportunities/{opp['id']}", headers=h).json["status"] == "proposal_sent"
    _status(client, h, p, "won")
    final = client.get(f"/api/opportunities/{opp['id']}", headers=h).json
    assert final["status"] == "won" and final["phase"] == "F5" and final["probability"] == 100
