"""Portal Low-Code, fase L3 (ADR-020): taller, comprobaciones, revisión y publicación."""
import copy
import json
from pathlib import Path

import pytest

from app.extensions import db
from app.models import AutomationEntry
from app.services import automation_checks as checks
import test_automation_runs as runs

# Mismos fixtures que las ejecuciones: n8n falso y personas con rol en la app automation
n8n = runs.n8n
as_automation = runs.as_automation
workflow = runs.workflow

TEMPLATES = Path(__file__).resolve().parents[2] / "automations"


def good_workflow(wid="w1"):
    raw = workflow(wid)
    raw["nodes"][0]["parameters"]["authentication"] = "headerAuth"
    raw["nodes"][1]["parameters"] = {
        "method": "POST", "url": "={{ $json.body.callback_url }}", "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "jsonBody": "={{ JSON.stringify({status: 'succeeded', result: {c: $json.body.input.cliente}}) }}",
    }
    raw["settings"] = {"errorWorkflow": "err1"}
    return raw


ENTRY = {"workflow_id": "w1", "title": "Aviso de oportunidad", "description": "Avisa por correo.",
         "category": "ciclo_comercial",
         "fields": [{"name": "cliente", "label": "Cliente", "type": "text", "required": True}]}


@pytest.fixture()
def good(n8n):
    n8n["workflows"]["w1"] = good_workflow()
    return n8n


def _create(client, headers, body=None):
    return client.post("/api/automation/entries", headers=headers, json=body or ENTRY)


# ---------------------------------------------------------------- Comprobaciones
def test_a_good_workflow_passes_every_check():
    assert checks.run_checks({**good_workflow(), "active": True}, ENTRY["fields"]) == []


@pytest.mark.parametrize("break_it, code", [
    (lambda w: w["nodes"][0]["parameters"].update(httpMethod="GET"), "webhook_post"),
    (lambda w: w["nodes"][0]["parameters"].pop("authentication"), "webhook_auth"),
    (lambda w: w["nodes"][1]["parameters"].pop("authentication"), "callback_auth"),
    (lambda w: w["nodes"].pop(1), "callback"),
    (lambda w: w["nodes"].append({"type": "n8n-nodes-base.executeCommand", "name": "x"}), "forbidden_node"),
    (lambda w: w["nodes"].append({"type": "@n8n/n8n-nodes-langchain.lmChatAnthropic", "name": "x"}), "direct_ai"),
    (lambda w: w["nodes"].append({"type": HTTP, "name": "x", "parameters": {"url": "https://api.openai.com/v1"}}),
     "direct_ai"),
    (lambda w: w["nodes"].append({"type": HTTP, "name": "x", "parameters": {
        "headers": {"value": "Bearer abcdefghijklmnopqrstuvwxyz123456"}}}), "secret"),
    (lambda w: w["nodes"].append({"type": HTTP, "name": "x", "parameters": {"q": "sk-ant-api03-abcdefghij"}}),
     "secret"),
])
def test_checks_find_blocking_problems(break_it, code):
    raw = {**good_workflow(), "active": True}
    break_it(raw)
    issues = checks.run_checks(raw, ENTRY["fields"])
    assert code in {i["code"] for i in issues if i["level"] == "error"}
    assert "abcdefghij" not in json.dumps(issues)  # nunca se devuelve el texto encontrado


HTTP = "n8n-nodes-base.httpRequest"


def test_checks_warn_without_blocking():
    raw = {**good_workflow(), "active": False}
    raw.pop("settings")
    issues = checks.run_checks(raw, [{"name": "otro", "label": "Otro", "type": "text"}])
    assert {i["code"] for i in issues} == {"inactive", "error_workflow", "input_undeclared", "input_unused"}
    assert not checks.has_errors(issues)
    assert checks.input_names(raw) == ["cliente"]


def test_disabled_nodes_are_ignored():
    raw = {**good_workflow(), "active": True}
    raw["nodes"].append({"type": "n8n-nodes-base.executeCommand", "name": "x", "disabled": True})
    assert checks.run_checks(raw) == []


@pytest.mark.parametrize("path", sorted(TEMPLATES.rglob("*.json")), ids=lambda p: p.name)
def test_repository_templates_pass_the_checks(path):
    """Las de ``entradas/`` son flujos de entrada (caso P2) y la de ``errores/`` el flujo de errores
    común (L4): entregan a PLATIA, no se lanzan. Todas las demás usan el flujo de errores."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    kind = {"entradas": "inbound", "errores": "error"}.get(path.parent.name, "launch")
    issues = checks.run_checks({**raw, "active": True}, kind=kind)
    assert [i for i in issues if i["level"] == "error"] == []
    assert "error_workflow" not in [i["code"] for i in issues]


def test_error_workflow_checks():
    raw = json.loads((TEMPLATES / "errores" / "platia-flujo-de-errores.json").read_text(encoding="utf-8"))
    raw["active"] = True
    assert checks.run_checks(raw, kind="error") == []
    trigger = next(n for n in raw["nodes"] if n["type"] == checks.ERROR_TRIGGER)
    raw["nodes"].remove(trigger)
    assert [i["code"] for i in checks.run_checks(raw, kind="error")] == ["error_trigger"]
    # Entregar en la ruta de solicitudes no vale para los fallos
    raw["nodes"].append(trigger)
    raw["nodes"][0]["parameters"]["url"] = "http://backend:5000/api/leads/inbound"
    assert "inbound_target" in [i["code"] for i in checks.run_checks(raw, kind="error")]


def test_inbound_workflows_must_deliver_with_the_key():
    raw = json.loads((TEMPLATES / "entradas" / "p2-solicitudes-formulario-web.json").read_text(encoding="utf-8"))
    raw["active"] = True
    assert not checks.has_errors(checks.run_checks(raw, kind="inbound"))
    # Un flujo de entrada no necesita Webhook ni respuesta a callback_url, pero sí la clave
    deliver = next(n for n in raw["nodes"] if n["name"] == "Entregar a PLATIA")
    deliver["parameters"]["authentication"] = "none"
    assert [i["code"] for i in checks.run_checks(raw, kind="inbound") if i["level"] == "error"] == ["inbound_auth"]
    raw["nodes"].remove(deliver)
    assert [i["code"] for i in checks.run_checks(raw, kind="inbound") if i["level"] == "error"] == ["inbound_target"]
    # Las reglas comunes siguen valiendo
    raw["nodes"].append({"type": "@n8n/n8n-nodes-langchain.lmChatAnthropic", "name": "IA"})
    assert "direct_ai" in [i["code"] for i in checks.run_checks(raw, kind="inbound")]


def test_there_are_templates():
    assert len(list(TEMPLATES.rglob("*.json"))) >= 3


# ---------------------------------------------------------------- Taller
def test_full_cycle_from_draft_to_published(client, as_automation, good):
    builder = as_automation("builder")
    admin = as_automation("admin")
    user = as_automation("user")

    created = _create(client, builder)
    assert created.status_code == 201, created.json
    entry = created.json
    assert entry["status"] == "draft" and entry["version"] == 1
    assert client.get("/api/automation/catalog", headers=user).json["items"] == []

    detail = client.get(f"/api/automation/entries/{entry['id']}", headers=builder).json
    assert detail["input_names"] == ["cliente"]

    sent = client.post(f"/api/automation/entries/{entry['id']}/submit", headers=builder,
                       json={"version": entry["version"]})
    assert sent.status_code == 200, sent.json
    assert sent.json["status"] == "in_review" and sent.json["checks"] == []

    # Quien construye no publica
    assert client.post(f"/api/automation/entries/{entry['id']}/review", headers=builder,
                       json={"version": sent.json["version"], "decision": "approve"}).status_code == 403
    done = client.post(f"/api/automation/entries/{entry['id']}/review", headers=admin,
                       json={"version": sent.json["version"], "decision": "approve", "note": "Revisado"})
    assert done.status_code == 200, done.json
    assert done.json["status"] == "published" and done.json["published_at"]

    catalog = client.get("/api/automation/catalog", headers=user).json
    assert [(i["title"], i["launchable"]) for i in catalog["items"]] == [("Aviso de oportunidad", True)]
    assert "workflow_id" not in catalog["items"][0]
    status = client.get("/api/automation/status", headers=user).json
    assert status["published"] == 1 and status["active"] == 1

    run = client.post("/api/automation/runs", headers=user,
                      json={"entry_id": entry["id"], "input": {"cliente": "Ayto."}})
    assert run.status_code == 202

    retired = client.post(f"/api/automation/entries/{entry['id']}/retire", headers=admin,
                          json={"version": done.json["version"]})
    assert retired.json["status"] == "retired"
    assert client.get("/api/automation/catalog", headers=user).json["items"] == []


def test_submit_is_refused_with_blocking_checks_and_keeps_them(client, as_automation, n8n):
    builder = as_automation("builder")
    entry = _create(client, builder).json  # el flujo de base no pide clave en el webhook
    resp = client.post(f"/api/automation/entries/{entry['id']}/submit", headers=builder,
                       json={"version": entry["version"]})
    assert resp.status_code == 422
    detail = client.get(f"/api/automation/entries/{entry['id']}", headers=builder).json
    assert detail["status"] == "draft"
    assert "webhook_auth" in {c["code"] for c in detail["checks"]}


def test_review_rechecks_the_workflow(client, as_automation, good):
    builder, admin = as_automation("builder"), as_automation("admin")
    entry = _create(client, builder).json
    sent = client.post(f"/api/automation/entries/{entry['id']}/submit", headers=builder,
                       json={"version": entry["version"]}).json
    good["workflows"]["w1"]["nodes"][0]["parameters"].pop("authentication")  # alguien lo cambia en n8n
    resp = client.post(f"/api/automation/entries/{entry['id']}/review", headers=admin,
                       json={"version": sent["version"], "decision": "approve"})
    assert resp.status_code == 422
    assert db.session.get(AutomationEntry, entry["id"]).status == "in_review"


def test_reject_returns_to_draft_with_a_note(client, as_automation, good):
    builder, admin = as_automation("builder"), as_automation("admin")
    entry = _create(client, builder).json
    sent = client.post(f"/api/automation/entries/{entry['id']}/submit", headers=builder,
                       json={"version": entry["version"]}).json
    resp = client.post(f"/api/automation/entries/{entry['id']}/review", headers=admin,
                       json={"version": sent["version"], "decision": "reject", "note": "Falta la descripción"})
    assert resp.json["status"] == "draft" and resp.json["review_note"] == "Falta la descripción"


def test_edit_rules(client, as_automation, good):
    builder = as_automation("builder")
    entry = _create(client, builder).json
    url = f"/api/automation/entries/{entry['id']}"
    ok = client.patch(url, headers=builder, json={"version": entry["version"], "title": "Nuevo título",
                                                  "fields": []})
    assert ok.status_code == 200 and ok.json["title"] == "Nuevo título" and ok.json["fields"] == []
    assert client.patch(url, headers=builder, json={"version": entry["version"], "title": "Otro"}).status_code == 409
    sent = client.post(f"{url}/submit", headers=builder, json={"version": ok.json["version"]}).json
    assert client.patch(url, headers=builder, json={"version": sent["version"], "title": "Otro"}).status_code == 422


@pytest.mark.parametrize("change", [
    {"workflow_id": "nada"},
    {"fields": [{"name": "a", "label": "A"}, {"name": "a", "label": "B"}]},
    {"fields": [{"name": "a", "label": "A", "type": "select"}]},
    {"fields": [{"name": "a", "label": "A", "options": ["x"]}]},
    {"fields": [{"name": "mal nombre", "label": "A"}]},
    {"category": "otra"},
    {"title": "x"},
])
def test_entry_validation(client, as_automation, good, change):
    assert _create(client, as_automation("builder"), {**ENTRY, **change}).status_code == 422


def test_one_entry_per_workflow(client, as_automation, good):
    builder = as_automation("builder")
    _create(client, builder)
    resp = _create(client, builder)
    assert resp.status_code == 409
    listed = client.get("/api/automation/workflows", headers=builder).json["items"]
    assert listed[0]["entry_id"] is not None


def test_workshop_needs_build_permission(client, as_automation, good):
    user = as_automation("user")
    assert client.get("/api/automation/entries", headers=user).status_code == 403
    assert _create(client, user).status_code == 403


def test_list_entries_by_status(client, as_automation, good):
    builder = as_automation("builder")
    _create(client, builder)
    assert client.get("/api/automation/entries?status=draft", headers=builder).json["pagination"]["total"] == 1
    assert client.get("/api/automation/entries?status=published", headers=builder).json["pagination"]["total"] == 0


def test_n8n_down_in_the_workshop(client, as_automation, good):
    import requests

    good["get_error"] = requests.ConnectionError("caído")
    resp = _create(client, as_automation("builder"))
    assert resp.status_code == 422 and "n8n" in resp.json["error"]


def test_good_workflow_fixture_is_not_shared():
    a, b = good_workflow(), good_workflow()
    a["nodes"].pop()
    assert len(b["nodes"]) == 2 and copy.deepcopy(b) == b
