"""Ejecuciones del portal Low-Code (cola ``automation``, ADR-020, fase L2).

``tasks.automation.run`` llama al webhook del flujo de n8n. Es idempotente: si la
ejecución ya no está en cola, no hace nada. Si n8n no responde, reintenta con backoff y,
al agotar los reintentos, da la ejecución por fallida para que nadie espere sin saberlo.
``tasks.automation.expire_stale`` cierra las que n8n no ha contestado a tiempo.
"""
import structlog

from ..extensions import db
from ..models import AutomationRun
from ..queue import PlatformTask, celery
from ..services import automation as service

log = structlog.get_logger(__name__)


@celery.task(name="tasks.automation.run", base=PlatformTask, bind=True, max_retries=4)
def run(self, run_id: int) -> dict:
    item = db.session.get(AutomationRun, run_id)
    if item is None or not item.is_active:
        return {"status": "missing"}
    try:
        status = service.dispatch(item)
    except service.N8nUnavailable as exc:
        db.session.rollback()
        log.warning("automation_n8n_unavailable", run_id=run_id, error=str(exc), retries=self.request.retries)
        if self.request.retries >= self.max_retries:
            item = db.session.get(AutomationRun, run_id)
            service.give_up(item, "No se ha podido conectar con n8n.")
            db.session.commit()
            return {"status": item.status}
        raise self.retry_later(exc) from exc
    db.session.commit()
    log.info("automation_run_dispatched", run_id=run_id, status=status)
    return {"status": status}


@celery.task(name="tasks.automation.expire_stale", base=PlatformTask)
def expire_stale() -> dict:
    expired = service.expire_stale()
    db.session.commit()
    return {"expired": expired}
