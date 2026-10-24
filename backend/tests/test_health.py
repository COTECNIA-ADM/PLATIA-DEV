from unittest.mock import patch

import pytest



@pytest.fixture()
def admin_headers(make_user, login):
    make_user("root@example.com", superadmin=True)
    return {**login("root@example.com"), "X-App-Code": "admin"}


def test_quick_health_reports_unhealthy_redis_with_503(client):
    with patch("app.routes.health.redis.Redis.from_url") as from_url:
        from_url.return_value.ping.side_effect = ConnectionError("sin redis")
        resp = client.get("/api/health")
    assert resp.status_code == 503
    services = {s["name"]: s["status"] for s in resp.json["services"]}
    assert services == {"database_platform": "healthy", "redis": "unhealthy"}


def test_quick_health_ok_when_everything_responds(client):
    with patch("app.routes.health.redis.Redis.from_url"):
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json["status"] == "healthy"


def test_full_health_requires_login(client):
    assert client.get("/api/health/full").status_code == 401


def test_full_health_denied_without_health_permission(client, make_user, login):
    make_user("viewer@example.com", roles={"operations": "viewer"})
    resp = client.get("/api/health/full", headers=login("viewer@example.com"))
    assert resp.status_code == 403


def test_full_health_lists_every_core_service(client, admin_headers):
    with patch("app.routes.health.redis.Redis.from_url"), patch(
        "app.routes.health._check_workers", return_value=None
    ), patch("app.routes.health.requests.get") as get:
        get.return_value.json.return_value = {"status": "healthy"}
        resp = client.get("/api/health/full", headers=admin_headers)
    names = [s["name"] for s in resp.json["services"]]
    assert names == [
        "database_platform",
        "database_operations",
        "database_analytics",
        "redis",
        "qdrant",
        "meilisearch",
        "ai_service",
        "workers",
    ]
    assert resp.status_code == 200


def test_full_health_degraded_when_ai_has_no_anthropic_key(client, admin_headers):
    with patch("app.routes.health.redis.Redis.from_url"), patch(
        "app.routes.health._check_workers", return_value=None
    ), patch("app.routes.health.requests.get") as get:
        get.return_value.json.return_value = {"status": "degraded"}
        resp = client.get("/api/health/full", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json["status"] == "degraded"
    ai = next(s for s in resp.json["services"] if s["name"] == "ai_service")
    assert ai["status"] == "degraded"
    assert "ANTHROPIC_API_KEY" in ai["detail"]


def test_request_id_is_propagated(client):
    with patch("app.routes.health.redis.Redis.from_url"):
        resp = client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["X-Request-ID"] == "abc-123"


def test_missing_env_vars_fail_fast(monkeypatch):
    from app.config import Config

    monkeypatch.delenv("DB_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="DB_PASSWORD"):
        Config()


def test_full_health_degraded_without_workers(client, admin_headers):
    with patch("app.routes.health.redis.Redis.from_url"), patch(
        "app.queue.celery.control.ping", return_value=[]
    ), patch("app.routes.health.requests.get") as get:
        get.return_value.json.return_value = {"status": "healthy"}
        resp = client.get("/api/health/full", headers=admin_headers)
    workers = next(s for s in resp.json["services"] if s["name"] == "workers")
    assert resp.status_code == 200 and workers["status"] == "degraded"


def test_internal_errors_do_not_leak_details(client, admin_headers):
    with patch("app.routes.health._check_database", side_effect=RuntimeError("secreto: /etc/db")):
        resp = client.get("/api/health/full", headers=admin_headers)
    assert resp.status_code == 500
    assert "secreto" not in resp.get_data(as_text=True)
    assert resp.json["error"] == "Error interno del servidor."
