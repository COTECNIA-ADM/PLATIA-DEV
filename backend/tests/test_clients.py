from app.extensions import db
from app.models import AuditLog, Client


def test_manager_crud_and_optimistic_lock(client, as_role):
    h = as_role("manager")
    resp = client.post("/api/clients", json={"name": "Ayuntamiento de Ejemplo", "tax_id": "P1234567A",
                                             "sector": "public", "segment": "A"}, headers=h)
    assert resp.status_code == 201, resp.json
    cid, version = resp.json["id"], resp.json["version"]
    assert version == 1

    resp = client.patch(f"/api/clients/{cid}", json={"version": version, "risk_level": "low"}, headers=h)
    assert resp.status_code == 200 and resp.json["version"] == 2

    # Otra persona edita con la versión antigua: 409 en lugar de pisar el cambio
    resp = client.patch(f"/api/clients/{cid}", json={"version": 1, "name": "Otro"}, headers=h)
    assert resp.status_code == 409
    assert resp.json["details"]["current_version"] == 2

    resp = client.patch(f"/api/clients/{cid}", json={"name": "Sin versión"}, headers=h)
    assert resp.status_code == 422

    contact = client.post(f"/api/clients/{cid}/contacts",
                          json={"full_name": "Marta Ruiz", "email": "marta@example.com", "is_primary": True},
                          headers=h)
    assert contact.status_code == 201
    detail = client.get(f"/api/clients/{cid}", headers=h).json
    assert detail["contacts"][0]["full_name"] == "Marta Ruiz"

    assert client.delete(f"/api/clients/{cid}", headers=h).status_code == 204
    assert client.get(f"/api/clients/{cid}", headers=h).status_code == 404
    assert db.session.get(Client, cid).deleted_at is not None  # borrado lógico
    actions = {a.action for a in db.session.scalars(db.select(AuditLog))}
    assert {"RECORD_CREATED", "RECORD_UPDATED", "RECORD_DELETED"} <= actions


def test_viewer_reads_but_cannot_write(client, as_role):
    h = as_role("viewer")
    assert client.get("/api/clients", headers=h).status_code == 200
    assert client.post("/api/clients", json={"name": "X"}, headers=h).status_code == 403


def test_validation_rejects_unknown_fields_and_nulls(client, as_role):
    h = as_role("manager")
    resp = client.post("/api/clients", json={"name": "A", "is_admin": True}, headers=h)
    assert resp.status_code == 422 and resp.json["fields"][0]["field"] == "is_admin"
    cid = client.post("/api/clients", json={"name": "A"}, headers=h).json["id"]
    resp = client.patch(f"/api/clients/{cid}", json={"version": 1, "name": None}, headers=h)
    assert resp.status_code == 422


def test_duplicate_tax_id_is_conflict(client, as_role):
    h = as_role("manager")
    assert client.post("/api/clients", json={"name": "A", "tax_id": "B1"}, headers=h).status_code == 201
    assert client.post("/api/clients", json={"name": "B", "tax_id": "B1"}, headers=h).status_code == 409


def test_search_escapes_like_wildcards(client, as_role):
    h = as_role("manager")
    for name in ("100% Digital", "Otra empresa"):
        client.post("/api/clients", json={"name": name}, headers=h)
    assert client.get("/api/clients?q=%", headers=h).json["pagination"]["total"] == 1
    assert client.get("/api/clients?q=_", headers=h).json["pagination"]["total"] == 0
    body = client.get("/api/clients?per_page=1000", headers=h).json
    assert body["pagination"]["per_page"] == 100


def test_contact_belongs_to_client(client, as_role):
    h = as_role("manager")
    a = client.post("/api/clients", json={"name": "A"}, headers=h).json["id"]
    b = client.post("/api/clients", json={"name": "B"}, headers=h).json["id"]
    contact = client.post(f"/api/clients/{a}/contacts", json={"full_name": "C"}, headers=h).json
    resp = client.patch(f"/api/clients/{b}/contacts/{contact['id']}", json={"version": 1, "phone": "1"},
                        headers=h)
    assert resp.status_code == 404


def test_unknown_routes_and_methods_return_json(client, as_role):
    h = as_role("manager")
    assert client.get("/api/nada", headers=h).json == {"error": "Recurso no encontrado."}
    assert client.put("/api/clients", headers=h).status_code == 405
