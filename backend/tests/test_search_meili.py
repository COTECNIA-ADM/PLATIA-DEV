"""Pruebas contra un Meilisearch de verdad (CI o local).

Se saltan si no hay ``MEILI_TEST_URL``. Comprueban lo que el falso no puede:
que la configuración de los índices es válida, que los filtros que genera el
backend tienen la sintaxis que espera Meilisearch (y que el escape impide la
inyección), los sinónimos, las palabras vacías y el intercambio de índices.

    docker run -d -p 7700:7700 -e MEILI_MASTER_KEY=clave-de-prueba-1234567890 getmeili/meilisearch:v1.54.3
    MEILI_TEST_URL=http://localhost:7700 MEILI_TEST_KEY=clave-de-prueba-1234567890 pytest tests/test_search_meili.py
"""
import io
import os
import time
import uuid

import pytest

from app.extensions import db
from app.models import Opportunity
from app.search import filters as F
from app.search import sync
from app.search.client import MeiliClient
from app.search.indexes import SPECS

pytestmark = pytest.mark.skipif(not os.environ.get("MEILI_TEST_URL"), reason="Sin Meilisearch de pruebas")


@pytest.fixture()
def real_meili(app):
    client = MeiliClient(os.environ["MEILI_TEST_URL"], os.environ.get("MEILI_TEST_KEY", ""), 10)
    app.extensions["search_client"] = client
    app.config["MEILI_INDEX_PREFIX"] = f"test_{uuid.uuid4().hex[:8]}_"  # índices propios de esta prueba
    yield client
    for spec in SPECS.values():
        for uid in (spec.uid, f"{spec.uid}__rebuild"):
            try:
                client.delete_index(uid)
            except Exception:  # noqa: BLE001
                pass


def _idle(client: MeiliClient, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = client._request("GET", "/tasks", params={"statuses": "enqueued,processing", "limit": 1})
        if not pending.get("results"):
            return
        time.sleep(0.1)
    raise AssertionError("Meilisearch no terminó de indexar")


def _sync(client):
    sync.sync_pending()
    _idle(client)


def _opp(client, h, **extra):
    resp = client.post("/api/opportunities", json={"title": "Portal web", **extra}, headers=h)
    assert resp.status_code == 201, resp.json
    return resp.json


def test_index_settings_filters_and_search(client, as_role, real_meili):
    h = as_role("manager")
    a = _opp(client, h, title="Servicio de ciberseguridad para el Ayuntamiento", code="2026/CONT-0387",
             estimated_value_eur="250000.00", cpv_codes=["72200000-7"])
    b = _opp(client, h, title="Mantenimiento de <script>alert(1)</script> portal", estimated_value_eur="40000.00",
             cpv_codes=["48000000-8"])
    _sync(real_meili)
    settings = real_meili._request("GET", f"/indexes/{SPECS['opportunities'].uid}/settings")
    assert "cpv_prefixes" in settings["filterableAttributes"]

    url = "/api/search/opportunities"
    body = client.post(url, json={"q": "ciberseguridad", "value_min": 100000, "cpv": ["72"], "only_open": True},
                       headers=h).json
    assert body["engine"] == "meilisearch" and [i["id"] for i in body["items"]] == [a["id"]]
    assert "<mark>" in body["items"][0]["highlight"]["title"] and body["facets"]["cpv_divisions"] == {"72": 1}
    # Sinónimo: "seguridad informática" encuentra "ciberseguridad"
    assert [i["id"] for i in client.post(url, json={"q": "seguridad informatica"}, headers=h).json["items"]] == [a["id"]]
    # Código exacto de expediente
    assert [i["id"] for i in client.post(url, json={"q": "2026/CONT-0387"}, headers=h).json["items"]][0] == a["id"]
    # El HTML de un título llega escapado
    hl = client.post(url, json={"q": "portal"}, headers=h).json["items"][0]["highlight"]["title"]
    assert "<script>" not in hl and "&lt;script&gt;" in hl
    assert client.post(url, json={"sort": "-value"}, headers=h).json["items"][0]["id"] == a["id"]
    assert b["id"] in [i["id"] for i in client.get("/api/search?q=mantenimiento", headers=h).json["groups"][0]["items"]]


def test_filter_injection_is_escaped(real_meili, app, client, as_role):
    h = as_role("manager")
    _opp(client, h)
    _sync(real_meili)
    evil = F.all_of(F.eq("status", 'x" OR status != "y'), F.gte("estimated_value_eur", 0))
    res = real_meili.search(SPECS["opportunities"].uid, {"q": ""}, evil)
    assert res["hits"] == []  # la comilla no cerró la cadena


def test_document_access_and_rebuild_swap(client, as_role, real_meili):
    manager = as_role("manager")
    analyst = as_role("analyst")
    for name, text in (("publico.txt", "Pliego de mantenimiento"), ("secreto.txt", "Pliego confidencial de mantenimiento")):
        resp = client.post("/api/documents", data={"file": (io.BytesIO(text.encode()), name)}, headers=manager,
                           content_type="multipart/form-data")
        assert resp.status_code == 201
        doc = resp.json
    current = client.get(f"/api/documents/{doc['id']}", headers=manager).json
    client.patch(f"/api/documents/{doc['id']}", headers=manager,
                 json={"version": current["version"], "allowed_roles": ["manager"]})
    _sync(real_meili)
    url = "/api/search/documents"
    assert len(client.post(url, json={"q": "mantenimiento"}, headers=analyst).json["items"]) == 1
    assert len(client.post(url, json={"q": "mantenimiento"}, headers=manager).json["items"]) == 2

    result = sync.rebuild("documents")
    assert result["documents"] == 2
    _idle(real_meili)
    assert real_meili.index_stats(f"{SPECS['documents'].uid}__rebuild") is None
    assert len(client.post(url, json={"q": "mantenimiento"}, headers=manager).json["items"]) == 2
    # Tras la reconstrucción, el registro cuadra con MySQL
    assert "documents" not in sync.check_consistency()
    assert db.session.scalar(db.select(db.func.count()).select_from(Opportunity)) == 0
