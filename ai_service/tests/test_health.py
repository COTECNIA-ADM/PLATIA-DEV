from unittest.mock import AsyncMock, patch

import httpx

from app.main import app, get_settings

from .conftest import API_HEADERS, make_settings


def _qdrant_ok():
    resp = httpx.Response(200, request=httpx.Request("GET", "http://qdrant:6333/readyz"))
    return patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp))


def test_health_requires_api_key(client):
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"X-API-Key": "otra"}).status_code == 401


def test_health_ok(client):
    with _qdrant_ok():
        resp = client.get("/health", headers=API_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["embedding"]["provider"] == "hash"
    assert body["checks"]["anthropic_circuit"] == "closed"


def test_health_degraded_without_anthropic_key(client):
    app.dependency_overrides[get_settings] = lambda: make_settings(anthropic_api_key="")
    with _qdrant_ok():
        resp = client.get("/health", headers=API_HEADERS)
    assert resp.json()["status"] == "degraded"


def test_health_unhealthy_without_qdrant(client):
    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=httpx.ConnectError("x"))):
        resp = client.get("/health", headers=API_HEADERS)
    assert resp.json()["status"] == "unhealthy"
