"""Colecciones de Qdrant para RAG (Capítulo 12).

Cada punto lleva en el *payload* el control de acceso (propietario y roles), si
es la versión vigente del documento y, para oportunidades, la fecha de cierre.
Así el filtro de acceso se aplica dentro de la propia búsqueda vectorial y una
persona nunca recibe fragmentos de documentos que no puede abrir.

Los identificadores de punto son deterministas (``uuid5`` de colección, registro
y número de fragmento): reindexar un documento sobrescribe sus puntos en lugar
de duplicarlos, y después se borran los fragmentos que sobran. No hay un
momento en que el documento se quede sin vectores.
"""
import time
import uuid

import structlog
from qdrant_client import AsyncQdrantClient, models
from starlette.concurrency import run_in_threadpool

log = structlog.get_logger(__name__)

# Colecciones lógicas permitidas. El nombre físico añade la huella del modelo de
# embeddings (ver embeddings.py).
COLLECTIONS = {
    "documents": "Documentos subidos por los usuarios",
    "opportunities": "Oportunidades con relevancia alta",
    "proposals": "Propuestas aprobadas o enviadas (histórico)",
    "service_lines": "Portfolio de servicios",
}
_NAMESPACE = uuid.UUID("6f1c2a52-7d8e-4b1f-9a51-3c1d2e0f5a77")
_INDEXED_FIELDS = {
    "ref_id": models.PayloadSchemaType.INTEGER,
    "owner_user_id": models.PayloadSchemaType.INTEGER,
    "allowed_roles": models.PayloadSchemaType.KEYWORD,
    "is_current": models.PayloadSchemaType.BOOL,
    "doc_type": models.PayloadSchemaType.KEYWORD,
    "expires_ts": models.PayloadSchemaType.INTEGER,
    "chunk_index": models.PayloadSchemaType.INTEGER,
}
UPSERT_BATCH = 100
EMBED_BATCH = 64


class UnknownCollection(ValueError):
    pass


class VectorStore:
    def __init__(self, client: AsyncQdrantClient, embedder):
        self.client = client
        self.embedder = embedder
        self._ready: set[str] = set()

    def physical(self, logical: str) -> str:
        if logical not in COLLECTIONS:
            raise UnknownCollection(logical)
        return f"{logical}__{self.embedder.slug}"

    async def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            vectors += await run_in_threadpool(self.embedder.embed, texts[start:start + EMBED_BATCH], kind)
        return vectors

    async def _ensure(self, logical: str, dims: int) -> str:
        name = self.physical(logical)
        if name in self._ready:
            return name
        if not await self.client.collection_exists(name):
            await self.client.create_collection(
                name, vectors_config=models.VectorParams(size=dims, distance=models.Distance.COSINE)
            )
            log.info("qdrant_collection_created", collection=name, dims=dims)
        for field, schema in _INDEXED_FIELDS.items():
            try:
                await self.client.create_payload_index(name, field, field_schema=schema)
            except Exception:
                pass
        self._ready.add(name)
        return name

    def point_id(self, logical: str, ref_id: int, chunk_index: int) -> str:
        return str(uuid.uuid5(_NAMESPACE, f"{logical}:{ref_id}:{chunk_index}"))

    async def upsert(self, logical: str, ref_id: int, chunks: list[dict], common: dict) -> dict:
        """Indexa los fragmentos de un registro (documento, oportunidad...)."""
        texts = [c["text"] for c in chunks]
        vectors = await self.embed(texts, "document") if texts else []
        if not vectors:
            await self.delete(logical, ref_id)
            return {"points": 0, "model": self.embedder.model}
        name = await self._ensure(logical, len(vectors[0]))
        points = []
        for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=False)):
            payload = {**common, "ref_id": ref_id, "chunk_index": i, "total_chunks": len(chunks),
                       "text": chunk["text"], **(chunk.get("metadata") or {})}
            points.append(models.PointStruct(id=self.point_id(logical, ref_id, i), vector=vector,
                                             payload=payload))
        for start in range(0, len(points), UPSERT_BATCH):
            await self.client.upsert(name, points=points[start:start + UPSERT_BATCH], wait=True)
        # Fragmentos sobrantes de una indexación anterior más larga
        await self.client.delete(name, points_selector=models.FilterSelector(filter=models.Filter(must=[
            models.FieldCondition(key="ref_id", match=models.MatchValue(value=ref_id)),
            models.FieldCondition(key="chunk_index", range=models.Range(gte=len(points))),
        ])), wait=True)
        return {"points": len(points), "model": self.embedder.model, "dims": len(vectors[0])}

    async def delete(self, logical: str, ref_id: int) -> None:
        name = self.physical(logical)
        if not await self.client.collection_exists(name):
            return
        await self.client.delete(name, points_selector=models.FilterSelector(filter=models.Filter(
            must=[models.FieldCondition(key="ref_id", match=models.MatchValue(value=ref_id))])), wait=True)

    async def set_payload(self, logical: str, ref_id: int, payload: dict) -> None:
        name = self.physical(logical)
        if not await self.client.collection_exists(name):
            return
        await self.client.set_payload(name, payload=payload, points=models.Filter(
            must=[models.FieldCondition(key="ref_id", match=models.MatchValue(value=ref_id))]), wait=True)

    async def count(self, logical: str, ref_id: int | None = None) -> int:
        name = self.physical(logical)
        if not await self.client.collection_exists(name):
            return 0
        flt = None
        if ref_id is not None:
            flt = models.Filter(must=[models.FieldCondition(key="ref_id", match=models.MatchValue(value=ref_id))])
        return (await self.client.count(name, count_filter=flt, exact=True)).count

    async def counts_by_ref(self, logical: str) -> dict[int, int]:
        """Puntos por registro, para la comprobación de coherencia con MySQL."""
        name = self.physical(logical)
        if not await self.client.collection_exists(name):
            return {}
        counts: dict[int, int] = {}
        offset = None
        while True:
            points, offset = await self.client.scroll(name, limit=1000, offset=offset,
                                                      with_payload=["ref_id"], with_vectors=False)
            for point in points:
                ref = int((point.payload or {}).get("ref_id", 0))
                counts[ref] = counts.get(ref, 0) + 1
            if offset is None:
                return counts

    @staticmethod
    def build_filter(spec: dict) -> models.Filter | None:
        must: list = []
        if spec.get("only_current", True):
            must.append(models.FieldCondition(key="is_current", match=models.MatchValue(value=True)))
        if spec.get("ref_ids"):
            must.append(models.FieldCondition(key="ref_id", match=models.MatchAny(any=spec["ref_ids"])))
        if spec.get("doc_types"):
            must.append(models.FieldCondition(key="doc_type", match=models.MatchAny(any=spec["doc_types"])))
        if spec.get("not_expired"):
            # Sin fecha de cierre o con fecha futura (Capítulo 12: las caducadas se
            # conservan para consultas históricas, pero no salen como vigentes)
            must.append(models.Filter(should=[
                models.IsNullCondition(is_null=models.PayloadField(key="expires_ts")),
                models.IsEmptyCondition(is_empty=models.PayloadField(key="expires_ts")),
                models.FieldCondition(key="expires_ts", range=models.Range(gt=int(time.time()))),
            ]))
        access = spec.get("access")
        if access and not access.get("bypass"):
            should = [models.FieldCondition(key="allowed_roles",
                                            match=models.MatchAny(any=["*", *access.get("roles", [])]))]
            if access.get("user_id") is not None:
                should.append(models.FieldCondition(key="owner_user_id",
                                                    match=models.MatchValue(value=access["user_id"])))
            must.append(models.Filter(should=should))
        return models.Filter(must=must) if must else None

    async def search(self, logical_names: list[str], query: str, spec: dict, limit: int,
                     score_threshold: float | None) -> list[dict]:
        vector = (await self.embed([query], "query"))[0]
        flt = self.build_filter(spec)
        hits: list[dict] = []
        for logical in logical_names:
            name = self.physical(logical)
            if not await self.client.collection_exists(name):
                continue
            result = await self.client.query_points(name, query=vector, query_filter=flt, limit=limit,
                                                    with_payload=True, score_threshold=score_threshold)
            for point in result.points:
                payload = dict(point.payload or {})
                hits.append({"collection": logical, "score": round(float(point.score), 4),
                             "ref_id": payload.pop("ref_id", None), "text": payload.pop("text", ""),
                             "payload": payload})
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:limit]

    async def stats(self) -> list[dict]:
        out = []
        for logical, description in COLLECTIONS.items():
            out.append({"collection": logical, "physical": self.physical(logical),
                        "description": description, "points": await self.count(logical)})
        return out
