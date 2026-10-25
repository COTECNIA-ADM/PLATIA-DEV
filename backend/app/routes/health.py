"""Health checks (Apéndice B, blueprint `health`).

- /api/health       comprobación rápida: base de datos y Redis.
- /api/health/full  comprobación completa: los 3 esquemas, Redis, Qdrant, Meilisearch, el
                    servicio de IA y los workers de Celery.

/api/health es público (lo usan Docker y Nginx). /api/health/full exige sesión y
el permiso health.read (rol de administración), porque describe la infraestructura.
"""
from collections.abc import Callable

import redis
import requests
import structlog
from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from ..extensions import db
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit

health_bp = Blueprint("health", __name__, url_prefix="/api/health")
log = structlog.get_logger()


def _check(name: str, fn: Callable[[], str | None]) -> dict:
    """Ejecuta una comprobación. Si devuelve texto, el servicio está degradado:
    responde, pero le falta algo para funcionar del todo."""
    try:
        detail = fn()
        if detail:
            return {"name": name, "status": "degraded", "detail": detail}
        return {"name": name, "status": "healthy"}
    except Exception as exc:  # noqa: BLE001 - un health check informa, no lanza
        log.warning("health_check_failed", service=name, error=str(exc))
        return {"name": name, "status": "unhealthy", "error": type(exc).__name__}


def _check_database(bind: str) -> Callable[[], None]:
    def fn() -> None:
        with db.engines[bind].connect() as conn:
            conn.execute(text("SELECT 1"))

    return fn


def _check_redis() -> None:
    client = redis.Redis.from_url(
        current_app.config["REDIS_URL"],
        socket_timeout=current_app.config["HEALTH_TIMEOUT_SECONDS"],
    )
    client.ping()


def _check_qdrant() -> None:
    headers = {}
    if current_app.config["QDRANT_API_KEY"]:
        headers["api-key"] = current_app.config["QDRANT_API_KEY"]
    resp = requests.get(
        f"{current_app.config['QDRANT_URL']}/readyz",
        headers=headers,
        timeout=current_app.config["HEALTH_TIMEOUT_SECONDS"],
    )
    resp.raise_for_status()


def _check_meilisearch() -> str | None:
    """Meilisearch caído no tumba la plataforma: las búsquedas pasan a MySQL, así
    que se informa como degradado, no como caído."""
    from ..search.client import MeiliError, get_search_client

    if not current_app.config.get("SEARCH_ENABLED", True):
        return "Búsqueda desactivada (SEARCH_ENABLED=false)"
    try:
        status = get_search_client().health().get("status")
    except MeiliError:
        return "Meilisearch no responde: las búsquedas usan MySQL, más lentas y sin facetas"
    if status != "available":
        return f"Meilisearch en estado {status}"
    return None


def _check_ai_service() -> str | None:
    resp = requests.get(
        f"{current_app.config['AI_SERVICE_URL']}/health",
        headers={"X-API-Key": current_app.config["AI_SERVICE_API_KEY"]},
        timeout=current_app.config["HEALTH_TIMEOUT_SECONDS"],
    )
    resp.raise_for_status()
    body = resp.json()
    status = body.get("status")
    if status == "degraded":
        # Responde, pero no puede llamar a Claude (falta ANTHROPIC_API_KEY)
        return "Falta ANTHROPIC_API_KEY en el servicio de IA"
    if status != "healthy":
        raise RuntimeError(status or "unknown")
    return None


def _check_workers() -> str | None:
    """Los workers de Celery responden al ping. Si no hay ninguno, la API sigue
    funcionando pero nada se procesa en segundo plano: degradado, no caído."""
    from ..queue import celery

    replies = celery.control.ping(timeout=1.0) or []
    if not replies:
        return "Ningún worker de Celery responde: los documentos no se procesarán"
    return None


def _summary(services: list[dict]):
    """503 solo si algo está caído; un servicio degradado no tumba la plataforma."""
    statuses = {s["status"] for s in services}
    if "unhealthy" in statuses:
        status, code = "unhealthy", 503
    elif "degraded" in statuses:
        status, code = "degraded", 200
    else:
        status, code = "healthy", 200
    return jsonify({"status": status, "services": services}), code


@health_bp.get("")
def quick():
    return _summary(
        [
            _check("database_platform", _check_database("core")),
            _check("redis", _check_redis),
        ]
    )


@health_bp.get("/full")
@platform_guard
@require_permission("health", "read")
@rate_limit("RATE_LIMIT_READ")
def full():
    return _summary(
        [
            _check("database_platform", _check_database("core")),
            _check("database_operations", _check_database("operations")),
            _check("database_analytics", _check_database("analytics")),
            _check("redis", _check_redis),
            _check("qdrant", _check_qdrant),
            _check("meilisearch", _check_meilisearch),
            _check("ai_service", _check_ai_service),
            _check("workers", _check_workers),
        ]
    )
