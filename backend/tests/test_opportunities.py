from conftest import uid

from app.extensions import db
from app.models import AuditLog


def _create(client, h, **extra):
    body = {"title": "Desarrollo de portal web y aplicación móvil", "estimated_value_eur": "120000.00",
            "cpv_codes": ["72200000-7"], **extra}
    resp = client.post("/api/opportunities", json=body, headers=h)
    assert resp.status_code == 201, resp.json
    return resp.json


def test_create_scores_against_portfolio(client, as_role):
    h = as_role("analyst")
    opp = _create(client, h, description="Desarrollo de software a medida para el portal.")
    assert opp["status"] == "detected" and opp["phase"] == "F1"
    assert opp["owner_user_id"] == uid(h)
    assert opp["service_line"] == "applications"
    breakdown = opp["score_breakdown"]
    assert breakdown["taxonomy"] == 1.0 and breakdown["text"] > 0
    assert opp["relevance_score"] == breakdown["score"]


def test_status_machine(client, as_role):
    h = as_role("analyst")
    opp = _create(client, h)
    url = f"/api/opportunities/{opp['id']}/status"
    resp = client.post(url, json={"version": opp["version"], "status": "won"}, headers=h)
    assert resp.status_code == 422 and "qualifying" in resp.json["details"]["allowed"]

    resp = client.post(url, json={"version": opp["version"], "status": "qualifying"}, headers=h)
    assert resp.status_code == 200 and resp.json["allowed_transitions"] == ["discarded", "qualified"]
    version = resp.json["version"]

    resp = client.post(url, json={"version": version, "status": "discarded"}, headers=h)
    assert resp.status_code == 422  # descartar exige motivo
    resp = client.post(url, json={"version": version, "status": "discarded", "comment": "Fuera de plazo"},
                       headers=h)
    assert resp.json["status"] == "discarded" and resp.json["probability"] == 0
    log = db.session.scalar(db.select(AuditLog).filter_by(action="OPPORTUNITY_STATUS_CHANGED")
                            .order_by(AuditLog.id.desc()))
    assert log.details["from"] == "qualifying" and log.details["to"] == "discarded"


def test_analyst_cannot_modify_someone_elses_opportunity(client, as_role):
    """Autorización por objeto (IDOR): permiso de escritura no basta."""
    owner = as_role("analyst", "ana@example.com")
    other = as_role("analyst", "luis@example.com")
    manager = as_role("manager")
    opp = _create(client, owner)
    url = f"/api/opportunities/{opp['id']}"
    assert client.patch(url, json={"version": 1, "title": "Mío"}, headers=other).status_code == 403
    assert client.post(f"{url}/status", json={"version": 1, "status": "qualifying"},
                       headers=other).status_code == 403
    denied = db.session.scalar(db.select(AuditLog).filter_by(action="ACCESS_DENIED")
                               .order_by(AuditLog.id.desc()))
    assert denied.details["reason"] == "not_owner"
    # Reasignar es cosa del gestor
    assert client.patch(url, json={"version": 1, "owner_user_id": uid(other)},
                        headers=owner).status_code == 403
    resp = client.patch(url, json={"version": 1, "owner_user_id": uid(other)}, headers=manager)
    assert resp.status_code == 200
    assert client.patch(url, json={"version": 2, "title": "Ahora sí"}, headers=other).status_code == 200


def test_filters_pagination_and_phase(client, as_role):
    h = as_role("manager")
    for i in range(3):
        _create(client, h, title=f"Oportunidad {i}", code=f"OP-{i}")
    body = client.get("/api/opportunities?per_page=2&sort=-created", headers=h).json
    assert body["pagination"]["total"] == 3 and len(body["items"]) == 2
    assert client.get("/api/opportunities?phase=F1", headers=h).json["pagination"]["total"] == 3
    assert client.get("/api/opportunities?phase=F5", headers=h).json["pagination"]["total"] == 0
    assert client.get("/api/opportunities?q=OP-1", headers=h).json["pagination"]["total"] == 1
    assert client.get("/api/opportunities?owner=me", headers=h).json["pagination"]["total"] == 3
    assert client.get("/api/opportunities?sort=hack", headers=h).status_code == 422
    assert client.post("/api/opportunities", json={"title": "Dup", "code": "OP-1"},
                       headers=h).status_code == 409


def test_export_csv_is_streamed_and_formula_safe(client, as_role):
    h = as_role("manager")
    _create(client, h, title="=HYPERLINK(\"http://malo\")")
    resp = client.get("/api/opportunities/export", headers=h)
    assert resp.status_code == 200 and resp.mimetype == "text/csv"
    text = resp.get_data(as_text=True)
    assert text.startswith("﻿id;code;title")
    assert "'=HYPERLINK" in text
    assert db.session.scalar(db.select(AuditLog).filter_by(action="DATA_EXPORTED")) is not None
    # El analista no tiene permiso de exportación
    assert client.get("/api/opportunities/export", headers=as_role("analyst")).status_code == 403


def test_link_documents(client, as_role):
    import io

    h = as_role("manager")
    opp = _create(client, h)
    doc = client.post("/api/documents", data={"file": (io.BytesIO(b"Pliego de requisitos"), "pliego.txt")},
                      headers=h, content_type="multipart/form-data").json
    url = f"/api/opportunities/{opp['id']}/documents"
    resp = client.post(url, json={"document_id": doc["id"], "role": "requirements"}, headers=h)
    assert resp.status_code == 201 and resp.json["documents"][0]["title"] == "pliego.txt"
    assert client.post(url, json={"document_id": doc["id"]}, headers=h).status_code == 409
    assert client.delete(f"{url}/{doc['id']}", headers=h).status_code == 204
    assert client.get(f"/api/opportunities/{opp['id']}", headers=h).json["documents"] == []
