"""Cuadro de mando de negocio y historial de estados (fase 6b)."""
from datetime import datetime

from app.extensions import db
from app.models import OpportunityStatusChange
from app.services.analytics import month_keys, period_start


def _analytics(make_user, login, role="viewer", email="bi@example.com"):
    make_user(email, roles={"analytics": role})
    return {**login(email), "X-App-Code": "analytics"}


def _move(client, headers, opp, *statuses, comment=None):
    for status in statuses:
        body = {"status": status, "version": opp["version"]}
        if status in ("lost", "discarded"):
            body["comment"] = comment or "Precio"
        resp = client.post(f"/api/opportunities/{opp['id']}/status", json=body, headers=headers)
        assert resp.status_code == 200, resp.json
        opp = resp.json
    return opp


def test_status_changes_are_recorded_with_who_and_when(client, as_role):
    manager = as_role("manager")
    opp = client.post("/api/opportunities", json={"title": "SOC 24x7"}, headers=manager).json
    _move(client, manager, opp, "qualifying", "qualified")
    rows = db.session.scalars(db.select(OpportunityStatusChange).filter_by(opportunity_id=opp["id"])
                              .order_by(OpportunityStatusChange.id)).all()
    assert [(r.from_status, r.to_status) for r in rows] == [(None, "detected"), ("detected", "qualifying"),
                                                            ("qualifying", "qualified")]
    assert all(r.created_by == int(manager["X-User-Id"]) for r in rows)


def test_overview_kpis_funnel_and_breakdowns(client, as_role, make_user, login):
    manager = as_role("manager")
    won = client.post("/api/opportunities", json={"title": "Ganada", "estimated_value_eur": "100000",
                                                  "service_line": "cyber", "sector": "Público"},
                      headers=manager).json
    path = ("qualifying", "qualified", "go_no_go", "preparing_proposal", "proposal_review", "proposal_sent")
    _move(client, manager, won, *path, "won")
    lost = client.post("/api/opportunities", json={"title": "Perdida", "estimated_value_eur": "50000",
                                                   "service_line": "cyber", "sector": "Público"},
                       headers=manager).json
    _move(client, manager, lost, *path, "lost")
    open_ = client.post("/api/opportunities", json={"title": "Abierta", "estimated_value_eur": "20000",
                                                    "probability": 50, "service_line": "data"},
                        headers=manager).json
    assert open_["status"] == "detected"

    headers = _analytics(make_user, login)
    resp = client.get("/api/analytics/overview?months=3", headers=headers)
    assert resp.status_code == 200, resp.json
    data = resp.json
    kpis = data["kpis"]
    assert kpis["open_count"] == 1 and kpis["pipeline_eur"] == "20000.00"
    assert kpis["weighted_pipeline_eur"] == "10000.00"
    assert kpis["won_count"] == 1 and kpis["won_eur"] == "100000.00" and kpis["lost_count"] == 1
    assert kpis["win_rate"] == 0.5 and kpis["new_count"] == 3

    funnel = {f["phase"]: f for f in data["funnel"]}
    # Las tres empezaron; dos llegaron a enviar propuesta (F4); solo una se ganó
    assert [funnel[p]["reached"] for p in ("F1", "F2", "F3", "F4", "F5")] == [3, 2, 2, 2, 1]
    assert funnel["F1"]["open_count"] == 1

    this_month = data["monthly"][-1]
    assert this_month["new_count"] == 3 and this_month["won_count"] == 1 and this_month["lost_count"] == 1
    assert len(data["monthly"]) == 3

    lines = {g["key"]: g for g in data["by_service_line"]}
    assert lines["cyber"]["win_rate"] == 0.5 and lines["data"]["pipeline_eur"] == "20000.00"
    assert lines["cyber"]["label"] == "Ciberseguridad"
    assert {(c["sector"], c["service_line"]) for c in data["heatmap"]} == {("Sin indicar", "data")}

    filtered = client.get("/api/analytics/overview?service_line=data", headers=headers).json
    assert filtered["kpis"]["new_count"] == 1 and filtered["kpis"]["won_count"] == 0


def test_analytics_needs_its_own_app_and_permission(client, as_role, make_user, login):
    manager = as_role("manager")  # operaciones: no basta
    assert client.get("/api/analytics/overview", headers=manager).status_code == 403
    assert client.get("/api/analytics/overview", headers={**manager, "X-App-Code": "analytics"}).status_code == 403
    headers = _analytics(make_user, login)
    assert client.get("/api/analytics/ai", headers=headers).status_code == 200
    assert client.get("/api/analytics/overview?months=x", headers=headers).status_code == 422


def test_ai_value_by_month(client, make_user, login):
    headers = _analytics(make_user, login)
    data = client.get("/api/analytics/ai?months=2", headers=headers).json
    assert len(data["monthly"]) == 2 and data["roi"]["total"]["tasks"] == 0


def test_month_helpers_cross_the_year():
    now = datetime(2027, 2, 10)
    start = period_start(4, now)
    assert start == datetime(2026, 11, 1)
    assert month_keys(start, now) == ["2026-11", "2026-12", "2027-01", "2027-02"]
