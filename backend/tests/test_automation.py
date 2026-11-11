"""Portal Low-Code (app automation, ADR-020): estado y catálogo leídos de n8n."""
import pytest
import requests

from app.services import automation as service


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


WORKFLOWS = [
    {"id": "b2", "name": "Aviso de oportunidad", "active": True, "updatedAt": "2026-11-10T09:00:00.000Z",
     "tags": [{"id": "1", "name": "platia"}, {"id": "2", "name": "comercial"}],
     "nodes": [{"parameters": {"secreto": "no-debe-salir"}}]},
    {"id": "a1", "name": "buzón de pliegos", "active": False, "updatedAt": None,
     "tags": [{"id": "1", "name": "platia"}]},
]


@pytest.fixture()
def n8n(monkeypatch):
    """Sustituye la API de n8n; guarda cada llamada para comprobar la clave y los filtros."""
    state = {"responses": [FakeResponse(body={"data": WORKFLOWS, "nextCursor": None})], "calls": []}

    def fake_get(url, params=None, headers=None, timeout=None, allow_redirects=True):
        state["calls"].append({"url": url, "params": dict(params or {}), "headers": headers,
                               "allow_redirects": allow_redirects})
        item = state["responses"].pop(0) if len(state["responses"]) > 1 else state["responses"][0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(service.requests, "get", fake_get)
    return state


@pytest.fixture()
def as_automation(make_user, login):
    def _as(role: str):
        email = f"auto-{role}@example.com"
        make_user(email=email, roles={"automation": role})
        return {**login(email), "X-App-Code": "automation"}

    return _as


def test_catalog_lists_tagged_workflows_without_their_insides(client, as_automation, n8n):
    resp = client.get("/api/automation/catalog", headers=as_automation("user"))
    assert resp.status_code == 200
    body = resp.json
    assert [w["name"] for w in body["items"]] == ["Aviso de oportunidad", "buzón de pliegos"]
    assert body["items"][0] == {"id": "b2", "name": "Aviso de oportunidad", "active": True,
                                "tags": ["comercial", "platia"], "updated_at": "2026-11-10T09:00:00.000Z"}
    assert "no-debe-salir" not in resp.get_data(as_text=True)
    assert body["pagination"] == {"page": 1, "per_page": 20, "total": 2, "pages": 1}
    assert body["source"] == {"enabled": True, "reachable": True, "problem": None}
    call = n8n["calls"][0]
    assert call["url"] == "http://n8n:5678/api/v1/workflows"
    assert call["params"]["tags"] == "platia"
    assert call["headers"]["X-N8N-API-KEY"] == "test-n8n-key"
    assert call["allow_redirects"] is False


def test_catalog_filters_by_text_and_state(client, as_automation, n8n):
    headers = as_automation("viewer")
    assert [w["id"] for w in client.get("/api/automation/catalog?q=PLIEGOS", headers=headers).json["items"]] == ["a1"]
    assert [w["id"] for w in client.get("/api/automation/catalog?q=comercial", headers=headers).json["items"]] == ["b2"]
    assert [w["id"] for w in client.get("/api/automation/catalog?active=true", headers=headers).json["items"]] == ["b2"]
    page2 = client.get("/api/automation/catalog?per_page=1&page=2", headers=headers).json
    assert [w["id"] for w in page2["items"]] == ["a1"] and page2["pagination"]["pages"] == 2


def test_catalog_follows_the_cursor(client, as_automation, n8n):
    n8n["responses"] = [FakeResponse(body={"data": WORKFLOWS[:1], "nextCursor": "c2"}),
                        FakeResponse(body={"data": WORKFLOWS[1:], "nextCursor": None})]
    resp = client.get("/api/automation/catalog", headers=as_automation("user"))
    assert resp.json["pagination"]["total"] == 2
    assert n8n["calls"][1]["params"]["cursor"] == "c2"


@pytest.mark.parametrize("failure, problem", [
    (requests.ConnectionError("caído"), "No se puede conectar con n8n."),
    (FakeResponse(status=401), "n8n rechaza la clave de su API."),
    (FakeResponse(status=500), "No se puede conectar con n8n."),
])
def test_n8n_down_gives_an_empty_catalog_and_a_reason(client, as_automation, n8n, failure, problem):
    n8n["responses"] = [failure]
    resp = client.get("/api/automation/catalog", headers=as_automation("user"))
    assert resp.status_code == 200
    assert resp.json["items"] == []
    assert resp.json["source"] == {"enabled": True, "reachable": False, "problem": problem}


def test_disabled_n8n_is_not_called(app, client, as_automation, n8n):
    app.config["N8N_ENABLED"] = False
    resp = client.get("/api/automation/status", headers=as_automation("user"))
    assert resp.json["enabled"] is False and resp.json["published"] == 0
    assert n8n["calls"] == []


def test_missing_api_key_is_explained(app, client, as_automation, n8n):
    app.config["N8N_API_KEY"] = ""
    resp = client.get("/api/automation/catalog", headers=as_automation("user"))
    assert resp.json["source"]["problem"] == "Falta la clave de la API de n8n (N8N_API_KEY)."
    assert n8n["calls"] == []


def test_status_gives_the_editor_link_only_to_builders(client, as_automation, n8n):
    user = client.get("/api/automation/status", headers=as_automation("user")).json
    builder = client.get("/api/automation/status", headers=as_automation("builder")).json
    admin = client.get("/api/automation/status", headers=as_automation("admin")).json
    assert user == {"enabled": True, "reachable": True, "problem": None, "published": 2, "active": 1,
                    "editor_url": None}
    assert builder["editor_url"] == admin["editor_url"] == "http://localhost:5679/"


def test_routes_only_exist_in_the_automation_app(client, make_user, login, n8n):
    make_user(email="mixto@example.com", roles={"operations": "manager", "automation": "user"})
    headers = login("mixto@example.com")
    resp = client.get("/api/automation/catalog", headers={**headers, "X-App-Code": "operations"})
    assert resp.status_code == 403


def test_seeded_roles(client, as_automation, n8n):
    me = client.get("/api/auth/me", headers=as_automation("builder")).json
    apps = (me.get("user") or me)["apps"]
    assert {"code": "automation", "role": "builder"}.items() <= next(a for a in apps if a["code"] == "automation").items()
