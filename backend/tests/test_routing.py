"""Reparto de oportunidades al responsable (caso P18 del portal Low-Code, ADR-020)."""
from datetime import timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Notification, Opportunity, OpportunityRoutingRule, utcnow
from app.services import routing
from app.tasks import alerts

URL = "/api/opportunities/routing-rules"


def rule_body(owner: int, **extra):
    return {"name": "Ciber grandes", "owner_user_id": owner, **extra}


def opp(**values):
    o = Opportunity(**{"title": "Servicio SOC", "status": "detected", "source": "ted", **values})
    db.session.add(o)
    db.session.commit()
    return o


def test_rules_need_manage_and_a_valid_owner(client, as_role):
    manager, analyst, viewer = as_role("manager"), as_role("analyst"), as_role("viewer")
    analyst_id = int(analyst["X-User-Id"])
    assert client.get(URL, headers=analyst).status_code == 403
    assert client.post(URL, json=rule_body(analyst_id), headers=analyst).status_code == 403
    page = client.get(URL, headers=manager).json
    assert page["items"] == [] and analyst_id in [c["id"] for c in page["candidates"]]
    # Quien solo lee no puede ser responsable
    assert client.post(URL, json=rule_body(int(viewer["X-User-Id"])), headers=manager).status_code == 422
    assert client.post(URL, json=rule_body(analyst_id, min_value_eur=10, max_value_eur=5),
                       headers=manager).status_code == 422
    resp = client.post(URL, json=rule_body(analyst_id, sources=["ted"], sectors=[]), headers=manager)
    assert resp.status_code == 201, resp.json
    assert resp.json["sectors"] == [] and resp.json["owner_name"] == "analyst"
    rule_id, version = resp.json["id"], resp.json["version"]
    body = {**rule_body(analyst_id, position=5, is_enabled=False), "version": version}
    upd = client.put(f"{URL}/{rule_id}", json=body, headers=manager)
    assert upd.status_code == 200 and upd.json["position"] == 5 and not upd.json["is_enabled"]
    assert client.put(f"{URL}/{rule_id}", json=body, headers=manager).status_code == 409
    assert client.delete(f"{URL}/{rule_id}", headers=manager).status_code == 204
    assert client.get(URL, headers=manager).json["items"] == []


def test_matching_criteria(seeded):
    rule = OpportunityRoutingRule(name="r", owner_user_id=1, sources=["TED"], service_lines=["ciber"],
                                  min_value_eur=Decimal("100000"), max_days_to_deadline=30)
    now = utcnow()
    good = Opportunity(title="x", source="ted", service_line="ciber", estimated_value_eur=Decimal("150000"),
                       deadline=now + timedelta(days=10))
    assert routing.matches(rule, good, now)
    for change in ({"source": "buzon_pliegos"}, {"service_line": "cloud"}, {"estimated_value_eur": None},
                   {"estimated_value_eur": Decimal("50000")}, {"deadline": None},
                   {"deadline": now + timedelta(days=40)}):
        other = Opportunity(**{"title": "x", "source": "ted", "service_line": "ciber",
                               "estimated_value_eur": Decimal("150000"), "deadline": now + timedelta(days=10),
                               **change})
        assert not routing.matches(rule, other, now), change
    # Sin criterios, encaja con todo
    assert routing.matches(OpportunityRoutingRule(name="todo", owner_user_id=1), Opportunity(title="y"), now)


def test_first_matching_rule_assigns_and_notifies(seeded, make_user):
    ana = make_user("ana@example.com", roles={"operations": "analyst"})
    luis = make_user("luis@example.com", roles={"operations": "analyst"})
    gone = make_user("baja@example.com", roles={"operations": "analyst"})
    gone.is_active = False
    db.session.add_all([
        OpportunityRoutingRule(name="De baja", position=1, sources=["ted"], owner_user_id=gone.id),
        OpportunityRoutingRule(name="Apagada", position=2, is_enabled=False, owner_user_id=luis.id),
        OpportunityRoutingRule(name="TED", position=3, sources=["ted"], owner_user_id=ana.id),
        OpportunityRoutingRule(name="Resto", position=4, owner_user_id=luis.id),
    ])
    db.session.commit()
    o = opp()
    rule = routing.route(o)
    db.session.commit()
    assert rule.name == "TED" and o.owner_user_id == ana.id and o.extra_data["routing"]["rule_name"] == "TED"
    note = db.session.scalar(db.select(Notification).filter_by(user_id=ana.id))
    assert note.notification_type == "NEW_OPPORTUNITY" and note.link == f"/opportunities/{o.id}"
    # Con responsable no se reasigna
    assert routing.route(o) is None
    other = opp(title="Otra", source="buzon_pliegos")
    assert routing.route(other).name == "Resto" and other.owner_user_id == luis.id
    assert routing.route(opp(title="Ya en marcha", status="analyzing")) is None


def test_proactive_scan_routes_new_opportunities(seeded, make_user):
    ana = make_user("ana@example.com", roles={"operations": "analyst"})
    db.session.add(OpportunityRoutingRule(name="Todo TED", sources=["ted"], owner_user_id=ana.id))
    db.session.commit()
    o = opp()
    worked = Opportunity(title="En análisis", status="analyzing", source="ted")
    db.session.add(worked)
    db.session.commit()
    result = alerts.proactive_scan.apply().get()
    assert result["routed"] == 1
    assert db.session.get(Opportunity, o.id).owner_user_id == ana.id
    assert db.session.get(Opportunity, worked.id).owner_user_id is None
