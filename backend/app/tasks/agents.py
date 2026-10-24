"""Tareas del copiloto y los agentes (cola ``ai``, Capítulos 14 y 15)."""
import structlog

from ..ai.errors import AIDisabledError, AIRejectedError, AIUnavailableError, BudgetExceededError
from ..queue import PlatformTask, celery

log = structlog.get_logger(__name__)
# Memoria y resumen son mejoras: si la IA no está, se dejan para el siguiente intercambio
SKIP = (AIDisabledError, AIRejectedError, BudgetExceededError, AIUnavailableError)


@celery.task(name="tasks.agents.extract_memories", base=PlatformTask, bind=True, max_retries=0)
def extract_memories(self, conversation_id: int) -> dict:
    from ..agents import memory

    try:
        return {"conversation_id": conversation_id, "created": memory.extract(conversation_id)}
    except SKIP as exc:
        log.info("memory_extraction_skipped", conversation=conversation_id, error=type(exc).__name__)
        return {"conversation_id": conversation_id, "status": "skipped"}


@celery.task(name="tasks.agents.summarize_conversation", base=PlatformTask, bind=True, max_retries=0)
def summarize_conversation(self, conversation_id: int) -> dict:
    from ..agents import chat

    try:
        return {"conversation_id": conversation_id, "summarized": chat.summarize(conversation_id)}
    except SKIP as exc:
        log.info("conversation_summary_skipped", conversation=conversation_id, error=type(exc).__name__)
        return {"conversation_id": conversation_id, "status": "skipped"}


@celery.task(name="tasks.agents.expire_approvals", base=PlatformTask)
def expire_approvals() -> dict:
    from ..agents import runner

    return {"expired": runner.expire_stale()}
