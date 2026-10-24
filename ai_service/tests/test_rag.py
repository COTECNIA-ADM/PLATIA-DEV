import time

from app.embeddings import HashEmbedder

from .conftest import API_HEADERS


def _index(client, ref_id, texts, **common):
    base = {"title": f"Doc {ref_id}", "doc_type": "requisitos", "owner_user_id": 1, "allowed_roles": ["*"],
            "is_current": True}
    base.update(common)
    resp = client.post("/v1/rag/index", headers=API_HEADERS, json={
        "collection": "documents", "ref_id": ref_id,
        "chunks": [{"text": t, "metadata": {"page": i + 1}} for i, t in enumerate(texts)],
        "common": base})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _search(client, query, **kw):
    body = {"collections": ["documents"], "query": query, "limit": 5}
    body.update(kw)
    resp = client.post("/v1/rag/search", json=body, headers=API_HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()["hits"]


def test_index_and_search(client):
    assert _index(client, 1, ["certificación ISO 27001 obligatoria", "plazo de ejecución doce meses"])["points"] == 2
    hits = _search(client, "certificación ISO 27001")
    assert hits[0]["ref_id"] == 1 and "ISO 27001" in hits[0]["text"]
    assert hits[0]["payload"]["page"] == 1 and hits[0]["payload"]["title"] == "Doc 1"


def test_reindex_replaces_points_without_duplicates(client):
    _index(client, 2, ["a uno", "b dos", "c tres"])
    _index(client, 2, ["solo uno"])
    assert client.post("/v1/rag/count", json={"collection": "documents", "ref_id": 2},
                       headers=API_HEADERS).json()["points"] == 1


def test_access_filter(client):
    _index(client, 3, ["informe confidencial de la cuenta"], owner_user_id=7, allowed_roles=["director"])
    _index(client, 4, ["informe abierto de la cuenta"], owner_user_id=8, allowed_roles=["*"])
    seen = {h["ref_id"] for h in _search(client, "informe de la cuenta", access={"user_id": 9, "roles": ["analyst"]})}
    assert seen == {4}
    seen = {h["ref_id"] for h in _search(client, "informe de la cuenta", access={"user_id": 7, "roles": []})}
    assert seen == {3, 4}
    seen = {h["ref_id"] for h in _search(client, "informe", access={"user_id": 9, "roles": ["director"]})}
    assert 3 in seen
    seen = {h["ref_id"] for h in _search(client, "informe de la cuenta", access={"bypass": True})}
    assert seen == {3, 4}


def test_only_current_versions_and_payload_update(client):
    _index(client, 5, ["versión antigua del pliego"])
    client.post("/v1/rag/payload", headers=API_HEADERS,
                json={"collection": "documents", "ref_id": 5, "payload": {"is_current": False}})
    assert all(h["ref_id"] != 5 for h in _search(client, "versión antigua del pliego"))
    assert any(h["ref_id"] == 5 for h in _search(client, "versión antigua del pliego", only_current=False))


def test_payload_update_rejects_unknown_fields(client):
    resp = client.post("/v1/rag/payload", headers=API_HEADERS,
                       json={"collection": "documents", "ref_id": 5, "payload": {"text": "x"}})
    assert resp.status_code == 422


def test_not_expired_filter(client):
    resp = client.post("/v1/rag/index", headers=API_HEADERS, json={
        "collection": "opportunities", "ref_id": 10, "chunks": [{"text": "servicio de ciberseguridad caducado"}],
        "common": {"is_current": True, "allowed_roles": ["*"], "expires_ts": int(time.time()) - 10}})
    assert resp.status_code == 200
    client.post("/v1/rag/index", headers=API_HEADERS, json={
        "collection": "opportunities", "ref_id": 11, "chunks": [{"text": "servicio de ciberseguridad vigente"}],
        "common": {"is_current": True, "allowed_roles": ["*"], "expires_ts": None}})
    hits = client.post("/v1/rag/search", headers=API_HEADERS, json={
        "collections": ["opportunities"], "query": "servicio de ciberseguridad", "not_expired": True}).json()["hits"]
    assert {h["ref_id"] for h in hits} == {11}


def test_delete_and_unknown_collection(client):
    _index(client, 6, ["borrame"])
    client.post("/v1/rag/delete", json={"collection": "documents", "ref_id": 6}, headers=API_HEADERS)
    assert client.post("/v1/rag/count", json={"collection": "documents", "ref_id": 6},
                       headers=API_HEADERS).json()["points"] == 0
    resp = client.post("/v1/rag/index", headers=API_HEADERS,
                       json={"collection": "otra", "ref_id": 1, "chunks": [{"text": "x"}]})
    assert resp.status_code == 422


def test_collections_and_refs(client):
    _index(client, 12, ["uno", "dos"])
    stats = client.get("/v1/rag/collections", headers=API_HEADERS).json()
    docs = next(c for c in stats["collections"] if c["collection"] == "documents")
    assert docs["points"] == 2 and docs["physical"].endswith("hash384")
    refs = client.get("/v1/rag/collections/documents/refs", headers=API_HEADERS).json()["refs"]
    assert refs == {"12": 2}


def test_similarity(client):
    resp = client.post("/v1/similarity", headers=API_HEADERS, json={
        "queries": ["auditoría de ciberseguridad y pentesting"],
        "candidates": ["ciberseguridad pentesting auditoría", "suministro de mobiliario de oficina"]})
    scores = resp.json()["scores"][0]
    assert scores[0] > scores[1]


def test_hash_embedder_is_normalized():
    vec = HashEmbedder().embed(["hola mundo hola"])[0]
    assert abs(sum(v * v for v in vec) - 1) < 1e-9
