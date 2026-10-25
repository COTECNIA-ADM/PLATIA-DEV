"""Límite de peticiones con ventana deslizante en Redis (Capítulo 6).

Funciona con varias instancias del backend porque el contador vive en Redis.
Si Redis no responde, deja pasar la petición y lo registra: el login sigue
protegido por el bloqueo de cuenta tras varios fallos (ADR-009).
"""
import math
import time
import uuid
from functools import wraps

import structlog
from flask import current_app, g, jsonify, request

from ..models import AuditAction
from .audit import audit
from .redis_store import get_redis

log = structlog.get_logger(__name__)


def _identity(scope: str) -> str:
    if scope == "user" and g.get("security"):
        return f"user:{g.security.user_id}"
    return f"ip:{request.remote_addr}"


def hit(key: str, limit: int, period: int) -> int:
    """Registra un intento. Devuelve 0 si se permite o los segundos que hay que esperar."""
    r = get_redis()
    now = time.time()
    redis_key = f"ratelimit:{key}"
    pipe = r.pipeline()
    pipe.zremrangebyscore(redis_key, 0, now - period)
    pipe.zcard(redis_key)
    pipe.zrange(redis_key, 0, 0, withscores=True)
    _, count, oldest = pipe.execute()
    if count >= limit:
        oldest_ts = oldest[0][1] if oldest else now
        return max(1, math.ceil(oldest_ts + period - now))
    pipe = r.pipeline()
    pipe.zadd(redis_key, {f"{now}:{uuid.uuid4().hex[:8]}": now})
    pipe.expire(redis_key, period)
    pipe.execute()
    return 0


def rate_limit(limit: int | str = "RATE_LIMIT_DEFAULT", period: int = 60, scope: str = "user"):
    """``limit`` es un número o el nombre de una clave de configuración."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            max_hits = current_app.config[limit] if isinstance(limit, str) else limit
            key = f"{request.endpoint}:{_identity(scope)}"
            try:
                retry_after = hit(key, max_hits, period)
            except Exception as exc:  # noqa: BLE001
                log.warning("rate_limit_unavailable", error=str(exc))
                retry_after = 0
            if retry_after:
                audit(AuditAction.RATE_LIMITED, "WARNING", details={"endpoint": request.endpoint})
                resp = jsonify(error="Demasiadas peticiones. Inténtalo más tarde.")
                resp.status_code = 429
                resp.headers["Retry-After"] = str(retry_after)
                return resp
            return fn(*args, **kwargs)

        wrapper.rate_limit = limit
        return wrapper

    return decorator
