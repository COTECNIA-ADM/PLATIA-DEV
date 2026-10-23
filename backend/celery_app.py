"""Workers de Celery (Capítulo 8). Mismo código que el backend, colas distintas.

En el núcleo mínimo un único worker atiende todas las colas. Más adelante se
separarán en celery_default, celery_ai y celery_automation, como en el libro.
"""
import os

from celery import Celery

from app.config import redis_url

broker = redis_url("REDIS_DB_CELERY", "1")

celery = Celery("platia", broker=broker, backend=broker)
celery.conf.update(
    task_default_queue="default",
    task_time_limit=int(os.environ.get("CELERY_TASK_TIME_LIMIT", "600")),
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone=os.environ.get("TIMEZONE", "Europe/Madrid"),
)


@celery.task(name="system.ping")
def ping() -> str:
    """Tarea mínima para comprobar que el worker procesa la cola."""
    return "pong"
