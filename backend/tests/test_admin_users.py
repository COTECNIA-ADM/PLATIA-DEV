"""Administración de usuarios, roles y auditoría (fase 6b)."""
from conftest import PASSWORD

from app.extensions import db
from app.models import AppRole, User


def _admin(make_user, login, role="admin", email="jefa@example.com"):
    make_user(email, roles={"admin": role})
    return {**login(email), "X-App-Code": "admin"}


def test_users_list_is_paginated_and_filterable(client, make_user, login):
    admin = _admin(make_user, login)
    make_user("ana@example.com", roles={"operations": "analyst"})
    make_user("luis@example.com", roles={"analytics": "viewer"})
    page = client.get("/api/admin/users?per_page=2", headers=admin).json
    assert page["pagination"]["total"] == 3 and len(page["items"]) == 2
    only_ops = client.get("/api/admin/users?app=operations", headers=admin).json["items"]
    assert [u["email"] for u in only_ops] == ["ana@example.com"]
    assert client.get("/api/admin/users?q=LUIS", headers=admin).json["items"][0]["email"] == "luis@example.com"


def test_create_user_validates_input(client, make_user, login):
    admin = _admin(make_user, login)
    assert client.post("/api/admin/users", headers=admin,
                       json={"email": "x", "full_name": "X", "password": PASSWORD}).status_code == 422
    assert client.post("/api/admin/users", headers=admin,
                       json={"email": "x@example.com", "full_name": "X", "password": "corta"}).status_code == 422
    assert client.post("/api/admin/users", headers=admin, json={"email": "x@example.com", "full_name": "X",
                                                                "password": PASSWORD, "is_superadmin": True}
                       ).status_code == 422
    ok = client.post("/api/admin/users", headers=admin,
                     json={"email": "x@example.com", "full_name": "X", "password": PASSWORD})
    assert ok.status_code == 201
    dup = client.post("/api/admin/users", headers=admin,
                      json={"email": "X@example.com", "full_name": "X", "password": PASSWORD})
    assert dup.status_code == 409


def test_revoke_and_reactivate(client, make_user, login):
    admin = _admin(make_user, login)
    user = make_user("ana@example.com", roles={"operations": "analyst"})
    ana = login("ana@example.com")
    assert client.get("/api/auth/me", headers=ana).status_code == 200
    resp = client.delete(f"/api/admin/users/{user.id}/memberships/operations", headers=admin)
    assert resp.status_code == 200 and resp.json["user"]["memberships"][0]["is_active"] is False
    assert client.get("/api/auth/me", headers=ana).status_code == 403  # sin rol, efecto inmediato
    assert client.delete(f"/api/admin/users/{user.id}/memberships/operations", headers=admin).status_code == 404

    assert client.post(f"/api/admin/users/{user.id}/deactivate", headers=admin).status_code == 200
    assert client.post(f"/api/admin/users/{user.id}/reactivate", headers=admin).json["user"]["is_active"] is True
    assert client.post(f"/api/admin/users/{user.id}/reactivate", headers=admin).status_code == 422


def test_admin_cannot_remove_own_admin_access(client, make_user, login):
    admin = _admin(make_user, login)
    me = db.session.scalar(db.select(User).filter_by(email="jefa@example.com"))
    assert client.delete(f"/api/admin/users/{me.id}/memberships/admin", headers=admin).status_code == 422


def test_mfa_reset_by_admin(client, make_user, login):
    admin = _admin(make_user, login)
    user = make_user("ana@example.com", roles={"operations": "analyst"})
    assert client.post(f"/api/admin/users/{user.id}/mfa/reset", headers=admin).status_code == 422  # sin MFA
    user = db.session.get(User, user.id)
    user.mfa_enabled, user.mfa_secret_encrypted = True, "x"
    db.session.commit()
    resp = client.post(f"/api/admin/users/{user.id}/mfa/reset", headers=admin)
    assert resp.status_code == 200 and resp.json["user"]["mfa_enabled"] is False


def test_role_editor(client, make_user, login):
    admin = _admin(make_user, login)
    apps = client.get("/api/admin/apps", headers=admin).json
    ops = next(a for a in apps["items"] if a["code"] == "operations")
    viewer = next(r for r in ops["roles"] if r["code"] == "viewer")
    assert "opportunities" in [m["module"] for m in ops["modules"]] and "copilot_chat" in apps["ai_modules"]

    user = make_user("ana@example.com", roles={"operations": "viewer"})
    ana = login("ana@example.com")
    assert "export" not in client.get("/api/auth/me", headers=ana).json["active_app"]["permissions"]["opportunities"]

    body = {"version": viewer["version"], "permissions": {**viewer["permissions"],
                                                          "opportunities": ["read", "export"]}}
    resp = client.patch(f"/api/admin/roles/{viewer['id']}", headers=admin, json=body)
    assert resp.status_code == 200, resp.json
    assert resp.json["members"] == 1 and resp.json["version"] == viewer["version"] + 1
    assert "export" in client.get("/api/auth/me", headers=ana).json["active_app"]["permissions"]["opportunities"]

    # Versión antigua, permiso inventado o módulo de otra app: rechazados
    assert client.patch(f"/api/admin/roles/{viewer['id']}", headers=admin, json=body).status_code == 409
    fresh = {"version": resp.json["version"]}
    assert client.patch(f"/api/admin/roles/{viewer['id']}", headers=admin,
                        json={**fresh, "permissions": {"opportunities": ["fly"]}}).status_code == 422
    assert client.patch(f"/api/admin/roles/{viewer['id']}", headers=admin,
                        json={**fresh, "permissions": {"users": ["read"]}}).status_code == 422
    admin_role = next(r for r in ops["roles"] if r["is_admin"])
    assert client.patch(f"/api/admin/roles/{admin_role['id']}", headers=admin,
                        json={"version": admin_role["version"], "permissions": {}}).status_code == 422
    assert db.session.get(AppRole, viewer["id"]).permissions["opportunities"] == ["export", "read"]
    assert user.id


def test_auditor_reads_but_cannot_edit_roles(client, make_user, login):
    auditor = _admin(make_user, login, role="auditor", email="audit@example.com")
    apps = client.get("/api/admin/apps", headers=auditor).json["items"]
    role = apps[0]["roles"][-1]
    assert client.patch(f"/api/admin/roles/{role['id']}", headers=auditor,
                        json={"version": role["version"], "permissions": {}}).status_code == 403


def test_audit_log_is_paginated_and_filterable(client, make_user, login):
    admin = _admin(make_user, login)
    make_user("ana@example.com", roles={"operations": "analyst"})
    client.post("/api/auth/login", json={"email": "ana@example.com", "password": "mal"})
    page = client.get("/api/admin/audit?action=LOGIN_FAILED", headers=admin).json
    assert page["pagination"]["total"] == 1
    entry = page["items"][0]
    assert entry["user_email"] == "ana@example.com" and entry["created_at"].endswith("Z")
    assert "LOGIN_FAILED" in client.get("/api/admin/audit/actions", headers=admin).json["items"]
    assert client.get("/api/admin/audit?severity=WARNING&days=1", headers=admin).status_code == 200
