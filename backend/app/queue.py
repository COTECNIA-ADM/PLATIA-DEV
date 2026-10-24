"""Colas de trabajo con Celery (Capítulo 8).

- Siete colas con routing centralizado: el código que encola no decide la cola.
- Serialización JSON, ``acks_late`` y ``reject_on_worker_lost``: si un worker
  muere a mitad de una tarea, otra la retoma (por eso las tareas son idempotentes).
- Tarea base ``PlatformTask``: contexto de Flask, reintentos con backoff
  exponencial y jitter, y dead-letter queue en MySQL al agotar los reintentos.
- Prioridad dentro de cada cola: 3 = una persona espera, 7 = programada, 9 = mantenimiento.
"""
import random
from contextlib import contextmanager

import structlog
from celery import Celery, Task
from celery.schedules import crontab
from flask import Flask, current_app, has_app_context
from kombu import Exchange, Queue

log = structlog.get_logger(__name__)

PRIORITY_USER = 3
PRIORITY_SCHEDULED = 7
PRIORITY_MAINTENANCE = 9

QUEUE_NAMES = ("default", "priority", "ai", "documents", "sync", "crm", "automation")
_exchange = Exchange("default", type="direct")

TASK_ROUTES = {
    "tasks.documents.*": {"queue": "documents"},
    "tasks.proposals.*": {"queue": "documents"},
    "tasks.ai.*": {"queue": "ai"},
    "tasks.agents.*": {"queue": "ai"},
    "tasks.sync.*": {"queue": "sync"},
    "tasks.search.*": {"queue": "sync"},
    "tasks.crm.*": {"queue": "crm"},
    "tasks.automation.*": {"queue": "automation"},
    "tasks.alerts.*": {"queue": "priority"},
    "tasks.notifications.*": {"queue": "default"},
    "tasks.analytics.*": {"queue": "default"},
    "tasks.system.*": {"queue": "default"},
}

TASK_ANNOTATIONS = {
    "tasks.ai.*": {"rate_limit": "30/m"},
    "tasks.automation.*": {"rate_limit": "5/m"},
    "tasks.documents.*": {"rate_limit": "10/m"},
}

# Tareas programadas (Celery Beat). Las pesadas, de madrugada. Las que dependen
# del CRM se añadirán en su fase.
BEAT_SCHEDULE = {
    "send-notification-emails": {
        "task": "tasks.notifications.send_pending_emails",
        "schedule": crontab(minute="*/2"),
    },
    "scan-new-opportunities": {
        "task": "tasks.sync.scan_opportunities",
        "schedule": crontab(minute=0, hour="*/12"),
    },
    "proactive-opportunity-alerts": {
        "task": "tasks.alerts.proactive_scan",
        "schedule": crontab(minute=0),  # cada hora
    },
    "deal-stalled-check": {
        "task": "tasks.alerts.deal_stalled",
        "schedule": crontab(minute=0, hour=8, day_of_week="mon-fri"),
    },
    "recover-pending-documents": {
        "task": "tasks.documents.recover_pending",
        "schedule": crontab(minute="*/15"),
    },
    "gdpr-daily-cleanup": {
        "task": "tasks.sync.gdpr_cleanup",
        "schedule": crontab(minute=0, hour=2),
    },
    "gdpr-anonymize-old-logs": {
        "task": "tasks.sync.anonymize_audit_logs",
        "schedule": crontab(minute=0, hour=3),
    },
    "cleanup-expired-sessions": {
        "task": "tasks.sync.cleanup_sessions",
        "schedule": crontab(minute=30, hour=0),
    },
    "health-check-services": {
        "task": "tasks.system.platform_health_check",
        "schedule": 300.0,  # cada 5 minutos
    },
    # --- Gobernanza de IA (fase 5, Capítulos 11 y 12)
    "verify-prompt-integrity": {
        "task": "tasks.ai.verify_prompt_integrity",
        "schedule": crontab(minute=10, hour="*/12"),
    },
    "scan-pii-in-ai-outputs": {
        "task": "tasks.ai.scan_pii_outputs",
        "schedule": crontab(minute=20, hour="*/6"),
    },
    "check-ai-budgets": {
        "task": "tasks.ai.check_budgets",
        "schedule": crontab(minute=5),  # cada hora
    },
    "recover-unindexed-documents": {
        "task": "tasks.ai.recover_index",
        "schedule": crontab(minute="7-59/15"),
    },
    "rag-consistency-check": {
        "task": "tasks.ai.rag_consistency",
        "schedule": crontab(minute=0, hour=4, day_of_week="sun"),
    },
    "cleanup-ai-output-samples": {
        "task": "tasks.ai.cleanup_usage_samples",
        "schedule": crontab(minute=40, hour=3),
    },
    # --- Búsqueda (fase 5b, Capítulo 13)
    "search-sync-pending": {
        "task": "tasks.search.sync_pending",
        "schedule": 60.0,  # red de seguridad: cada cambio ya lanza su sincronización
    },
    "search-consistency-check": {
        "task": "tasks.search.check_consistency",
        "schedule": crontab(minute="*/10"),
    },
    "search-cleanup-query-log": {
        "task": "tasks.search.cleanup_query_log",
        "schedule": crontab(minute=50, hour=3),
    },
    # --- Copiloto y agentes (fase 5c, Capítulos 14 y 15)
    "agents-expire-approvals": {
        "task": "tasks.agents.expire_approvals",
        "schedule": crontab(minute="*/5"),
    },
    # --- Inteligencia comercial (fase 9a, Capítulo 23)
    "analytics-pipeline-snapshot": {
        "task": "tasks.analytics.take_snapshot",
        "schedule": crontab(minute=50, hour=23),
    },
    "analytics-heatmap": {
        "task": "tasks.analytics.compute_heatmap",
        "schedule": crontab(minute=15, hour=2),
    },
}

TASK_MODULES = ["app.tasks.documents", "app.tasks.proposals", "app.tasks.alerts", "app.tasks.sync",
                "app.tasks.system", "app.tasks.ai", "app.tasks.search", "app.tasks.agents",
                "app.tasks.notifications", "app.tasks.analytics"]

_flask_app: Flask | None = None


def _app() -> Flask:
    if _flask_app is None:
        raise RuntimeError("Celery no está inicializado: llama a init_celery(app).")
    return _flask_app


class FlaskTask(Task):
    """Ejecuta cada tarea dentro del contexto de la aplicación Flask."""

    abstract = True

    def __call__(self, *args, **kwargs):
        if has_app_context():
            return super().__call__(*args, **kwargs)
        with _app().app_context():
            return super().__call__(*args, **kwargs)


def backoff_with_jitter(retry: int, base: int = 60, maximum: int = 3600, jitter: float = 0.25) -> int:
    """Espera = min(base * 2^reintento, máximo) ± 25 %. El jitter reparte los
    reintentos para no provocar una tormenta cuando fallan muchas tareas a la vez."""
    wait = min(base * (2 ** retry), maximum)
    return max(1, int(wait + wait * jitter * (2 * random.random() - 1)))


class TransientError(Exception):
    """Fallo pasajero (red, servicio externo saturado): se reintenta."""


class PlatformTask(FlaskTask):
    """Tarea base: reintentos con backoff y dead-letter queue al agotarlos."""

    abstract = True
    max_retries = 5
    acks_late = True

    def retry_later(self, exc: Exception):
        return self.retry(exc=exc, countdown=backoff_with_jitter(self.request.retries))

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        log.error("task_failed", task=self.name, task_id=task_id, error_type=type(exc).__name__,
                  retries=self.request.retries)
        if has_app_context():
            _send_to_dead_letter_queue(self, exc, task_id, args, kwargs)
        else:
            with _app().app_context():
                _send_to_dead_letter_queue(self, exc, task_id, args, kwargs)


def _send_to_dead_letter_queue(task: Task, exc: Exception, task_id, args, kwargs) -> None:
    from sqlalchemy.orm import Session

    from .extensions import db
    from .models import AuditAction, FailedTask
    from .security.audit import audit

    delivery = getattr(task.request, "delivery_info", None) or {}
    try:
        with Session(db.engines["core"]) as session:
            session.add(FailedTask(
                task_id=task_id or "eager",
                task_name=task.name,
                queue=delivery.get("routing_key"),
                error_type=type(exc).__name__[:100],
                error_message=str(exc)[:2000],
                task_args=list(args or [])[:20],
                task_kwargs=dict(kwargs or {}),
                retries=task.request.retries or 0,
            ))
            session.commit()
    except Exception as dlq_exc:  # noqa: BLE001
        log.error("dead_letter_write_failed", task=task.name, error=str(dlq_exc))
    audit(AuditAction.TASK_FAILED, "WARNING", resource_type="task", resource_id=task_id,
          details={"task": task.name, "error_type": type(exc).__name__})


class TaskAlreadyRunning(Exception):
    pass


@contextmanager
def task_lock(lock_id: str, expire: int = 3600):
    """Bloqueo distribuido en Redis (SET NX EX) para tareas que no deben solaparse."""
    from .security.redis_store import get_redis

    r = get_redis()
    key = f"celery_lock:{lock_id}"
    if not r.set(key, "1", nx=True, ex=expire):
        raise TaskAlreadyRunning(lock_id)
    try:
        yield
    finally:
        r.delete(key)


celery = Celery("platia", task_cls=FlaskTask)


def init_celery(app: Flask) -> Celery:
    global _flask_app
    _flask_app = app
    broker = app.config.get("CELERY_BROKER_URL", "memory://")
    celery.conf.update(
        broker_url=broker,
        result_backend=None if broker.startswith("memory") else broker,
        result_expires=3600,
        task_queues=[Queue(name, _exchange, routing_key=name) for name in QUEUE_NAMES],
        task_default_queue="default",
        task_default_exchange="default",
        task_default_routing_key="default",
        task_routes=TASK_ROUTES,
        task_annotations=TASK_ANNOTATIONS,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_time_limit=app.config.get("CELERY_TASK_TIME_LIMIT", 600),
        task_soft_time_limit=max(30, app.config.get("CELERY_TASK_TIME_LIMIT", 600) - 30),
        # Prioridades con Redis: 0 (más alta) a 9; se agrupan en 4 niveles internos
        broker_transport_options={"priority_steps": list(range(10)), "sep": ":",
                                  "queue_order_strategy": "priority"},
        task_default_priority=PRIORITY_SCHEDULED,
        timezone=app.config.get("TIMEZONE", "Europe/Madrid"),
        enable_utc=True,
        beat_schedule=BEAT_SCHEDULE,
        task_always_eager=app.config.get("CELERY_ALWAYS_EAGER", False),
        task_eager_propagates=False,
        broker_connection_retry_on_startup=True,
    )
    celery.conf.include = TASK_MODULES
    for module in TASK_MODULES:
        __import__(module)
    app.extensions["celery"] = celery
    return celery


def enqueue(task: Task, *args, priority: int = PRIORITY_USER, **kwargs) -> str | None:
    """Encola una tarea. Si el broker no responde, no tumba la petición: devuelve
    None y la tarea programada de recuperación la volverá a lanzar."""
    try:
        result = task.apply_async(args=args, kwargs=kwargs, priority=priority)
        return result.id
    except Exception as exc:  # noqa: BLE001
        log.error("enqueue_failed", task=task.name, error=str(exc))
        if current_app and current_app.config.get("TESTING"):
            raise
        return None
