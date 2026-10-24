"""Tareas del buscador (Capítulo 13). Van a la cola ``sync``.

- ``sync_pending``: lleva a Meilisearch los cambios confirmados en MySQL (a los
  pocos segundos de cada cambio y, por si acaso, cada minuto).
- ``rebuild_index``: reconstruye un índice completo sin cortar las búsquedas.
- ``check_consistency``: compara MySQL con cada índice y reconstruye el que no
  cuadra (también llena los índices la primera vez que se levanta Meilisearch).
- ``cleanup_query_log``: borra el registro de consultas al cumplir la retención.
"""
from datetime import timedelta

import structlog
from flask import current_app

from ..extensions import db
from ..models import SearchQueryLog, utcnow
from ..queue import PRIORITY_MAINTENANCE, PlatformTask, TaskAlreadyRunning, TransientError, celery, enqueue, task_lock
from ..search import sync
from ..search.client import MeiliError

log = structlog.get_logger(__name__)


def _disabled() -> bool:
    return not current_app.config.get("SEARCH_ENABLED", True)


@celery.task(name="tasks.search.sync_pending", base=PlatformTask, bind=True, max_retries=3)
def sync_pending(self) -> dict:
    if _disabled():
        return {"skipped": "SEARCH_ENABLED=false"}
    try:
        with task_lock("search_sync_pending", expire=300):
            return sync.sync_pending()
    except TaskAlreadyRunning:
        return {"skipped": "otra sincronización en curso"}
    except MeiliError as exc:
        # Los ids siguen apuntados en Redis: se reintentará sin perder nada
        log.warning("search_sync_failed", error=str(exc))
        if self.request.retries >= self.max_retries:
            return {"failed": str(exc)}
        raise self.retry_later(TransientError(str(exc)))


@celery.task(name="tasks.search.rebuild_index", base=PlatformTask, bind=True, max_retries=2)
def rebuild_index(self, kind: str) -> dict:
    if _disabled():
        return {"skipped": "SEARCH_ENABLED=false"}
    try:
        with task_lock(f"search_rebuild_{kind}", expire=3 * 3600):
            return sync.rebuild(kind)
    except TaskAlreadyRunning:
        return {"skipped": f"ya se está reconstruyendo {kind}"}
    except MeiliError as exc:
        raise self.retry_later(TransientError(str(exc)))


@celery.task(name="tasks.search.check_consistency", base=PlatformTask)
def check_consistency() -> dict:
    if _disabled():
        return {"skipped": "SEARCH_ENABLED=false"}
    try:
        stale = sync.check_consistency()
    except MeiliError as exc:
        log.warning("search_consistency_unavailable", error=str(exc))
        return {"error": str(exc)}
    for kind in stale:
        enqueue(rebuild_index, kind, priority=PRIORITY_MAINTENANCE)
    if stale:
        log.info("search_indexes_out_of_sync", indexes=stale)
    return {"rebuild": stale}


@celery.task(name="tasks.search.cleanup_query_log", base=PlatformTask)
def cleanup_query_log() -> dict:
    cutoff = utcnow() - timedelta(days=current_app.config["SEARCH_LOG_RETENTION_DAYS"])
    result = db.session.execute(db.delete(SearchQueryLog).where(SearchQueryLog.created_at < cutoff))
    db.session.commit()
    return {"deleted": result.rowcount}
