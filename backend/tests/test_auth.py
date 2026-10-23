"""Login, sesiones, bloqueo y límite de peticiones (Capítulo 6)."""
from datetime import timedelta

from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models import AuditLog, User, UserSession, utcnow

from conftest import PASSWORD


def _actions():
    return [a.action for a in db.session.scalars(db.select(AuditLog).order_by(AuditLog.id))]


def test_login_ok_returns_access_token_and_refresh_cookie(client, make_user):
    make_user(roles={"operations": "viewer"})
    resp = client.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json["access_token"]
    cookie = resp.headers.get("Set-Cookie")
    assert "platia_refresh=" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert "Path=/api/auth" in cookie
    assert resp.json["user"]["apps"] == [
        {"code": "operations", "name": "Operaciones", "role": "viewer", "is_admin": False}
    ]
    assert "LOGIN_SUCCESS" in _actions()


def test_login_errors_do_not_reveal_whether_email_exists(client, make_user):
    make_user()
    wrong_pw = client.post("/api/auth/login", json={"email": "ana@example.com", "password": "x"})
    unknown = client.post("/api/auth/login", json={"email": "nadie@example.com", "password": "x"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json == unknown.json


def test_account_locks_after_repeated_failures(seeded, make_user):
    seeded.config["RATE_LIMIT_LOGIN"] = 100  # aislar el bloqueo del límite de peticiones
    client = seeded.test_client()
    user = make_user()
    for _ in range(5):
        client.post("/api/auth/login", json={"email": user.email, "password": "mala"})
    resp = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert resp.status_code == 401
    db.session.refresh(user)
    assert user.locked_until and user.locked_until > utcnow()
    assert "ACCOUNT_LOCKED" in _actions()

    user.locked_until = utcnow() - timedelta(seconds=1)  # pasa el tiempo de bloqueo
    db.session.commit()
    assert client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD}).status_code == 200


def test_login_is_rate_limited_per_ip(client, make_user):
    make_user()
    codes = [
        client.post("/api/auth/login", json={"email": "x@example.com", "password": "x"}).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429
    resp = client.post("/api/auth/login", json={"email": "x@example.com", "password": "x"})
    assert int(resp.headers["Retry-After"]) > 0


def test_refresh_rotates_and_detects_reuse(client, make_user):
    make_user(roles={"operations": "viewer"})
    client.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    old_cookie = client.get_cookie("platia_refresh", path="/api/auth").value

    first = client.post("/api/auth/refresh")
    assert first.status_code == 200 and first.json["access_token"]
    new_access = first.json["access_token"]
    assert client.get_cookie("platia_refresh", path="/api/auth").value != old_cookie

    # Alguien reutiliza el token de refresco antiguo: se revoca toda la familia
    client.set_cookie("platia_refresh", old_cookie, path="/api/auth")
    reuse = client.post("/api/auth/refresh")
    assert reuse.status_code == 401
    assert "REFRESH_TOKEN_REUSE" in _actions()
    assert db.session.scalar(db.select(db.func.count()).select_from(UserSession).filter_by(is_active=True)) == 0
    # y el token de acceso emitido en la rotación deja de valer
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_access}"}).status_code == 401


def test_logout_revokes_access_token(client, make_user, login):
    make_user(roles={"operations": "viewer"})
    headers = login()
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/refresh").status_code == 401


def test_password_change_closes_every_session(client, make_user, login):
    make_user(roles={"operations": "viewer"})
    headers = login()
    weak = client.post("/api/auth/password", headers=headers,
                       json={"current_password": PASSWORD, "new_password": "corta"})
    assert weak.status_code == 400
    ok = client.post("/api/auth/password", headers=headers,
                     json={"current_password": PASSWORD, "new_password": "Otra-Clave-Larga-456"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ana@example.com", "password": "Otra-Clave-Larga-456"}).status_code == 200


def test_security_headers_on_api_responses(client):
    resp = client.get("/api/health")
    for header in ("Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options",
                   "Referrer-Policy", "Permissions-Policy", "Strict-Transport-Security"):
        assert header in resp.headers


def test_mfa_pending_token_is_not_a_session(client, make_user):
    user = make_user(roles={"operations": "viewer"})
    token = create_access_token(identity=str(user.id), additional_claims={"mfa_pending": True})
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_password_is_stored_hashed(make_user):
    user = make_user()
    stored = db.session.get(User, user.id).password_hash
    assert stored.startswith("$2b$") and PASSWORD not in stored
