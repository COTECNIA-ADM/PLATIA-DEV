import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db


@pytest.fixture()
def app():
    """App con las tablas de los tres binds creadas en SQLite en memoria."""
    app = create_app(TestConfig())
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
