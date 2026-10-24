"""Buscador (Capítulo 13): filtros, sincronización, búsqueda con permisos y plan B."""
import io
from datetime import datetime, timedelta, timezone

from conftest import uid

from app.extensions import db
from app.models import Document, Opportunity, SearchQueryLog, utcnow
from app.search import filters as F
from app.search import sync
from app.search.extract import extract
from app.search.indexes import SPECS, cpv_prefixes

NOW = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)  # sábado


def _opp(client, h, **extra):
    body = {"title": "Desarrollo de portal web", "estimated_value_eur": "120000.00", "cpv_codes": ["72200000-7"],
            **extra}
    resp = client.post("/api/opportunities", json=body, headers=h)
    assert resp.status_code == 201, resp.json
    return resp.json


def _doc(client, h, text="Pliego de soporte técnico con ENS nivel medio.", name="pliego.txt", **form):
    resp = client.post("/api/documents", data={"file": (io.BytesIO(text.encode()), name), **form}, headers=h,
                       content_type="multipart/form-data")
    assert resp.status_code == 201, resp.json
    return resp.json


def _uid(kind):
    return SPECS[kind].uid


# ------------------------------------------------------------------ Piezas sueltas
def test_filters_escape_values_and_match_the_same_logic():
    evil = 'x" OR allowed_roles = "*'
    f = F.all_of(F.eq("doc_type", evil), F.any_of("status", ["a", "b"]), F.gte("v", 10), None)
    text = F.to_meili(f)
    assert text == '(doc_type = "x\\" OR allowed_roles = \\"*" AND status IN ["a", "b"] AND v >= 10)'
    assert F.all_of(None, None) is None and F.any_of("x", []) is None
    assert F.to_meili(F.eq("ok", True)) == "ok = true"
    doc = {"doc_type": "pliego", "status": "b", "v": 12, "roles": ["manager"]}
    assert not f.matches(doc)
    assert F.all_of(F.any_of("status", ["a", "b"]), F.gte("v", 10)).matches(doc)
    assert F.either(F.eq("roles", "*"), F.eq("roles", "manager")).matches(doc)
    assert not F.lte("v", None or 5).matches(doc)


def test_cpv_prefixes():
    assert cpv_prefixes(["72200000-7", "48"]) == ["48", "72", "722", "7220", "72200", "72200000"]


def test_extractor_understands_spanish_filters():
    e = extract("licitaciones de ciberseguridad superiores a 100.000 euros", NOW)
    assert e.value_min == 100000 and e.keywords == "ciberseguridad" and e.to_filters()["only_open"] is True
    assert extract("contratos de más de 1,5 millones", NOW).value_min == 1_500_000
    e = extract("oportunidades entre 50.000 y 200.000 € publicadas esta semana", NOW)
    assert (e.value_min, e.value_max) == (50000, 200000) and e.published_within_days == 6
    e = extract("concursos de software que cierran este mes", NOW)
    assert e.deadline_within_days == 7 and e.only_open is True and e.keywords == "software"
    e = extract("expedientes ganados cpv 72 en los próximos 30 días", NOW)
    assert e.cpv == ["72"] and e.deadline_within_days == 30 and "won" in e.statuses
    assert extract("oportunidades perdidas de software", NOW).to_filters()["only_open"] is False
    # Un plazo en días no es un importe
    assert extract("más de 30 días de plazo", NOW).value_min is None


# ------------------------------------------------------------------ Sincronización
def test_changes_reach_the_index_after_commit(client, as_role, meili):
    h = as_role("manager")
    c = client.post("/api/clients", json={"name": "Ayuntamiento de Ejemplo"}, headers=h).json
    opp = _opp(client, h, client_id=c["id"], code="2026/CONT-0387", description="Portal del ciudadano")
    assert sync.pending_counts()["opportunities"] == 1
    totals = sync.sync_pending()
    assert totals["opportunities"]["indexed"] == 1 and totals["clients"]["indexed"] == 1
    indexed = meili.docs(_uid("opportunities"))[opp["id"]]
    assert indexed["client_name"] == "Ayuntamiento de Ejemplo" and indexed["cpv_divisions"] == ["72"]
    assert meili.indexes[_uid("opportunities")]["settings"]["filterableAttributes"]
    assert sync.pending_counts() == {"opportunities": 0, "documents": 0, "clients": 0}

    # Cambio de nombre del cliente: sus oportunidades se reindexan
    client.patch(f"/api/clients/{c['id']}", json={"version": c["version"], "name": "Concello de Ejemplo"},
                 headers=h)
    sync.sync_pending()
    sync.sync_pending()
    assert meili.docs(_uid("opportunities"))[opp["id"]]["client_name"] == "Concello de Ejemplo"

    # Borrado lógico: sale del índice
    assert client.delete(f"/api/opportunities/{opp['id']}", headers=h).status_code == 204
    sync.sync_pending()
    assert opp["id"] not in meili.docs(_uid("opportunities"))


def test_rollback_does_not_mark_and_failures_keep_pending(app, client, as_role, meili):
    h = as_role("manager")
    o = Opportunity(title="Se deshace", owner_user_id=uid(h))
    db.session.add(o)
    db.session.flush()
    db.session.rollback()
    assert sync.pending_counts()["opportunities"] == 0

    _opp(client, h)
    meili.down = True
    try:
        sync.sync_pending()
    except Exception as exc:  # noqa: BLE001
        assert "no responde" in str(exc)
    assert sync.pending_counts()["opportunities"] == 1  # nada se pierde
    meili.down = False
    sync.sync_pending()
    assert sync.pending_counts()["opportunities"] == 0


def test_system_fields_only_reindex_when_indexed_fields_change(client, as_role, meili):
    h = as_role("manager")
    opp = _opp(client, h)
    sync.sync_pending()
    o = db.session.get(Opportunity, opp["id"])
    o.set_system_fields(scored_at=datetime(2026, 1, 1))
    db.session.commit()
    assert sync.pending_counts()["opportunities"] == 0
    o.set_system_fields(ai_summary="Resumen generado")
    db.session.commit()
    assert sync.pending_counts()["opportunities"] == 1
    sync.sync_pending()
    assert meili.docs(_uid("opportunities"))[opp["id"]]["ai_summary"] == "Resumen generado"


def test_rebuild_swaps_without_losing_service_and_consistency(client, as_role, meili):
    h = as_role("manager")
    for i in range(3):
        _opp(client, h, title=f"Oportunidad {i}", code=f"OP-{i}")
    sync.sync_pending()
    for kind in ("documents", "clients"):  # índices que aún no existen: se crean vacíos
        sync.rebuild(kind)
    assert sync.check_consistency() == []
    meili.docs(_uid("opportunities")).pop(next(iter(meili.docs(_uid("opportunities")))))
    assert sync.check_consistency() == ["opportunities"]
    result = sync.rebuild("opportunities")
    assert result["documents"] == 3
    assert len(meili.docs(_uid("opportunities"))) == 3
    assert f"{_uid('opportunities')}__rebuild" not in meili.indexes
    assert sync.check_consistency() == []
    status = {row["index"]: row for row in sync.status()}
    assert status["opportunities"]["mysql_count"] == 3 and status["opportunities"]["last_rebuild"]


# ------------------------------------------------------------------ Búsqueda de oportunidades
def _seed_opportunities(client, h):
    a = _opp(client, h, title="Servicio de ciberseguridad y SOC", code="EXP-1", estimated_value_eur="250000.00",
             deadline=(datetime.now(timezone.utc) + timedelta(days=10)).isoformat())
    b = _opp(client, h, title="Mantenimiento de <b>portal</b> web", code="EXP-2", estimated_value_eur="40000.00",
             cpv_codes=["48000000-8"])
    c = _opp(client, h, title="Ciberseguridad para hospitales", code="EXP-3", estimated_value_eur="90000.00",
             deadline=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    for o, days in ((a, 1), (b, 20), (c, 3)):
        db.session.get(Opportunity, o["id"]).published_at = utcnow() - timedelta(days=days)
    db.session.commit()
    sync.sync_pending()
    return a, b, c


def test_opportunity_search_filters_facets_and_highlight(client, as_role):
    h = as_role("manager")
    a, b, c = _seed_opportunities(client, h)
    url = "/api/search/opportunities"

    body = client.post(url, json={"q": "ciberseguridad"}, headers=h).json
    assert {i["id"] for i in body["items"]} == {a["id"], c["id"]} and body["engine"] == "meilisearch"
    assert body["items"][0]["highlight"]["title"].count("<mark>") == 1
    assert body["facets"]["status"] == {"detected": 2} and body["query_log_id"]

    assert [i["id"] for i in client.post(url, json={"value_min": 100000}, headers=h).json["items"]] == [a["id"]]
    assert [i["id"] for i in client.post(url, json={"cpv": ["48"]}, headers=h).json["items"]] == [b["id"]]
    # Abiertas: excluye la que ya cerró, incluye la que no tiene plazo
    ids = {i["id"] for i in client.post(url, json={"only_open": True}, headers=h).json["items"]}
    assert ids == {a["id"], b["id"]}
    ids = [i["id"] for i in client.post(url, json={"deadline_within_days": 30}, headers=h).json["items"]]
    assert ids == [a["id"]]
    ids = {i["id"] for i in client.post(url, json={"published_within_days": 7}, headers=h).json["items"]}
    assert ids == {a["id"], c["id"]}
    body = client.post(url, json={"sort": "-value", "per_page": 2}, headers=h).json
    assert [i["id"] for i in body["items"]] == [a["id"], c["id"]] and body["pagination"]["pages"] == 2

    # El HTML de un título nunca llega sin escapar
    hl = client.post(url, json={"q": "portal"}, headers=h).json["items"][0]["highlight"]["title"]
    assert "&lt;b&gt;" in hl and "<mark>portal</mark>" in hl

    assert client.post(url, json={"status": ["inventado"]}, headers=h).status_code == 422
    assert client.post(url, json={"value_min": 10, "value_max": 5}, headers=h).status_code == 422
    assert client.post(url, json={"filter": "1 = 1"}, headers=h).status_code == 422


def test_semantic_rerank_and_fallback_to_mysql(client, as_role, meili, ai):
    h = as_role("manager")
    a, b, c = _seed_opportunities(client, h)
    url = "/api/search/opportunities"
    body = client.post(url, json={"q": "ciberseguridad", "semantic": True}, headers=h).json
    assert body["reranked"] is True and all(i["score"] is not None for i in body["items"])
    ai.down = True
    body = client.post(url, json={"q": "ciberseguridad", "semantic": True}, headers=h).json
    assert body["reranked"] is False and body["notes"]

    meili.down = True
    body = client.post(url, json={"q": "ciberseguridad", "value_min": 100000}, headers=h).json
    assert body["engine"] == "mysql" and [i["id"] for i in body["items"]] == [a["id"]] and "facets" not in body
    quick = client.get("/api/search?q=EXP", headers=h).json
    assert quick["engine"] == "mysql" and quick["groups"][0]["total"] == 3


def test_deleted_rows_are_dropped_even_if_index_is_stale(client, as_role, meili):
    h = as_role("manager")
    a, _, _ = _seed_opportunities(client, h)
    o = db.session.get(Opportunity, a["id"])
    o.is_active = False
    db.session.commit()  # sin sincronizar: el índice aún la tiene
    ids = [i["id"] for i in client.post("/api/search/opportunities", json={"q": "servicio"}, headers=h).json["items"]]
    assert a["id"] not in ids


# ------------------------------------------------------------------ Documentos y búsqueda rápida
def test_document_search_respects_access_even_with_stale_index(client, as_role, meili):
    manager = as_role("manager")
    analyst = as_role("analyst")
    public = _doc(client, manager, "Pliego de mantenimiento del portal.", "publico.txt")
    secret = _doc(client, manager, "Pliego confidencial de mantenimiento.", "secreto.txt")
    client.patch(f"/api/documents/{secret['id']}", headers=manager,
                 json={"version": db.session.get(Document, secret["id"]).row_version, "allowed_roles": ["manager"]})
    sync.sync_pending()
    assert meili.docs(_uid("documents"))[secret["id"]]["allowed_roles"] == ["manager"]

    url = "/api/search/documents"
    ids = {i["id"] for i in client.post(url, json={"q": "mantenimiento"}, headers=analyst).json["items"]}
    assert ids == {public["id"]}
    assert {i["id"] for i in client.post(url, json={"q": "mantenimiento"}, headers=manager).json["items"]} == {
        public["id"], secret["id"]}
    # Índice desfasado: aunque diga "todos", el backend vuelve a comprobar en MySQL
    meili.docs(_uid("documents"))[secret["id"]]["allowed_roles"] = ["*"]
    ids = {i["id"] for i in client.post(url, json={"q": "mantenimiento"}, headers=analyst).json["items"]}
    assert ids == {public["id"]}
    # El filtro de acceso va dentro de la consulta a Meilisearch
    assert "allowed_roles" in F.to_meili(meili.searches[-1]["filter"])

    quick = client.get("/api/search?q=secreto", headers=analyst).json
    docs = next(g for g in quick["groups"] if g["type"] == "documents")
    assert docs["items"] == []
    meili.down = True
    ids = {i["id"] for i in client.post(url, json={"q": "secreto"}, headers=analyst).json["items"]}
    assert ids == set()


def test_quick_search_groups_by_permission(client, as_role):
    h = as_role("manager")
    client.post("/api/clients", json={"name": "Hospital General"}, headers=h)
    _opp(client, h, title="Hospital digital", code="HD-1")
    sync.sync_pending()
    body = client.get("/api/search?q=hospital", headers=h).json
    groups = {g["type"]: g for g in body["groups"]}
    assert groups["opportunities"]["items"][0]["subtitle"].startswith("HD-1")
    assert groups["clients"]["items"][0]["title"] == "Hospital General"
    assert client.get("/api/search", headers=h).status_code == 422


def test_click_counts_only_first_and_only_own(client, as_role):
    h = as_role("manager")
    other = as_role("analyst")
    _seed_opportunities(client, h)
    log_id = client.post("/api/search/opportunities", json={"q": "ciberseguridad"}, headers=h).json["query_log_id"]
    body = {"query_log_id": log_id, "kind": "opportunity", "object_id": 1, "position": 2}
    assert client.post("/api/search/click", json=body, headers=other).status_code == 404
    first = client.post("/api/search/click", json=body, headers=h).json["first_click_at"]
    assert client.post("/api/search/click", json={**body, "position": 5}, headers=h).json["first_click_at"] == first
    assert db.session.get(SearchQueryLog, log_id).click_position == 2


def test_quick_reformulation_is_detected(client, as_role):
    h = as_role("manager")
    _seed_opportunities(client, h)
    url = "/api/search/opportunities"
    first = client.post(url, json={"q": "ciberseguridad"}, headers=h).json["query_log_id"]
    client.post(url, json={"q": "seguridad hospitales"}, headers=h)
    assert db.session.get(SearchQueryLog, first).reformulated is True


def test_search_tasks(client, as_role, meili):
    from app.tasks import search as tasks

    h = as_role("manager")
    _opp(client, h)
    assert tasks.sync_pending.apply().get()["opportunities"]["indexed"] == 1
    # La primera revisión crea los índices que faltan; después solo el que no cuadra
    assert tasks.check_consistency.apply().get() == {"rebuild": ["documents", "clients"]}
    meili.docs(_uid("opportunities")).clear()
    assert tasks.check_consistency.apply().get() == {"rebuild": ["opportunities"]}
    assert len(meili.docs(_uid("opportunities"))) == 1  # la reconstrucción se ejecutó (modo eager)
    meili.down = True
    assert "error" in tasks.check_consistency.apply().get()
    old = SearchQueryLog(channel="opportunities", query_text="viejo", query_hash="x",
                         created_at=utcnow() - timedelta(days=400))
    db.session.add(old)
    db.session.commit()
    assert tasks.cleanup_query_log.apply().get() == {"deleted": 1}
