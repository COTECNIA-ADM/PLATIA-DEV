"""Servicio de IA (FastAPI): pasarela de proveedores de LLM, embeddings y Qdrant.

Solo es accesible desde la red interna backend_net y exige X-API-Key: el
backend es su único cliente (Capítulo 11). No decide qué modelo ni qué prompt
usar ni registra costes: eso lo hace el backend, que guarda cada llamada con los
datos de uso que este servicio le devuelve (ADR-011).
"""
import asyncio
import functools
import hmac
import json
import math
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from qdrant_client import AsyncQdrantClient
from starlette.concurrency import run_in_threadpool

from . import llm
from .circuit import CircuitBreaker
from .embeddings import build_embedder
from .providers import AnthropicProvider, OpenAICompatibleProvider
from .schemas import (
    CompleteRequest,
    EmbedRequest,
    IndexRequest,
    PayloadRequest,
    RefRequest,
    SearchRequest,
    SimilarityRequest,
)
from .settings import Settings, get_settings
from .vectorstore import COLLECTIONS, UnknownCollection, VectorStore

log = structlog.get_logger()


@dataclass
class Runtime:
    settings: Settings
    providers: dict
    breaker: CircuitBreaker
    embedder: object
    store: VectorStore


def build_runtime(settings: Settings) -> Runtime:
    embedder = build_embedder(settings)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None,
                               timeout=30, check_compatibility=False)
    return Runtime(
        settings=settings,
        providers={"anthropic": AnthropicProvider(settings), "openai_compatible": OpenAICompatibleProvider(settings)},
        breaker=CircuitBreaker(settings.circuit_failure_threshold, settings.circuit_window_seconds,
                               settings.circuit_recovery_seconds),
        embedder=embedder,
        store=VectorStore(qdrant, embedder),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = build_runtime(get_settings())
    app.state.runtime = runtime
    load = getattr(runtime.embedder, "load", None)
    if load is not None:
        # Carga el modelo de embeddings en segundo plano: el health check lo muestra
        # como "loading" mientras tanto y el servicio ya atiende peticiones de LLM.
        asyncio.get_running_loop().run_in_executor(None, _safe_load, load)
    yield


def _safe_load(load) -> None:
    try:
        load()
    except Exception:
        pass


app = FastAPI(title="PLATIA AI Service", docs_url=None, redoc_url=None, lifespan=lifespan)


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def require_api_key(x_api_key: str = Header(default=""), settings: Settings = Depends(get_settings)) -> None:
    if not settings.api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="API key no válida")


@app.exception_handler(UnknownCollection)
async def _unknown_collection(_request: Request, exc: UnknownCollection):
    return JSONResponse(status_code=422, content={"detail": f"Colección desconocida: {exc}"})


@app.get("/health", dependencies=[Depends(require_api_key)])
async def health(settings: Settings = Depends(get_settings), runtime: Runtime = Depends(get_runtime)) -> dict:
    checks: dict[str, str] = {}

    # No se llama a la API de Anthropic en cada health check (coste): solo se
    # comprueba que la clave está configurada y el estado del circuit breaker.
    if settings.llm_gateway_enabled:
        # Las llamadas salen por el gateway corporativo: la credencial es la suya
        checks["llm_gateway"] = "configured" if settings.llm_gateway_api_key else "missing"
        llm_credential = checks["llm_gateway"]
    else:
        checks["anthropic_key"] = "configured" if settings.anthropic_api_key else "missing"
        llm_credential = checks["anthropic_key"]
    checks["anthropic_circuit"] = runtime.breaker.state("anthropic")
    checks["embeddings"] = getattr(runtime.embedder, "status", "ready")

    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.qdrant_url}/readyz", headers=headers)
            resp.raise_for_status()
        checks["qdrant"] = "healthy"
    except httpx.HTTPError as exc:
        log.warning("qdrant_unreachable", error=str(exc))
        checks["qdrant"] = "unhealthy"

    if checks["qdrant"] != "healthy" or checks["embeddings"] == "error":
        status = "unhealthy"
    elif llm_credential != "configured" or checks["anthropic_circuit"] == "open" \
            or checks["embeddings"] != "ready":
        status = "degraded"
    else:
        status = "healthy"
    return {
        "status": status,
        "model": settings.default_model,
        "models": {"default": settings.default_model, "premium": settings.premium_model,
                   "fast": settings.fast_model},
        "embedding": {"provider": runtime.embedder.provider, "model": runtime.embedder.model,
                      "dims": runtime.embedder.dims},
        "fallback_configured": bool(settings.fallback_base_url) and not settings.llm_gateway_enabled,
        "llm_gateway": settings.llm_gateway_enabled,
        "checks": checks,
    }


# ------------------------------------------------------------------ LLM
@app.post("/v1/complete", dependencies=[Depends(require_api_key)])
async def complete(body: CompleteRequest, runtime: Runtime = Depends(get_runtime)):
    outcome = await llm.complete(**_llm_kwargs(body, runtime))
    payload = outcome.to_dict()
    if outcome.result is None:
        # Se devuelven igualmente los intentos: el backend registra también los fallidos
        status = 422 if outcome.rejected else (502 if outcome.error and "JSON" in outcome.error else 503)
        return JSONResponse(status_code=status, content={"detail": outcome.error, **payload})
    return payload


def gateway_headers(body: CompleteRequest, settings: Settings) -> dict[str, str] | None:
    """Cabeceras para el gateway LLM: tarea, persona y correlación (ADR-019)."""
    if not settings.llm_gateway_enabled:
        return None
    headers = {"X-Platia-Purpose": body.service_type}
    if body.user_ref:
        headers["X-Platia-User-Id"] = body.user_ref
    if body.correlation_id:
        # Las llamadas de una misma tarea comparten id: el gateway las agrupa igual que PLATIA
        headers["X-Request-ID"] = body.correlation_id
    return headers


def _llm_kwargs(body: CompleteRequest, runtime: Runtime) -> dict:
    return dict(
        headers=gateway_headers(body, runtime.settings),
        providers=runtime.providers, breaker=runtime.breaker,
        targets=[t.model_dump() for t in body.targets], system=body.system,
        messages=[m.model_dump() for m in body.messages], max_tokens=body.max_tokens, effort=body.effort,
        json_schema=body.json_schema, timeout=body.timeout_seconds, service_type=body.service_type,
        tools=[t.model_dump() for t in body.tools] if body.tools else None,
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/v1/stream", dependencies=[Depends(require_api_key)])
async def stream(body: CompleteRequest, runtime: Runtime = Depends(get_runtime)):
    """Igual que /v1/complete, pero en Server-Sent Events (Capítulo 15).

    Eventos: ``delta`` (texto según llega), y al final ``final`` (mismo cuerpo que
    /v1/complete, con los bloques de contenido) o ``error`` (con los intentos, para
    que el backend registre también los fallidos)."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_text(text: str) -> None:
        await queue.put(_sse("delta", {"text": text}))

    async def produce() -> None:
        try:
            outcome = await llm.complete(**_llm_kwargs(body, runtime), on_text=on_text)
            payload = outcome.to_dict()
            if outcome.result is None:
                await queue.put(_sse("error", {"detail": outcome.error, "rejected": outcome.rejected, **payload}))
            else:
                await queue.put(_sse("final", payload))
        except Exception as exc:  # noqa: BLE001 - el cliente siempre recibe un cierre
            log.exception("llm_stream_failed", service_type=body.service_type)
            await queue.put(_sse("error", {"detail": f"Error interno: {type(exc).__name__}", "attempts": []}))
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(produce())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()  # el backend cortó la conexión: no se sigue generando

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ Embeddings y RAG
@app.post("/v1/embed", dependencies=[Depends(require_api_key)])
async def embed(body: EmbedRequest, runtime: Runtime = Depends(get_runtime)) -> dict:
    vectors = await runtime.store.embed(body.texts, body.kind)
    return {"vectors": vectors, "model": runtime.embedder.model, "dims": len(vectors[0]) if vectors else None}


@functools.lru_cache(maxsize=512)
def _cached_vector(embedder, text: str) -> tuple[float, ...]:
    return tuple(embedder.embed([text], "document")[0])


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


@app.post("/v1/similarity", dependencies=[Depends(require_api_key)])
async def similarity(body: SimilarityRequest, runtime: Runtime = Depends(get_runtime)) -> dict:
    """Matriz de similitud coseno queries x candidatos. Los candidatos (p. ej. las
    líneas de servicio) se cachean en memoria porque cambian poco."""
    emb = runtime.embedder

    def _work():
        queries = emb.embed(body.queries, "query")
        cands = [_cached_vector(emb, c) for c in body.candidates]
        return [[round(_cosine(q, c), 4) for c in cands] for q in queries]

    return {"scores": await run_in_threadpool(_work), "model": emb.model}


@app.post("/v1/rag/index", dependencies=[Depends(require_api_key)])
async def rag_index(body: IndexRequest, runtime: Runtime = Depends(get_runtime)) -> dict:
    result = await runtime.store.upsert(body.collection, body.ref_id,
                                        [c.model_dump() for c in body.chunks], body.common)
    return {"collection": body.collection, "ref_id": body.ref_id, **result}


@app.post("/v1/rag/search", dependencies=[Depends(require_api_key)])
async def rag_search(body: SearchRequest, runtime: Runtime = Depends(get_runtime)) -> dict:
    spec = body.model_dump(include={"only_current", "not_expired", "ref_ids", "doc_types", "access"})
    hits = await runtime.store.search(body.collections, body.query, spec, body.limit, body.score_threshold)
    return {"hits": hits, "model": runtime.embedder.model}


@app.post("/v1/rag/delete", dependencies=[Depends(require_api_key)])
async def rag_delete(body: RefRequest, runtime: Runtime = Depends(get_runtime)) -> dict:
    await runtime.store.delete(body.collection, body.ref_id)
    return {"deleted": True}


@app.post("/v1/rag/payload", dependencies=[Depends(require_api_key)])
async def rag_payload(body: PayloadRequest, runtime: Runtime = Depends(get_runtime)) -> dict:
    allowed = {"is_current", "allowed_roles", "owner_user_id", "expires_ts", "title", "doc_type", "status"}
    unknown = set(body.payload) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"Campos no permitidos: {sorted(unknown)}")
    await runtime.store.set_payload(body.collection, body.ref_id, body.payload)
    return {"updated": True}


@app.post("/v1/rag/count", dependencies=[Depends(require_api_key)])
async def rag_count(body: RefRequest, runtime: Runtime = Depends(get_runtime)) -> dict:
    return {"points": await runtime.store.count(body.collection, body.ref_id)}


@app.get("/v1/rag/collections/{collection}/refs", dependencies=[Depends(require_api_key)])
async def rag_refs(collection: str, runtime: Runtime = Depends(get_runtime)) -> dict:
    counts = await runtime.store.counts_by_ref(collection)
    return {"collection": collection, "refs": {str(k): v for k, v in counts.items()}}


@app.get("/v1/rag/collections", dependencies=[Depends(require_api_key)])
async def rag_collections(runtime: Runtime = Depends(get_runtime)) -> dict:
    return {"collections": await runtime.store.stats(), "embedding_model": runtime.embedder.model,
            "available": list(COLLECTIONS)}
