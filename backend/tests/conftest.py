import fakeredis
import pytest
import structlog

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import App, AppRole, User, UserAppMembership
from app.security.passwords import hash_password
from app.seeds import run_seeds

PASSWORD = "Contrasena-Segura-123"


@pytest.fixture()
def app():
    """App con las tablas de los tres binds en SQLite en memoria y Redis falso."""
    structlog.contextvars.clear_contextvars()
    app = create_app(TestConfig())
    app.extensions["redis"] = fakeredis.FakeRedis()
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def seeded(app):
    run_seeds()
    return app


@pytest.fixture()
def client(seeded):
    return seeded.test_client()


@pytest.fixture()
def make_user(seeded):
    def _make(email="ana@example.com", roles=None, superadmin=False, password=PASSWORD):
        user = User(email=email, full_name=email.split("@")[0], password_hash=hash_password(password),
                    is_superadmin=superadmin)
        db.session.add(user)
        db.session.flush()
        for app_code, role_code in (roles or {}).items():
            app_row = db.session.scalar(db.select(App).filter_by(code=app_code))
            role = db.session.scalar(db.select(AppRole).filter_by(app_id=app_row.id, code=role_code))
            db.session.add(UserAppMembership(user_id=user.id, app_id=app_row.id, role_id=role.id))
        db.session.commit()
        return user

    return _make


@pytest.fixture()
def login(client):
    def _login(email="ana@example.com", password=PASSWORD):
        resp = client.post("/api/auth/login", json={"email": email, "password": password})
        assert resp.status_code == 200, resp.json
        return {"Authorization": f"Bearer {resp.json['access_token']}"}

    return _login


@pytest.fixture()
def as_role(make_user, login):
    """Crea un usuario con un rol de operaciones y devuelve sus cabeceras."""
    def _as(role: str, email: str | None = None, extra_roles: dict | None = None):
        email = email or f"{role}@example.com"
        user = make_user(email=email, roles={"operations": role, **(extra_roles or {})})
        headers = login(email)
        headers["X-User-Id"] = str(user.id)  # solo para los tests; el backend no la lee
        return headers

    return _as


def uid(headers: dict) -> int:
    return int(headers["X-User-Id"])
