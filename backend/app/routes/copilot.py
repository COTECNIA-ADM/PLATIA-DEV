"""Copiloto: conversaciones en streaming, aprobaciones y memoria (Capítulo 14).

- ``/api/copilot/conversations``: conversaciones propias (nadie más las ve).
- ``POST /api/copilot/conversations/<id>/messages``: mensaje nuevo; la respuesta
  llega por SSE (``text/event-stream``) con los eventos ``intent``, ``agent``,
  ``delta``, ``replace``, ``tool_call``, ``tool_result``, ``notice``,
  ``rag_answer``, ``approval_required``, ``done`` y ``error``.
- ``POST /api/copilot/runs/<run_id>/approval``: la persona confirma o rechaza las
  acciones que propuso el agente; la respuesta sigue por SSE.
- ``/api/copilot/memories``: lo que el copiloto recuerda; se ve, se corrige y se
  borra. ``GET /api/copilot/export``: copia de las conversaciones y la memoria.
"""
import json

from flask import Blueprint, Response, g, jsonify, stream_with_context

from ..agents import chat, memory
from ..agents.actor import Actor
from ..agents.runner import AgentSession
from ..ai import pii
from ..api.common import iso, paginate, parse_body
from ..api.schemas import ApprovalIn, ChatMessageIn, ConversationIn, ConversationPatch, MemoryIn, MemoryPatch
from ..errors import DomainError, NotFoundError, ValidationError
from ..extensions import db
from ..models import AgentRun, ChatConversation, ChatMessage, UserMemory, utcnow
from ..security.context import platform_guard, require_ai_module, require_permission
from ..security.ratelimit import rate_limit

copilot_bp = Blueprint("copilot", __name__, url_prefix="/api/copilot")


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def stream(make_events) -> Response:
    """Envía los eventos por SSE. Un error a mitad se envía como evento, sin detalles internos.

    ``make_events`` se llama ya dentro del streaming: Flask cierra la sesión de base
    de datos al devolver la respuesta, así que los registros se cargan de nuevo
    ahí y no en la vista (si no, los cambios sobre ellos se perderían)."""
    def generate():
        try:
            for event, data in make_events():
                yield sse(event, data)
        except DomainError as exc:
            yield sse("error", {"message": exc.message})
        except Exception:  # noqa: BLE001
            import structlog

            structlog.get_logger(__name__).exception("copilot_stream_failed")
            yield sse("error", {"message": "Ha fallado algo inesperado. Inténtalo de nuevo."})

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ Conversaciones
@copilot_bp.get("/conversations")
@platform_guard
@require_permission("copilot", "read")
@rate_limit("RATE_LIMIT_READ")
def list_conversations():
    stmt = ChatConversation.select_active().where(ChatConversation.user_id == g.security.user_id).order_by(
        ChatConversation.last_message_at.desc(), ChatConversation.id.desc())
    return jsonify(paginate(stmt, chat.conversation_dict))


@copilot_bp.post("/conversations")
@platform_guard
@require_permission("copilot", "write")
@require_ai_module("copilot_chat")
@rate_limit("RATE_LIMIT_WRITE")
def create_conversation():
    data = parse_body(ConversationIn)
    conv = ChatConversation(user_id=g.security.user_id, title=data.title or "Nueva conversación",
                            created_by=g.security.user_id, last_message_at=utcnow())
    db.session.add(conv)
    db.session.commit()
    return jsonify(chat.conversation_dict(conv)), 201


@copilot_bp.get("/conversations/<int:conversation_id>")
@platform_guard
@require_permission("copilot", "read")
@rate_limit("RATE_LIMIT_READ")
def get_conversation(conversation_id: int):
    conv = chat.get_conversation(conversation_id, g.security.user_id)
    rows = db.session.scalars(db.select(ChatMessage).filter_by(conversation_id=conv.id)
                              .order_by(ChatMessage.id.desc()).limit(200)).all()[::-1]
    return jsonify({**chat.conversation_dict(conv), "messages": [chat.message_dict(m) for m in rows]})


@copilot_bp.patch("/conversations/<int:conversation_id>")
@platform_guard
@require_permission("copilot", "write")
@rate_limit("RATE_LIMIT_WRITE")
def rename_conversation(conversation_id: int):
    conv = chat.get_conversation(conversation_id, g.security.user_id)
    conv.title = parse_body(ConversationPatch).title
    db.session.commit()
    return jsonify(chat.conversation_dict(conv))


@copilot_bp.delete("/conversations/<int:conversation_id>")
@platform_guard
@require_permission("copilot", "write")
@rate_limit("RATE_LIMIT_WRITE")
def delete_conversation(conversation_id: int):
    conv = chat.get_conversation(conversation_id, g.security.user_id)
    conv.soft_delete()
    db.session.commit()
    return "", 204


@copilot_bp.post("/conversations/<int:conversation_id>/messages")
@platform_guard
@require_permission("copilot", "write")
@require_ai_module("copilot_chat")
@rate_limit("RATE_LIMIT_AI")
def send_message(conversation_id: int):
    conv = chat.get_conversation(conversation_id, g.security.user_id)
    data = parse_body(ChatMessageIn)
    text = chat.check_message(data.content, g.security.user_id)  # bloqueado -> 422 antes de abrir el stream
    actor, conv_id = Actor.for_user(g.security.user_id), conv.id
    return stream(lambda: chat.respond(conv_id, actor, text, opportunity_id=data.opportunity_id,
                                       document_ids=data.document_ids))


@copilot_bp.post("/runs/<run_id>/approval")
@platform_guard
@require_permission("copilot", "write")
@require_ai_module("copilot_chat")
@rate_limit("RATE_LIMIT_AI")
def approve_run(run_id: str):
    data = parse_body(ApprovalIn)
    actor = Actor.for_user(g.security.user_id)
    run = AgentSession.claim(run_id[:36], actor)  # 404 si no es suya, 409 si ya no espera
    conv = chat.get_conversation(run.conversation_id, g.security.user_id)
    run_pk, conv_id = run.id, conv.id
    return stream(lambda: chat.resume(conv_id, AgentSession.load(run_pk, actor), data.approve, data.comment))


@copilot_bp.get("/runs/<run_id>")
@platform_guard
@require_permission("copilot", "read")
@rate_limit("RATE_LIMIT_READ")
def get_run(run_id: str):
    run = db.session.scalar(db.select(AgentRun).filter_by(run_uid=run_id[:36]))
    if run is None or run.user_id != g.security.user_id:
        raise NotFoundError("Ejecución no encontrada.")
    return jsonify({"run_id": run.run_uid, "status": run.status, "stop_reason": run.stop_reason,
                    "pending": run.pending or [], "expires_at": iso(run.expires_at),
                    "iterations": run.iterations, "tool_calls": run.tool_calls or []})


# ------------------------------------------------------------------ Memoria
def _own_memory(memory_id: int) -> UserMemory:
    m = db.session.get(UserMemory, memory_id)
    if m is None or m.user_id != g.security.user_id:
        raise NotFoundError("Recuerdo no encontrado.")
    return m


@copilot_bp.get("/memories")
@platform_guard
@require_permission("copilot", "read")
@rate_limit("RATE_LIMIT_READ")
def list_memories():
    return jsonify(items=[memory.to_dict(m) for m in memory.ranked(g.security.user_id)])


@copilot_bp.post("/memories")
@platform_guard
@require_permission("copilot", "write")
@rate_limit("RATE_LIMIT_WRITE")
def add_memory():
    data = parse_body(MemoryIn)
    text = chat.check_message(data.content, g.security.user_id)
    m = memory.add(g.security.user_id, data.category, text, source="user")
    if m is None:
        raise ValidationError("El recuerdo está vacío después de quitar los datos personales.")
    db.session.commit()
    return jsonify(memory.to_dict(m)), 201


@copilot_bp.patch("/memories/<int:memory_id>")
@platform_guard
@require_permission("copilot", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_memory(memory_id: int):
    m = _own_memory(memory_id)
    data = parse_body(MemoryPatch)
    if data.category:
        m.category = data.category
    if data.content:
        text, _ = pii.redact(chat.check_message(data.content, g.security.user_id))
        m.content, m.content_hash, m.source = text, memory.content_hash(text), "user"
    db.session.commit()
    return jsonify(memory.to_dict(m))


@copilot_bp.delete("/memories/<int:memory_id>")
@platform_guard
@require_permission("copilot", "write")
@rate_limit("RATE_LIMIT_WRITE")
def delete_memory(memory_id: int):
    db.session.delete(_own_memory(memory_id))
    db.session.commit()
    return "", 204


@copilot_bp.delete("/memories")
@platform_guard
@require_permission("copilot", "write")
@rate_limit("RATE_LIMIT_WRITE")
def forget_everything():
    deleted = db.session.execute(db.delete(UserMemory).where(UserMemory.user_id == g.security.user_id)).rowcount
    db.session.commit()
    return jsonify({"deleted": deleted})


@copilot_bp.get("/export")
@platform_guard
@require_permission("copilot", "read")
@rate_limit("RATE_LIMIT_EXPORT")
def export_mine():
    """Derecho de acceso y portabilidad: conversaciones y memoria propias."""
    user_id = g.security.user_id
    convs = db.session.scalars(db.select(ChatConversation).filter_by(user_id=user_id)
                               .order_by(ChatConversation.id)).all()
    return jsonify({
        "user_id": user_id, "generated_at": iso(utcnow()),
        "conversations": [{**chat.conversation_dict(c), "deleted": not c.is_active, "summary": c.summary,
                           "messages": [chat.message_dict(m) for m in c.messages]} for c in convs],
        "memories": [memory.to_dict(m) for m in memory.ranked(user_id)],
    })
