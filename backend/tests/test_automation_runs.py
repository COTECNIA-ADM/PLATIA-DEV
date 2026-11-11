"""Portal Low-Code, fase L2 (ADR-020): lanzar un flujo de n8n, seguirlo y recibir su respuesta."""
import hashlib
import hmac
import json
from datetime import timedelta

import pytest
import requests

from app.extensions import db
from app.models import AutomationEntry, AutomationRun, utcnow
from app.services import automation as service
from app.tasks import automation as tasks

CALLBACK = {"X-Platia-Integration-Key": "test-callback-key"}


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def workflow(wid="w1", active=True, method="POST", tags=("platia",), path="pliegos"):
    return {"id": wid, "name": f"Flujo {wid}", "active": active,
            "tags": [{"id": str(i), "name": t} for i, t in enumerate(tags)],
            "nodes": [{"type": "n8n-nodes-base.webhook", "parameters": {"httpMethod": method, "path": path}},
                      {"type": "n8n-nodes-base.httpRequest", "parameters": {"url": "secreto-interno"}}]}


@pytest.fixture()
def n8n(monkeypatch):
    """API y webhooks de n8n falsos. ``workflows`` por id; ``webhook`` es la respuesta del POST."""
    state = {"workflows": {"w1": workflow()}, "webhook": FakeResponse(200, {"message": "Workflow was started"}),
             "posts": [], "get_error": None}

    def fake_get(url, params=None, headers=None, timeout=None, allow_redirects=True):
        if state["get_error"]:
            raise state["get_error"]
        wid = url.rsplit("/", 1)[-1]
        if wid == "workflows":
            return FakeResponse(200, {"data": list(state["workflows"].values()), "nextCursor": None})
        raw = state["workflows"].get(wid)
        return FakeResponse(200, raw) if raw else FakeResponse(404, {"message": "Not Found"})

    def fake_post(url, data=None, headers=None, timeout=None, allow_redirects=True):
        state["posts"].append({"url": url, "data": data, "headers": headers, "allow_redirects": allow_redirects})
        if isinstance(state["webhook"], Exception):
            raise state["webhook"]
        return state["webhook"]

    monkeypatch.setattr(service.requests, "get", fake_get)
    monkeypatch.setattr(service.requests, "post", fake_post)
    return state


@pytest.fixture()
def as_automation(make_user, login):
    def _as(role: str, email: str | None = None):
        email = email or f"run-{role}@example.com"
        make_user(email=email, roles={"automation": role})
        return {**login(email), "X-App-Code": "automation"}

    return _as


FIELDS = [{"name": "cliente", "label": "Cliente", "type": "text", "required": True},
          {"name": "importe", "label": "Importe", "type": "number"}]


def publish(wid="w1", fields=None, status="published") -> int:
    entry = AutomationEntry(workflow_id=wid, title=f"Ficha {wid}", status=status,
                            fields=FIELDS if fields is None else fields, created_by=1)
    db.session.add(entry)
    db.session.commit()
    return entry.id


def _launch(client, headers, entry_id=None, data=None):
    entry_id = entry_id or publish()
    return client.post("/api/automation/runs", headers=headers,
                       json={"entry_id": entry_id, "input": {"cliente": "Ayto. de Ejemplo"} if data is None else data})


# ---------------------------------------------------------------- Lanzar
def test_launch_calls_the_signed_webhook_and_marks_it_running(client, as_automation, n8n):
    resp = _launch(client, as_automation("user"), data={"cliente": "Ayto. de Ejemplo", "importe": 1200})
    assert resp.status_code == 202, resp.json
    run_id = resp.json["id"]
    assert resp.json["status"] == "running"
    assert resp.json["input"] == {"cliente": "Ayto. de Ejemplo", "importe": 1200}
    assert resp.json["entry_id"] and resp.json["workflow_name"] == "Ficha w1"

    post = n8n["posts"][0]
    assert post["url"] == "http://n8n:5678/webhook/pliegos"
    assert post["allow_redirects"] is False
    assert post["headers"]["X-Platia-Webhook-Key"] == "test-webhook-secret"
    body = json.loads(post["data"])
    assert body["run_id"] == run_id
    assert body["input"]["cliente"] == "Ayto. de Ejemplo"
    assert body["callback_url"] == f"http://backend:5000/api/automation/runs/{run_id}/callback"
    ts, mac = (part.split("=", 1)[1] for part in post["headers"]["X-Platia-Signature"].split(","))
    expected = hmac.new(b"test-webhook-secret", f"{ts}.".encode() + post["data"], hashlib.sha256).hexdigest()
    assert hmac.compare_digest(mac, expected)


def test_catalog_says_which_entries_can_be_launched(client, as_automation, n8n):
    n8n["workflows"]["w2"] = workflow("w2", method="GET")
    n8n["workflows"]["w3"] = workflow("w3", active=False)
    for wid in ("w1", "w2", "w3", "w4"):
        publish(wid)
    publish("w1", status="draft")
    items = client.get("/api/automation/catalog", headers=as_automation("viewer")).json["items"]
    assert [(w["title"], w["launchable"]) for w in items] == [
        ("Ficha w1", True), ("Ficha w2", False), ("Ficha w3", False), ("Ficha w4", False)]
    assert items[0]["fields"] == FIELDS
    assert "pliegos" not in json.dumps(items)  # la ruta del webhook no sale de PLATIA


@pytest.mark.parametrize("change, status", [
    ({"active": False}, 422),
    ({"method": "GET"}, 422),
    ({"tags": ("otra",)}, 422),
])
def test_only_published_active_webhook_workflows_can_be_launched(client, as_automation, n8n, change, status):
    n8n["workflows"]["w1"] = workflow(**change)
    assert _launch(client, as_automation("user")).status_code == status
    assert db.session.scalar(db.select(db.func.count(AutomationRun.id))) == 0
    assert n8n["posts"] == []


def test_only_published_entries_can_be_launched(client, as_automation, n8n):
    headers = as_automation("user")
    assert _launch(client, headers, entry_id=999).status_code == 404
    assert _launch(client, headers, entry_id=publish(status="draft")).status_code == 404
    assert _launch(client, headers, entry_id=publish("nada")).status_code == 422


@pytest.mark.parametrize("data", [
    {"anidado": {"a": 1}},
    {"mala clave": "x"},
    {"cliente": "x", "sobra": 1},
    {"importe": 3},
    {"cliente": "x", "importe": "mucho"},
    {"cliente": "x" * 301},
])
def test_input_must_match_the_entry_fields(client, as_automation, n8n, data):
    assert _launch(client, as_automation("user"), data=data).status_code == 422


def test_input_types(client, as_automation, n8n):
    fields = [{"name": "fecha", "label": "Fecha", "type": "date", "required": True},
              {"name": "canal", "label": "Canal", "type": "select", "options": ["correo", "teams"]},
              {"name": "urgente", "label": "Urgente", "type": "boolean"},
              {"name": "nota", "label": "Nota", "type": "textarea"}]
    entry_id = publish(fields=fields)
    headers = as_automation("user")
    ok = _launch(client, headers, entry_id, {"fecha": "2026-12-01", "canal": "teams", "nota": "x" * 1500})
    assert ok.status_code == 202
    assert ok.json["input"] == {"fecha": "2026-12-01", "canal": "teams", "urgente": False, "nota": "x" * 1500}
    assert _launch(client, headers, entry_id, {"fecha": "mañana"}).status_code == 422
    assert _launch(client, headers, entry_id, {"fecha": "2026-12-01", "canal": "fax"}).status_code == 422
    assert _launch(client, headers, entry_id, {"fecha": "2026-12-01", "urgente": "sí"}).status_code == 422
    assert client.post("/api/automation/runs", headers=headers,
                       json={"entry_id": entry_id, "extra": 1}).status_code == 422


def test_viewer_cannot_launch(client, as_automation, n8n):
    assert _launch(client, as_automation("viewer")).status_code == 403


def test_n8n_down_when_launching_is_a_clear_error(client, as_automation, n8n):
    n8n["get_error"] = requests.ConnectionError("sin red")
    resp = _launch(client, as_automation("user"))
    assert resp.status_code == 422
    assert "n8n" in resp.json["error"]


def test_webhook_rejection_fails_the_run(client, as_automation, n8n):
    n8n["webhook"] = FakeResponse(404, {"message": "webhook not registered"})
    resp = _launch(client, as_automation("user"))
    run = db.session.get(AutomationRun, resp.json["id"])
    assert run.status == "failed"
    assert "HTTP 404" in run.error


def test_dispatch_retries_and_finally_gives_up(app, n8n, monkeypatch):
    run = AutomationRun(workflow_id="w1", workflow_name="Flujo w1", status="queued", input_data={}, created_by=1)
    db.session.add(run)
    db.session.commit()
    n8n["webhook"] = FakeResponse(503)
    with pytest.raises(service.N8nUnavailable):
        service.dispatch(run)
    db.session.rollback()

    retried = []
    monkeypatch.setattr(tasks.run, "retry_later", lambda exc: retried.append(exc) or RuntimeError("retry"))
    with pytest.raises(RuntimeError):
        tasks.run.run(run.id)
    assert retried and db.session.get(AutomationRun, run.id).status == "queued"

    monkeypatch.setattr(tasks.run, "max_retries", 0)
    assert tasks.run.run(run.id) == {"status": "failed"}
    assert db.session.get(AutomationRun, run.id).error == "No se ha podido conectar con n8n."


def test_dispatch_is_idempotent(app, n8n):
    run = AutomationRun(workflow_id="w1", workflow_name="Flujo w1", status="running", created_by=1)
    db.session.add(run)
    db.session.commit()
    assert tasks.run.run(run.id) == {"status": "running"}
    assert n8n["posts"] == []
    assert tasks.run.run(999999) == {"status": "missing"}


def test_missing_webhook_secret_fails_without_calling_n8n(app, n8n):
    app.config["N8N_WEBHOOK_SECRET"] = ""
    try:
        run = AutomationRun(workflow_id="w1", workflow_name="Flujo w1", status="queued", created_by=1)
        db.session.add(run)
        db.session.commit()
        assert service.dispatch(run) == "failed"
        assert n8n["posts"] == []
    finally:
        app.config["N8N_WEBHOOK_SECRET"] = "test-webhook-secret"


# ---------------------------------------------------------------- Respuesta de n8n
def test_callback_closes_the_run_once(client, as_automation, n8n):
    headers = as_automation("user")
    run_id = _launch(client, headers).json["id"]
    url = f"/api/automation/runs/{run_id}/callback"
    ok = client.post(url, headers=CALLBACK, json={"status": "succeeded", "result": {"enviados": 3}})
    assert ok.status_code == 200 and ok.json == {"id": run_id, "status": "succeeded"}
    again = client.post(url, headers=CALLBACK, json={"status": "failed", "error": "tarde"})
    assert again.status_code == 409
    detail = client.get(f"/api/automation/runs/{run_id}", headers=headers).json
    assert detail["status"] == "succeeded" and detail["result"] == {"enviados": 3}
    assert detail["finished_at"]


def test_callback_needs_the_integration_key(client, as_automation, n8n):
    run_id = _launch(client, as_automation("user")).json["id"]
    url = f"/api/automation/runs/{run_id}/callback"
    body = {"status": "succeeded"}
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, headers={"X-Platia-Integration-Key": "mala"}, json=body).status_code == 401
    # Una sesión de persona tampoco vale
    assert client.post(url, headers=as_automation("admin"), json=body).status_code == 401
    assert client.post("/api/automation/runs/999999/callback", headers=CALLBACK, json=body).status_code == 404


def test_callback_without_configured_key_is_always_401(app, client, as_automation, n8n):
    run_id = _launch(client, as_automation("user")).json["id"]
    app.config["N8N_CALLBACK_KEY"] = ""
    try:
        resp = client.post(f"/api/automation/runs/{run_id}/callback",
                           headers={"X-Platia-Integration-Key": ""}, json={"status": "succeeded"})
        assert resp.status_code == 401
    finally:
        app.config["N8N_CALLBACK_KEY"] = "test-callback-key"


def test_callback_validates_its_body(client, as_automation, n8n):
    run_id = _launch(client, as_automation("user")).json["id"]
    url = f"/api/automation/runs/{run_id}/callback"
    assert client.post(url, headers=CALLBACK, json={"status": "quizá"}).status_code == 422
    big = {"status": "succeeded", "result": {"texto": "x" * 40_000}}
    assert client.post(url, headers=CALLBACK, json=big).status_code == 422


def test_failed_callback_keeps_the_error_not_the_result(client, as_automation, n8n):
    headers = as_automation("user")
    run_id = _launch(client, headers).json["id"]
    client.post(f"/api/automation/runs/{run_id}/callback", headers=CALLBACK,
                json={"status": "failed", "error": "El buzón no responde", "result": {"x": 1}})
    detail = client.get(f"/api/automation/runs/{run_id}", headers=headers).json
    assert detail["status"] == "failed" and detail["error"] == "El buzón no responde"
    assert detail["result"] is None


# ---------------------------------------------------------------- Seguir
def test_people_see_their_runs_and_managers_see_all(client, as_automation, n8n):
    ana = as_automation("user", "ana@example.com")
    luis = as_automation("user", "luis@example.com")
    boss = as_automation("admin", "jefa@example.com")
    ana_run = _launch(client, ana).json["id"]
    _launch(client, luis)

    mine = client.get("/api/automation/runs", headers=ana).json
    assert [r["id"] for r in mine["items"]] == [ana_run]
    assert "input" not in mine["items"][0]
    assert mine["pagination"]["total"] == 1
    assert client.get(f"/api/automation/runs/{ana_run}", headers=luis).status_code == 404

    everything = client.get("/api/automation/runs", headers=boss).json
    assert everything["pagination"]["total"] == 2
    assert client.get("/api/automation/runs?mine=true", headers=boss).json["pagination"]["total"] == 0
    assert client.get("/api/automation/runs?status=failed", headers=boss).json["pagination"]["total"] == 0
    assert client.get("/api/automation/runs?workflow_id=w1", headers=boss).json["pagination"]["total"] == 2


def test_stale_runs_expire(app, n8n):
    old = AutomationRun(workflow_id="w1", workflow_name="Flujo w1", status="running", created_by=1,
                        created_at=utcnow() - timedelta(hours=7))
    fresh = AutomationRun(workflow_id="w1", workflow_name="Flujo w1", status="running", created_by=1)
    done = AutomationRun(workflow_id="w1", workflow_name="Flujo w1", status="succeeded", created_by=1,
                         created_at=utcnow() - timedelta(hours=7))
    db.session.add_all([old, fresh, done])
    db.session.commit()
    assert tasks.expire_stale.run() == {"expired": 1}
    assert db.session.get(AutomationRun, old.id).status == "failed"
    assert db.session.get(AutomationRun, fresh.id).status == "running"
    assert db.session.get(AutomationRun, done.id).status == "succeeded"


def test_routes_only_work_inside_the_automation_app(client, as_automation, n8n):
    headers = {**as_automation("admin"), "X-App-Code": "operations"}
    assert client.get("/api/automation/runs", headers=headers).status_code in (401, 403)
