"""Salud de la plataforma y de las colas (cola ``default``, Capítulo 8)."""
from datetime import timedelta

import redis
import structlog
from flask import current_app
from sqlalchemy import func, text

from ..extensions import db
from ..models import AuditLog, FailedTask, utcnow
from ..queue import QUEUE_NAMES, celery
from ..queue import PlatformTask
from ..security.redis_store import get_redis
from ..services.notifications import notify_many, superadmins

log = structlog.get_logger(__name__)
LAST_RUN_KEY = "health_check:last_run"


def queue_lengths() -> dict[str, int]:
    """Tareas pendientes por cola en el broker (incluye las sub-colas de prioridad)."""
    broker = current_app.config.get("CELERY_BROKER_URL", "")
    if not broker.startswith("redis"):
        return {}
    client = redis.Redis.from_url(broker, socket_timeout=3)
    lengths = {}
    for name in QUEUE_NAMES:
        keys = [name] + [f"{name}:{p}" for p in range(1, 10)]
        pipe = client.pipeline()
        for key in keys:
            pipe.llen(key)
        lengths[name] = sum(pipe.execute())
    return lengths


def _thresholds() -> dict[str, int]:
    result = {}
    for item in current_app.config["QUEUE_ALERT_THRESHOLDS"].split(","):
        name, _, value = item.partition("=")
        if name.strip() and value.strip().isdigit():
            result[name.strip()] = int(value)
    return result


@celery.task(name="tasks.system.platform_health_check", base=PlatformTask)
def platform_health_check() -> dict:
    """Cada 5 minutos: bases de datos, colas saturadas, eventos críticos y tareas
    fallidas nuevas. Avisa a los superadministradores (con deduplicación)."""
    problems = []
    for bind in ("core", "operations", "analytics"):
        try:
            with db.engines[bind].connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Base de datos {bind}: {type(exc).__name__}")

    try:
        lengths = queue_lengths()
    except Exception as exc:  # noqa: BLE001
        lengths = {}
        problems.append(f"Broker de colas: {type(exc).__name__}")
    for name, limit in _thresholds().items():
        if lengths.get(name, 0) > limit:
            problems.append(f"Cola {name} saturada: {lengths[name]} tareas pendientes (umbral {limit})")

    r = get_redis()
    last = r.get(LAST_RUN_KEY)
    since = utcnow() - timedelta(minutes=10)
    if last:
        from datetime import datetime

        since = datetime.fromisoformat(last.decode() if isinstance(last, bytes) else last)
    now = utcnow()
    critical = db.session.scalar(db.select(func.count()).select_from(AuditLog).where(
        AuditLog.severity == "CRITICAL", AuditLog.created_at >= since))
    failed = db.session.scalar(db.select(func.count()).select_from(FailedTask).where(
        FailedTask.failed_at >= since))
    r.set(LAST_RUN_KEY, now.isoformat())
    if critical:
        problems.append(f"{critical} eventos de seguridad críticos en la auditoría")
    if failed:
        problems.append(f"{failed} tareas han agotado sus reintentos (ver Admin > Tareas)")

    if problems:
        log.warning("platform_health_problems", problems=problems)
        notify_many(superadmins(), "SYSTEM", "Avisos de la plataforma", "\n".join(problems),
                    link="/admin/health", priority="high", extra_data={"problems": problems})
    return {"problems": problems, "queues": lengths}
