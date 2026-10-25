"""Tokens manipulados (fase 7a, OWASP API2: autenticación rota).

Cada caso es un token que alguien podría fabricar o reutilizar; todos deben dar 401 y
ninguno debe dejar ver datos.
"""
import base64
import json
from datetime import timedelta

import jwt
from flask_jwt_extended import create_access_token, create_refresh_token

from app.extensions import db

ROUTE = "/api/opportunities"


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _claims(app, user_id: int) -> dict:
    with app.test_request_context():
        token = create_access_token(identity=str(user_id))
    return jwt.decode(token, options={"verify_signature": False})


def _get(client, token: str):
    return client.get(ROUTE, headers={"Authorization": f"Bearer {token}"})


def test_valid_token_works(client, app, make_user):
    user = make_user(roles={"operations": "viewer"})
    with app.test_request_context():
        token = create_access_token(identity=str(user.id))
    assert _get(client, token).status_code == 200


def test_unsigned_token_alg_none_is_rejected(client, app, make_user):
    user = make_user(roles={"operations": "viewer"})
    token = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(_claims(app, user.id))}."
    assert _get(client, token).status_code == 401


def test_token_signed_with_another_key_is_rejected(client, app, make_user):
    user = make_user(roles={"operations": "viewer"})
    token = jwt.encode(_claims(app, user.id), "otra-clave-que-no-es-la-del-servidor-32b", algorithm="HS256")
    assert _get(client, token).status_code == 401


def test_changing_the_user_breaks_the_signature(client, app, make_user):
    victim = make_user("victima@example.com", roles={"operations": "manager"})
    attacker = make_user("atacante@example.com", roles={"operations": "viewer"})
    with app.test_request_context():
        header, _, signature = create_access_token(identity=str(attacker.id)).split(".")
    forged = _b64({**_claims(app, attacker.id), "sub": str(victim.id)})
    assert _get(client, f"{header}.{forged}.{signature}").status_code == 401


def test_expired_token_is_rejected(client, app, make_user):
    user = make_user(roles={"operations": "viewer"})
    with app.test_request_context():
        token = create_access_token(identity=str(user.id), expires_delta=timedelta(seconds=-5))
    assert _get(client, token).status_code == 401


def test_refresh_token_is_not_an_access_token(client, app, make_user):
    user = make_user(roles={"operations": "viewer"})
    with app.test_request_context():
        token = create_refresh_token(identity=str(user.id))
    assert _get(client, token).status_code == 401


def test_token_of_a_deactivated_user_stops_working(client, app, make_user):
    user = make_user(roles={"operations": "viewer"})
    with app.test_request_context():
        token = create_access_token(identity=str(user.id))
    user.is_active = False
    db.session.commit()
    assert _get(client, token).status_code == 401


def test_token_of_a_user_that_does_not_exist(client, app, seeded):
    with app.test_request_context():
        token = create_access_token(identity="999999")
    assert _get(client, token).status_code == 401


def test_errors_do_not_leak_internals(client):
    resp = _get(client, "a.b.c")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 401
    assert "Traceback" not in body and "jwt" not in body.lower()
