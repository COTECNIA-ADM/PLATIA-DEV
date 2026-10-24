"""El copiloto: chat en streaming que decide cómo responder (Capítulo 14).

Para cada mensaje:

1. Guardarraíles de entrada (inyección, peticiones maliciosas, datos personales).
2. Menciones (``@oportunidad:12``, ``@doc:7``, ``@cliente:3``, ``@propuesta:5``):
   se resuelven con los permisos de la persona y se pasan como contexto.
3. Intención con el clasificador de dos capas de la fase 5b:
   - ``OFF_TOPIC``: mensaje orientativo, sin coste.
   - ``CHAT_RAG``: respuesta con citas sobre los documentos (RAG).
   - ``AGENT_TOOLS``: el agente ``copiloto`` con sus herramientas.
   - ``WORKFLOW``: el agente especialista del encargo, que propone las acciones
     y la persona las confirma (nada que cree datos o gaste se ejecuta solo).
4. Historial: los últimos turnos completos y un resumen de los anteriores.
5. Memoria: lo más útil que se sabe de la persona va en el contexto; al terminar,
   una tarea extrae lo nuevo que merezca recordarse.

Todo se emite como eventos que la ruta envía por SSE.
"""
import re
from datetime import datetime, timezone

import structlog
from flask import current_app

from ..ai import guardrails, rag
from ..ai.errors import GuardrailBlockedError
from ..errors import DomainError, NotFoundError
from ..extensions import db
from ..models import (AgentDefinition, AgentRun, AuditAction, ChatConversation, ChatMessage, Client, Document,
                      Opportunity, Proposal, User, utcnow)
from ..search import intent as intent_service
from ..search.router import OFF_TOPIC_MESSAGE, log_query
from ..security.audit import audit
from . import definitions, memory
from .actor import Actor
from .runner import AgentSession

log = structlog.get_logger(__name__)
MENTION = re.compile(r"@(oportunidad|doc|documento|cliente|propuesta):(\d{1,9})\b", re.IGNORECASE)
WORKFLOW_AGENTS = {"analyze_opportunity": "analista_documental", "analyze_document": "analista_documental",
                   "summarize": "analista_documental", "generate_proposal": "preparador_propuestas"}
DEFAULT_AGENT = "copiloto"


# ------------------------------------------------------------------ Conversaciones
def get_conversation(conversation_id: int, user_id: int) -> ChatConversation:
    conv = db.session.get(ChatConversation, conversation_id)
    if conv is None or not conv.is_active or conv.user_id != user_id:  # solo su dueño la ve
        raise NotFoundError("Conversación no encontrada.")
    return conv


def conversation_dict(c: ChatConversation) -> dict:
    from ..api.common import iso

    return {"id": c.id, "title": c.title, "message_count": c.message_count, "has_summary": bool(c.summary),
            "last_message_at": iso(c.last_message_at), "created_at": iso(c.created_at)}


def message_dict(m: ChatMessage) -> dict:
    from ..api.common import iso

    return {"id": m.id, "role": m.role, "content": m.content, "intent": m.intent, "run_id": m.agent_run_uid,
            "meta": m.meta or {}, "created_at": iso(m.created_at)}


def _save(conv: ChatConversation, role: str, content: str, **fields) -> ChatMessage:
    msg = ChatMessage(conversation_id=conv.id, role=role, content=content, **fields)
    db.session.add(msg)
    conv.message_count = (conv.message_count or 0) + 1
    conv.last_message_at = utcnow()
    if role == "user" and conv.message_count == 1:
        conv.title = (content[:80] + ("…" if len(content) > 80 else "")).replace("\n", " ")
    db.session.commit()
    return msg


# ------------------------------------------------------------------ Menciones
def resolve_mentions(text: str, actor: Actor) -> tuple[list[dict], list[str]]:
    """Devuelve las referencias que la persona puede ver y avisos de las que no."""
    found, warnings, seen = [], [], set()
    viewer = actor.viewer
    for kind, raw in MENTION.findall(text):
        kind, ref_id = kind.lower(), int(raw)
        if (kind, ref_id) in seen or len(found) >= 5:
            continue
        seen.add((kind, ref_id))
        item = None
        if kind == "oportunidad" and actor.can("opportunities", "read"):
            o = db.session.get(Opportunity, ref_id)
            if o is not None and o.is_active:
                item = {"kind": "opportunity", "id": o.id, "title": o.title, "code": o.code, "status": o.status}
        elif kind in ("doc", "documento") and actor.can("documents", "read"):
            d = db.session.get(Document, ref_id)
            if d is not None and d.is_active and viewer.can_view(d):
                item = {"kind": "document", "id": d.id, "title": d.title, "doc_type": d.doc_type}
        elif kind == "cliente" and actor.can("clients", "read"):
            c = db.session.get(Client, ref_id)
            if c is not None and c.is_active:
                item = {"kind": "client", "id": c.id, "title": c.name, "sector": c.sector}
        elif kind == "propuesta" and actor.can("proposals", "read"):
            p = db.session.get(Proposal, ref_id)
            if p is not None and p.is_active:
                item = {"kind": "proposal", "id": p.id, "title": p.title, "status": p.status}
        if item is None:
            warnings.append(f"No encuentro @{kind}:{ref_id} o no tienes acceso.")
        else:
            found.append(item)
    return found, warnings


def _references_text(refs: list[dict]) -> str:
    labels = {"opportunity": "Oportunidad", "document": "Documento", "client": "Cliente", "proposal": "Propuesta"}
    return "\n".join(f"- {labels[r['kind']]} id={r['id']}: {r['title']}" for r in refs)


# ------------------------------------------------------------------ Historial
def history_messages(conv: ChatConversation, exclude_id: int | None = None) -> list[dict]:
    """Últimos turnos completos (texto) desde lo que no cubre el resumen."""
    turns = current_app.config.get("COPILOT_HISTORY_TURNS", 10)
    stmt = db.select(ChatMessage).filter_by(conversation_id=conv.id)
    if conv.summarized_until_id:
        stmt = stmt.where(ChatMessage.id > conv.summarized_until_id)
    if exclude_id:
        stmt = stmt.where(ChatMessage.id != exclude_id)
    rows = db.session.scalars(stmt.order_by(ChatMessage.id.desc()).limit(turns * 2)).all()[::-1]
    out: list[dict] = []
    for m in rows:
        content = m.content.strip() or "(sin texto)"
        if out and out[-1]["role"] == m.role:  # la API exige turnos alternos
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": m.role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if out and out[-1]["role"] == "user":  # el mensaje nuevo va después
        out.pop()
    return out


def _variables(actor: Actor, conv: ChatConversation, refs: list[dict], screen: str) -> dict:
    user = db.session.get(User, actor.user_id)
    return {
        "user_name": user.full_name if user else "",
        "role": actor.role or "",
        "today": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "memories": memory.for_prompt(actor.user_id) or "(ninguna todavía)",
        "conversation_summary": conv.summary or "(conversación nueva)",
        "references": _references_text(refs) or "(ninguna)",
        "screen": screen or "(ninguna)",
    }


# ------------------------------------------------------------------ Punto de entrada
def check_message(text: str, user_id: int) -> str:
    result = guardrails.check_input(text, max_chars=current_app.config.get("COPILOT_MAX_MESSAGE_CHARS", 4000))
    if result.blocked:
        audit(AuditAction.AI_REQUEST_BLOCKED, "WARNING", user_id=user_id,
              details={"reasons": result.reasons, "length": len(text), "channel": "copilot"})
        raise GuardrailBlockedError("El mensaje no se puede procesar: " + result.user_message)
    return result.text


def pick_agent(intent: intent_service.IntentResult) -> AgentDefinition:
    slug = WORKFLOW_AGENTS.get(intent.subtype, DEFAULT_AGENT) if intent.intent == "WORKFLOW" else DEFAULT_AGENT
    try:
        return definitions.by_slug(slug)
    except NotFoundError:
        return definitions.by_slug(DEFAULT_AGENT)


def respond(conv_id: int, actor: Actor, text: str, *, opportunity_id: int | None = None,
            document_ids: list[int] | None = None):
    """Generador de eventos de una respuesta del copiloto. ``text`` ya pasó ``check_message``."""
    conv = get_conversation(conv_id, actor.user_id)
    # Un mensaje nuevo deja sin efecto las acciones que esperaban confirmación aquí
    db.session.execute(db.update(AgentRun).where(AgentRun.conversation_id == conv.id,
                                                 AgentRun.status == "awaiting_approval")
                       .values(status="cancelled", stop_reason="superseded", state=None, pending=None,
                               finished_at=utcnow()))
    refs, warnings = resolve_mentions(text, actor)
    user_msg = _save(conv, "user", text, meta={"references": refs} if refs else None)
    for w in warnings:
        yield "notice", {"message": w}

    screen = ""
    if opportunity_id:
        opp = db.session.get(Opportunity, opportunity_id)
        if opp is not None and opp.is_active and actor.can("opportunities", "read"):
            screen = f"La persona está viendo la oportunidad id={opp.id}: «{opp.title[:200]}»."
            refs.append({"kind": "opportunity", "id": opp.id, "title": opp.title, "code": opp.code,
                         "status": opp.status})
    result = intent_service.classify(text, actor.user_id, context=screen)
    yield "intent", result.to_dict()
    log_query("copilot", text, user_id=actor.user_id, result=result, engine_name="copilot")

    if result.intent == "OFF_TOPIC" and not refs:
        yield "delta", {"text": OFF_TOPIC_MESSAGE}
        msg = _save(conv, "assistant", OFF_TOPIC_MESSAGE, intent=result.intent)
        yield "done", {"status": "completed", "text": OFF_TOPIC_MESSAGE, "message_id": msg.id}
        return

    doc_ids = list(document_ids or []) + [r["id"] for r in refs if r["kind"] == "document"]
    if (result.intent == "CHAT_RAG" and actor.can("documents", "read") and actor.has_ai("document_analyzer")
            and not any(r["kind"] != "document" for r in refs)):
        yield from _rag(conv, actor, text, result, doc_ids or None, user_msg.id)
        return

    agent = pick_agent(result)
    yield "agent", {"slug": agent.slug, "name": agent.name}
    session = AgentSession.start(agent, actor, text, history=history_messages(conv, exclude_id=user_msg.id),
                                 variables=_variables(actor, conv, refs, screen), conversation_id=conv.id)
    yield from _relay(conv, session, session.loop(), intent=result.intent)


def _rag(conv: ChatConversation, actor: Actor, text: str, result, doc_ids, exclude_id: int):
    history = history_messages(conv, exclude_id=exclude_id)
    try:
        answer = rag.ask(actor.viewer, text, document_ids=doc_ids, history=history[-6:])
    except DomainError as exc:
        yield "error", {"message": exc.message}
        _save(conv, "assistant", exc.message, intent=result.intent, meta={"error": True})
        return
    yield "rag_answer", {"sources": answer.get("sources") or [], "citations": answer.get("citations") or [],
                         "sufficient_context": answer.get("sufficient_context")}
    yield "delta", {"text": answer["answer"]}
    msg = _save(conv, "assistant", answer["answer"], intent=result.intent,
                meta={"sources": answer.get("sources") or [], "usage_log_id": answer.get("usage_log_id")})
    yield "done", {"status": "completed", "text": answer["answer"], "message_id": msg.id}
    after_exchange(conv)


def _relay(conv: ChatConversation, session: AgentSession, events, *, intent: str | None = None):
    """Reenvía los eventos del agente y guarda la respuesta al terminar o al pausarse."""
    tools_used = []
    for event, data in events:
        if event == "tool_call":
            tools_used.append({"name": data["name"], "title": data.get("title"), "summary": data.get("summary")})
        if event in ("done", "approval_required", "error"):
            text = session.text.strip()
            meta = {"tools": tools_used} if tools_used else {}
            if event == "approval_required":
                meta["approval"] = {"run_id": data["run_id"], "actions": data["actions"], "status": "pending"}
            if event == "error":
                meta["error"] = True
                text = text if not data.get("retract") else ""
                text = text or data["message"]
            msg = _save(conv, "assistant", text or "(sin texto)", intent=intent, agent_run_uid=session.run.run_uid,
                        meta=meta or None)
            yield event, {**data, "message_id": msg.id}
            if event == "done":
                after_exchange(conv)
            continue
        yield event, data


def resume(conv_id: int, session: AgentSession, approved: bool, comment: str | None):
    """Continúa una ejecución pausada tras la decisión de la persona."""
    conv = get_conversation(conv_id, session.actor.user_id)
    previous = db.session.scalar(db.select(ChatMessage).filter_by(conversation_id=conv.id,
                                                                  agent_run_uid=session.run.run_uid)
                                 .order_by(ChatMessage.id.desc()).limit(1))
    if previous is not None and previous.meta and previous.meta.get("approval"):
        meta = dict(previous.meta)
        meta["approval"] = {**meta["approval"], "status": "approved" if approved else "rejected"}
        previous.meta = meta
        db.session.commit()
    yield from _relay(conv, session, session.approve(approved, comment))


def after_exchange(conv: ChatConversation) -> None:
    """Tareas en segundo plano tras un intercambio: memoria y resumen del historial."""
    from ..queue import PRIORITY_MAINTENANCE, enqueue
    from ..tasks.agents import extract_memories, summarize_conversation

    cfg = current_app.config
    every = cfg.get("MEMORY_EXTRACT_EVERY", 2)
    if every and (conv.message_count // 2) % every == 0:
        enqueue(extract_memories, conv.id, priority=PRIORITY_MAINTENANCE)
    pending = db.session.scalar(db.select(db.func.count()).select_from(ChatMessage).where(
        ChatMessage.conversation_id == conv.id, ChatMessage.id > (conv.summarized_until_id or 0)))
    if pending > cfg.get("COPILOT_HISTORY_TURNS", 10) * 2 + cfg.get("COPILOT_SUMMARY_BATCH", 10):
        enqueue(summarize_conversation, conv.id, priority=PRIORITY_MAINTENANCE)


def summarize(conv_id: int) -> bool:
    """Resume los turnos que ya no van completos y avanza ``summarized_until_id``."""
    from ..ai import gateway

    conv = db.session.get(ChatConversation, conv_id)
    if conv is None or not conv.is_active:
        return False
    keep = current_app.config.get("COPILOT_HISTORY_TURNS", 10) * 2
    rows = db.session.scalars(db.select(ChatMessage).where(
        ChatMessage.conversation_id == conv.id, ChatMessage.id > (conv.summarized_until_id or 0))
        .order_by(ChatMessage.id)).all()
    old = rows[:-keep] if len(rows) > keep else []
    if not old:
        return False
    transcript = "\n".join(f"{'Persona' if m.role == 'user' else 'Copiloto'}: {m.content[:2000]}" for m in old)
    result = gateway.run("chat_summary", variables={"previous_summary": conv.summary or "(ninguno)",
                                                    "conversation": transcript}, user_id=conv.user_id)
    checked = guardrails.check_output(result.text)
    if checked.blocked:
        return False
    conv.summary = checked.text.strip()[:6000]
    conv.summarized_until_id = old[-1].id
    db.session.commit()
    return True
