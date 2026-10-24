"""Dead-letter queue y estado de las colas (Capítulo 8), dentro de la app ``admin``."""
from flask import Blueprint, g, jsonify, request

from ..api.common import get_active, iso, paginate
from ..errors import BusinessRuleError
from ..extensions import db
from ..models import AuditAction, FailedTask, utcnow
from ..queue import PRIORITY_USER, QUEUE_NAMES, celery
from ..security.audit import audit
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit
from .admin import _admin_app_only

admin_tasks_bp = Blueprint("admin_tasks", __name__, url_prefix="/api/admin/tasks")

# Solo se reencolan tareas propias: nunca un nombre arbitrario guardado en la BD
RETRYABLE_PREFIXES = ("tasks.",)


def failed_dict(t: FailedTask) -> dict:
    return {"id": t.id, "task_id": t.task_id, "task_name": t.task_name, "queue": t.queue,
            "error_type": t.error_type, "error_message": t.error_message, "args": t.task_args,
            "retries": t.retries, "failed_at": iso(t.failed_at), "reviewed": t.reviewed,
            "reviewed_by": t.reviewed_by, "reviewed_at": iso(t.reviewed_at),
            "requeued_task_id": t.requeued_task_id}


@admin_tasks_bp.get("/failed")
@platform_guard
@_admin_app_only
@require_permission("tasks", "read")
@rate_limit("RATE_LIMIT_READ")
def list_failed():
    stmt = db.select(FailedTask).order_by(FailedTask.failed_at.desc(), FailedTask.id.desc())
    if request.args.get("reviewed") in ("true", "false"):
        stmt = stmt.where(FailedTask.reviewed.is_(request.args["reviewed"] == "true"))
    if name := request.args.get("task_name"):
        stmt = stmt.where(FailedTask.task_name == name)
    return jsonify(paginate(stmt, failed_dict))


@admin_tasks_bp.post("/failed/<int:failed_id>/review")
@platform_guard
@_admin_app_only
@require_permission("tasks", "write")
@rate_limit("RATE_LIMIT_WRITE")
def mark_reviewed(failed_id: int):
    task = get_active(FailedTask, failed_id, "Tarea fallida")
    task.reviewed, task.reviewed_by, task.reviewed_at = True, g.security.user_id, utcnow()
    db.session.commit()
    return jsonify(failed_dict(task))


@admin_tasks_bp.post("/failed/<int:failed_id>/retry")
@platform_guard
@_admin_app_only
@require_permission("tasks", "write")
@rate_limit("RATE_LIMIT_WRITE")
def retry_failed(failed_id: int):
    task = get_active(FailedTask, failed_id, "Tarea fallida")
    registered = celery.tasks.get(task.task_name)
    if registered is None or not task.task_name.startswith(RETRYABLE_PREFIXES):
        raise BusinessRuleError("Esta tarea no se puede reencolar.")
    result = registered.apply_async(args=task.task_args or [], kwargs=task.task_kwargs or {},
                                    priority=PRIORITY_USER)
    task.requeued_task_id = result.id
    task.reviewed, task.reviewed_by, task.reviewed_at = True, g.security.user_id, utcnow()
    db.session.commit()
    audit(AuditAction.TASK_REQUEUED, user_id=g.security.user_id, resource_type="failed_tasks",
          resource_id=task.id, details={"task": task.task_name, "new_task_id": result.id})
    return jsonify(failed_dict(task)), 202


@admin_tasks_bp.get("/queues")
@platform_guard
@_admin_app_only
@require_permission("tasks", "read")
@rate_limit("RATE_LIMIT_READ")
def queue_lengths():
    from ..tasks.system import queue_lengths as lengths

    return jsonify({"queues": lengths(), "known_queues": list(QUEUE_NAMES)})
