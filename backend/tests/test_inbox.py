from conftest import uid

import pytest

from app.extensions import db
from app.models import FailedTask
from app.services.notifications import notify


def test_users_only_see_their_notifications(client, as_role):
    ana, luis = as_role("analyst", "ana@example.com"), as_role("viewer", "luis@example.com")
    mine = notify(uid(ana), "REPORT_READY", "Listo", link="/proposals/1")
    assert notify(uid(ana), "REPORT_READY", "Listo otra vez", link="/proposals/1") is None  # deduplicada
    theirs = notify(uid(luis), "SYSTEM", "Aviso")

    body = client.get("/api/notifications", headers=ana).json
    assert [n["id"] for n in body["items"]] == [mine.id]
    assert client.get("/api/notifications/unread-count", headers=ana).json == {"unread": 1}
    # La de otro usuario responde 404, no 403
    assert client.post(f"/api/notifications/{theirs.id}/read", headers=ana).status_code == 404
    resp = client.post(f"/api/notifications/{mine.id}/read", headers=ana)
    assert resp.status_code == 200 and resp.json["read_at"]
    assert client.get("/api/notifications?unread=true", headers=ana).json["items"] == []
    assert client.post("/api/notifications/read-all", headers=luis).json == {"updated": 1}
    # Leída, ya se puede volver a avisar del mismo recurso
    assert notify(uid(ana), "REPORT_READY", "Nuevo paquete", link="/proposals/1") is not None


def test_unknown_notification_type_is_rejected(seeded):
    with pytest.raises(ValueError):
        notify(1, "INVENTADA", "x")


def test_alerts_permissions(client, as_role):
    viewer, manager = as_role("viewer"), as_role("manager")
    assert client.get("/api/alerts?open=true", headers=viewer).status_code == 200
    assert client.post("/api/alerts/1/resolve", headers=viewer).status_code == 403
    assert client.post("/api/alerts/1/resolve", headers=manager).status_code == 404


def test_dead_letter_admin_endpoints(client, make_user, login):
    make_user("root@example.com", superadmin=True)
    h = {**login("root@example.com"), "X-App-Code": "admin"}
    failed = FailedTask(task_id="t1", task_name="tasks.sync.gdpr_cleanup", error_type="OperationalError",
                        task_args=[], task_kwargs={})
    evil = FailedTask(task_id="t2", task_name="os.system", error_type="X", task_args=["rm -rf /"])
    db.session.add_all([failed, evil])
    db.session.commit()
    body = client.get("/api/admin/tasks/failed?reviewed=false", headers=h).json
    assert body["pagination"]["total"] == 2
    resp = client.post(f"/api/admin/tasks/failed/{failed.id}/retry", headers=h)
    assert resp.status_code == 202 and resp.json["requeued_task_id"] and resp.json["reviewed"]
    # Nunca se reencola un nombre de tarea que no es nuestro
    assert client.post(f"/api/admin/tasks/failed/{evil.id}/retry", headers=h).status_code == 422
    assert client.post(f"/api/admin/tasks/failed/{evil.id}/review", headers=h).json["reviewed"]
    # Fuera de la app admin no existen
    ops = login("root@example.com")
    assert client.get("/api/admin/tasks/failed", headers=ops).status_code == 403
    assert client.get("/api/admin/tasks/queues", headers=h).json["queues"] == {}


def test_talent_profiles(client, as_role):
    manager, viewer = as_role("manager"), as_role("viewer")
    body = {"full_name": "Laura Gómez", "email": "laura@example.com", "family": "cyber",
            "seniority": "SENIOR", "years_experience": 9,
            "skills": [{"name": "ENS", "level": 5}, {"name": "SIEM", "level": 4}],
            "experiences": [{"company": "SOC Iberia", "role": "Analista SOC", "start_date": "2019-01-01",
                             "technologies": ["Splunk"]}]}
    resp = client.post("/api/talent/profiles", json=body, headers=manager)
    assert resp.status_code == 201, resp.json
    pid = resp.json["id"]
    listing = client.get("/api/talent/profiles?skill=siem&family=cyber", headers=viewer).json
    assert listing["pagination"]["total"] == 1
    assert "email" not in listing["items"][0]  # el listado no expone datos de contacto
    assert client.get(f"/api/talent/profiles/{pid}", headers=viewer).json["email"] == "laura@example.com"
    resp = client.patch(f"/api/talent/profiles/{pid}", json={"version": 1, "skills": [{"name": "SOAR"}]},
                        headers=manager)
    assert resp.json["skills"] == [{"name": "SOAR", "level": None, "years": None}]
    assert resp.json["version"] == 2
    bad = {**body, "experiences": [{"company": "X", "start_date": "2020-01-01", "end_date": "2019-01-01"}]}
    assert client.post("/api/talent/profiles", json=bad, headers=manager).status_code == 422
    assert client.post("/api/talent/profiles", json=body, headers=viewer).status_code == 403


def test_unknown_permission_fails_at_import():
    from app.security.context import require_permission
    from app.security.registry import UnknownPermissionError

    with pytest.raises(UnknownPermissionError):
        require_permission("exports", "read")
    with pytest.raises(UnknownPermissionError):
        require_permission("documents", "export")
