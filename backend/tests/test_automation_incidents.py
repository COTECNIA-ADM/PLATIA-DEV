"""Portal Low-Code, fase L4 (ADR-020): incidencias del flujo de errores común y salud por flujo."""
from datetime import timedelta

import pytest

import test_automation_runs as runs
from app.extensions import db
from app.models import AutomationIncident, AutomationRun, Notification, utcnow
from app.services import automation_incidents as incidents

KEY = {"X-Platia-Integration-Key": "test-callback-key"}
FAILURE = {"workflow_id": "w1", "workflow_name": "Flujo w1", "execution_id": "77", "mode": "webhook",
           "node": "Enviar correo", "message": "Connection refused"}
as_automation = runs.as_automation


@pytest.fixture()
def execution(monkeypatch):
    """API de ejecuciones de n8n falsa: ``state['body']`` es lo que recibió el Webhook."""
    state = {"body": None, "workflow_id": "w1", "status": 200, "calls": []}

    class Resp:
        def __init__(self):
            self.status_code = state["status"]

        def json(self):
            node_out = [{"json": {"headers": {}, "body": state["body"]}}] if state["body"] else []
            return {"id": "77", "workflowId": state["workflow_id"],
                    "data": {"resultData": {"runData": {"Webhook PLATIA": [{"data": {"main": [node_out]}}]}}}}

    def fake_get(url, params=None, headers=None, timeout=None, allow_redirects=True):
        state["calls"].append({"url": url, "params": params})
        return Resp()

    monkeypatch.setattr(incidents.requests, "get", fake_get)
    return state


def send(client, body=None, headers=KEY):
    return client.post("/api/automation/incidents/inbound", json=FAILURE if body is None else body, headers=headers)


def open_run(wid="w1", status="running") -> int:
    run = AutomationRun(workflow_id=wid, workflow_name=f"Flujo {wid}", status=status, created_by=1,
                        started_at=utcnow())
    db.session.add(run)
    db.session.commit()
    return run.id


def test_inbound_needs_the_integration_key(client):
    assert send(client, headers={}).status_code == 401
    assert send(client, headers={"X-Platia-Integration-Key": "otra"}).status_code == 401
    assert send(client, {**FAILURE, "workflow_id": "w-1"}).status_code == 422
    assert send(client, {**FAILURE, "data": {"x": 1}}).status_code == 422


def test_failure_closes_the_platia_run_and_notifies_admins(client, as_automation, execution):
    as_automation("admin")
    as_automation("builder")
    run_id = open_run()
    execution["body"] = {"run_id": run_id, "callback_url": "http://backend/api/automation/runs/1/callback",
                         "input": {"correo": "privado@example.com"}}
    resp = send(client, {**FAILURE, "message": "x" * 3000})
    assert resp.status_code == 201, resp.json
    assert resp.json["run_id"] == run_id
    assert execution["calls"][0]["url"].endswith("/executions/77")
    run = db.session.get(AutomationRun, run_id)
    assert run.status == "failed" and "Enviar correo" in run.error and "privado" not in run.error
    incident = db.session.get(AutomationIncident, resp.json["id"])
    assert len(incident.message) == 500 and incident.status == "open"
    # Avisa solo a quien administra (y a los superadmin), una vez por flujo hasta que lo lea
    notes = db.session.scalars(db.select(Notification).where(
        Notification.notification_type == "AUTOMATION_FAILED")).all()
    assert len(notes) == 1 and notes[0].link == "/automation/monitor?workflow_id=w1"
    assert db.session.scalars(db.select(Notification.user_id)).all() == [notes[0].user_id]
    send(client, {**FAILURE, "execution_id": "78"})
    assert db.session.scalar(db.select(db.func.count()).select_from(Notification)) == 1


def test_repeated_delivery_is_idempotent(client, execution):
    first = send(client)
    again = send(client)
    assert again.status_code == 200 and again.json["duplicate"] and again.json["id"] == first.json["id"]
    assert db.session.scalar(db.select(db.func.count()).select_from(AutomationIncident)) == 1


def test_execution_of_another_workflow_or_unreadable_is_not_linked(client, execution):
    run_id = open_run()
    execution["body"] = {"run_id": run_id, "callback_url": "x"}
    execution["workflow_id"] = "otro"
    assert send(client).json["run_id"] is None
    assert db.session.get(AutomationRun, run_id).status == "running"
    execution["workflow_id"], execution["status"] = "w1", 500
    assert send(client, {**FAILURE, "execution_id": "79"}).json["run_id"] is None
    # Un fallo sin ejecución (p. ej. de un disparador) también se guarda
    assert send(client, {**FAILURE, "execution_id": None}).status_code == 201


def test_closed_run_is_linked_but_not_changed(client, execution):
    run_id = open_run(status="succeeded")
    execution["body"] = {"run_id": run_id, "callback_url": "x"}
    assert send(client).json["run_id"] == run_id
    assert db.session.get(AutomationRun, run_id).status == "succeeded"


def test_list_and_resolve_permissions(client, as_automation, execution):
    builder, admin, user = as_automation("builder"), as_automation("admin"), as_automation("user")
    incident_id = send(client).json["id"]
    assert client.get("/api/automation/incidents", headers=user).status_code == 403
    page = client.get("/api/automation/incidents?status=open&workflow_id=w1", headers=builder).json
    assert [i["id"] for i in page["items"]] == [incident_id]
    body = {"version": 1, "note": "Servidor de correo caído; ya responde."}
    assert client.post(f"/api/automation/incidents/{incident_id}/resolve", json=body,
                       headers=builder).status_code == 403
    resp = client.post(f"/api/automation/incidents/{incident_id}/resolve", json=body, headers=admin)
    assert resp.status_code == 200 and resp.json["status"] == "resolved"
    assert client.post(f"/api/automation/incidents/{incident_id}/resolve", json={**body, "version": 2},
                       headers=admin).status_code == 409
    assert client.get("/api/automation/incidents?status=open", headers=builder).json["items"] == []
    # Fuera de la app automation no existe
    other = {k: v for k, v in builder.items() if k != "X-App-Code"}
    assert client.get("/api/automation/incidents", headers=other).status_code == 403


def test_health_summarises_runs_and_open_incidents(client, as_automation, execution):
    builder = as_automation("builder")
    now = utcnow()
    for status, seconds in (("succeeded", 10), ("succeeded", 30), ("failed", None), ("running", None)):
        db.session.add(AutomationRun(workflow_id="w1", workflow_name="Flujo w1", status=status, created_by=1,
                                     started_at=now - timedelta(seconds=seconds or 5),
                                     finished_at=now if seconds else None))
    db.session.add(AutomationRun(workflow_id="w1", workflow_name="Flujo w1", status="failed", created_by=1,
                                 created_at=now - timedelta(days=60)))
    db.session.commit()
    send(client, {**FAILURE, "workflow_id": "w2", "workflow_name": "Solo falla"})
    data = client.get("/api/automation/health?days=30", headers=builder).json
    by_id = {i["workflow_id"]: i for i in data["items"]}
    assert by_id["w1"]["runs"] == 4 and by_id["w1"]["succeeded"] == 2 and by_id["w1"]["failed"] == 1
    assert by_id["w1"]["open"] == 1 and by_id["w1"]["success_rate"] == 50 and by_id["w1"]["avg_seconds"] == 20
    assert by_id["w2"]["runs"] == 0 and by_id["w2"]["open_incidents"] == 1
    assert data["items"][0]["workflow_id"] == "w2" and data["open_incidents"] == 1
    assert client.get("/api/automation/health?days=abc", headers=builder).json["days"] == 30
    assert client.get("/api/automation/health", headers=as_automation("user")).status_code == 403
