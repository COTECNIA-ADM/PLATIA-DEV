"""Servicio de IA (FastAPI). En la fase 0 solo expone el health check.

Solo es accesible desde la red interna backend_net y exige X-API-Key:
el backend es su único cliente (Capítulo 11).
"""
import hmac

import httpx
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException

from .settings import Settings, get_settings

log = structlog.get_logger()
app = FastAPI(title="PLATIA AI Service", docs_url=None, redoc_url=None)


def require_api_key(
    x_api_key: str = Header(default=""), settings: Settings = Depends(get_settings)
) -> None:
    if not settings.api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="API key no válida")


@app.get("/health", dependencies=[Depends(require_api_key)])
async def health(settings: Settings = Depends(get_settings)) -> dict:
    checks: dict[str, str] = {}

    # No se llama a la API de Anthropic en cada health check (coste): solo se
    # comprueba que la clave está configurada.
    checks["anthropic_key"] = "configured" if settings.anthropic_api_key else "missing"

    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.qdrant_url}/readyz", headers=headers)
            resp.raise_for_status()
        checks["qdrant"] = "healthy"
    except httpx.HTTPError as exc:
        log.warning("qdrant_unreachable", error=str(exc))
        checks["qdrant"] = "unhealthy"

    if checks["qdrant"] != "healthy":
        status = "unhealthy"
    elif checks["anthropic_key"] != "configured":
        status = "degraded"
    else:
        status = "healthy"
    return {"status": status, "model": settings.default_model, "checks": checks}
