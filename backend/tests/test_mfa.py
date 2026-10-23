"""MFA con TOTP y códigos de respaldo (Capítulo 6, error 3: sal por código)."""
import pyotp

from app.extensions import db
from app.models import User

from conftest import PASSWORD


def _enable_mfa(client, headers):
    setup = client.post("/api/auth/mfa/setup", headers=headers)
    secret = setup.json["secret"]
    assert setup.json["otpauth_uri"].startswith("otpauth://totp/")
    assert client.post("/api/auth/mfa/enable", headers=headers, json={"code": "000000"}).status_code == 400
    enabled = client.post("/api/auth/mfa/enable", headers=headers, json={"code": pyotp.TOTP(secret).now()})
    assert enabled.status_code == 200
    return secret, enabled.json["backup_codes"]


def test_mfa_full_flow(client, make_user, login):
    user = make_user(roles={"operations": "viewer"})
    secret, codes = _enable_mfa(client, login())
    assert len(codes) == 10

    stored = db.session.get(User, user.id)
    assert secret not in stored.mfa_secret_encrypted  # cifrado con Fernet
    assert all(c not in str(stored.mfa_backup_codes) for c in codes)  # nunca en claro
    assert len({e["salt"] for e in stored.mfa_backup_codes}) == 10  # una sal por código

    step1 = client.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert step1.json["mfa_required"] is True and "access_token" not in step1.json
    bad = client.post("/api/auth/mfa/verify", json={"mfa_token": step1.json["mfa_token"], "code": "123456"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/mfa/verify",
                     json={"mfa_token": step1.json["mfa_token"], "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200 and ok.json["access_token"]
    again = client.post("/api/auth/mfa/verify",
                        json={"mfa_token": step1.json["mfa_token"], "code": pyotp.TOTP(secret).now()})
    assert again.status_code == 401  # el token de segundo factor no se reutiliza


def test_backup_code_works_once(client, make_user, login):
    make_user(roles={"operations": "viewer"})
    _, codes = _enable_mfa(client, login())

    def attempt():
        token = client.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD}).json["mfa_token"]
        return client.post("/api/auth/mfa/verify", json={"mfa_token": token, "code": codes[0]}).status_code

    assert attempt() == 200
    assert attempt() == 401


def test_mfa_verify_rejects_garbage_token(client):
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": "no", "code": "1"}).status_code == 401


def test_disable_requires_password_and_code(client, make_user, login):
    make_user(roles={"operations": "viewer"})
    headers = login()
    secret, _ = _enable_mfa(client, headers)
    assert client.post("/api/auth/mfa/disable", headers=headers,
                       json={"password": PASSWORD, "code": "000000"}).status_code == 400
    assert client.post("/api/auth/mfa/disable", headers=headers,
                       json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()}).status_code == 200
