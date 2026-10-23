"""Autorización: rol verificado en BD y default-deny (Capítulo 6, errores 1 y 2)."""
from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models import AuditLog, UserAppMembership

from conftest import PASSWORD


def test_forged_admin_claims_in_token_are_ignored(client, make_user):
    """Error 1 del libro: el guard leía is_admin del JWT. Aquí solo cuenta la BD."""
    user = make_user("viewer@example.com", roles={"operations": "viewer"})
    forged = create_access_token(identity=str(user.id),
                                 additional_claims={"is_admin": True, "role": "superadmin"})
    headers = {"Authorization": f"Bearer {forged}", "X-App-Code": "admin"}
    assert client.get("/api/admin/users", headers=headers).status_code == 403
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).json
    assert me["active_app"]["is_admin"] is False


def test_no_membership_in_app_is_denied_and_audited(client, make_user, login):
    make_user(roles={"operations": "viewer"})
    resp = client.get("/api/auth/me", headers={**login(), "X-App-Code": "security"})
    assert resp.status_code == 403
    entry = db.session.scalars(db.select(AuditLog).filter_by(action="ACCESS_DENIED")).first()
    assert entry is not None and entry.severity == "WARNING"


def test_unknown_app_is_denied(client, make_user, login):
    make_user(roles={"operations": "viewer"})
    assert client.get("/api/auth/me", headers={**login(), "X-App-Code": "inventada"}).status_code == 403


def test_permissions_are_read_from_the_role(client, make_user, login):
    make_user("auditor@example.com", roles={"admin": "auditor"})
    headers = {**login("auditor@example.com"), "X-App-Code": "admin"}
    assert client.get("/api/admin/users", headers=headers).status_code == 200
    create = client.post("/api/admin/users", headers=headers,
                         json={"email": "b@example.com", "full_name": "B", "password": PASSWORD})
    assert create.status_code == 403  # el auditor solo lee


def test_superadmin_cannot_use_unknown_app(client, make_user, login):
    make_user("root@example.com", superadmin=True)
    headers = {**login("root@example.com"), "X-App-Code": "inventada"}
    assert client.get("/api/auth/me", headers=headers).status_code == 403


def test_admin_routes_only_inside_admin_app(client, make_user, login):
    make_user("root@example.com", superadmin=True)
    headers = login("root@example.com")  # sin X-App-Code: operations
    assert client.get("/api/admin/users", headers=headers).status_code == 403


def test_admin_creates_user_assigns_role_and_deactivates(client, make_user, login):
    make_user("jefe@example.com", roles={"admin": "admin"})
    admin = {**login("jefe@example.com"), "X-App-Code": "admin"}
    created = client.post("/api/admin/users", headers=admin,
                          json={"email": "Nuevo@Example.com", "full_name": "Nuevo", "password": PASSWORD})
    assert created.status_code == 201
    uid = created.json["user"]["id"]
    assert created.json["user"]["email"] == "nuevo@example.com"

    bad_role = client.put(f"/api/admin/users/{uid}/memberships/operations", headers=admin, json={"role": "jefe"})
    assert bad_role.status_code == 400
    ok = client.put(f"/api/admin/users/{uid}/memberships/operations", headers=admin, json={"role": "analyst"})
    assert ok.json["user"]["memberships"] == [{"app": "operations", "role": "analyst", "is_active": True}]

    user_headers = login("nuevo@example.com")
    assert client.get("/api/auth/me", headers=user_headers).json["active_app"]["role"] == "analyst"

    assert client.post(f"/api/admin/users/{uid}/deactivate", headers=admin).status_code == 200
    assert client.get("/api/auth/me", headers=user_headers).status_code == 401


def test_revoked_membership_takes_effect_immediately(client, make_user, login):
    user = make_user(roles={"operations": "viewer"})
    headers = login()
    assert client.get("/api/auth/me", headers=headers).status_code == 200  # rol en caché
    membership = db.session.scalar(db.select(UserAppMembership).filter_by(user_id=user.id))
    membership.is_active = False
    db.session.commit()
    from app.security.context import invalidate_permissions

    invalidate_permissions(user.id)
    assert client.get("/api/auth/me", headers=headers).status_code == 403


def test_require_permission_without_guard_denies():
    """Un decorador mal encadenado no abre la puerta (default-deny)."""
    from flask import Flask

    from app.security.context import require_permission

    app = Flask(__name__)

    @app.get("/x")
    @require_permission("clients", "read")
    def view():
        return "dentro"

    assert app.test_client().get("/x").status_code == 401
