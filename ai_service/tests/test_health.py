from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.settings import Settings, get_settings


def _settings(**overrides) -> Settings:
    base = {"api_key": "secret", "anthropic_api_key": "sk-test", "qdrant_api_key": ""}
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _qdrant_ok():
    resp = httpx.Response(200, request=httpx.Request("GET", "http://qdrant:6333/readyz"))
    return patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp))


def test_health_requires_api_key(client):
    app.dependency_overrides[get_settings] = lambda: _settings()
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"X-API-Key": "otra"}).status_code == 401


def test_health_ok(client):
    app.dependency_overrides[get_settings] = lambda: _settings()
    with _qdrant_ok():
        resp = client.get("/health", headers={"X-API-Key": "secret"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_health_degraded_without_anthropic_key(client):
    app.dependency_overrides[get_settings] = lambda: _settings(anthropic_api_key="")
    with _qdrant_ok():
        resp = client.get("/health", headers={"X-API-Key": "secret"})
    assert resp.json()["status"] == "degraded"
