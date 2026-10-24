"""Bucle de un agente: razonar, usar herramientas, observar y repetir (Capítulo 15).

El bucle vive en el backend, que es quien conoce a la persona, sus permisos y
los datos; el servicio de IA solo hace cada llamada al modelo (ADR-013).

Cada ejecución:

1. Ofrece al modelo solo las herramientas asignadas al agente que el rol de la
   persona permite.
2. En cada iteración pide un turno al modelo por la pasarela (streaming, coste
   y tokens registrados) y revisa el texto con los guardarraíles de salida.
3. Si el modelo pide herramientas: valida la entrada con Pydantic, comprueba otra
   vez el permiso y ejecuta las ``auto``/``notify``. Las ``approve`` no se
   ejecutan: la ejecución se pausa, guarda su estado en ``agent_runs`` y pide
   confirmación. La persona aprueba o rechaza y el bucle sigue donde estaba.
4. Termina cuando el modelo responde sin pedir herramientas, al llegar al límite
   de iteraciones, de llamadas o de tiempo, o si algo falla.

Los eventos que produce el generador (``(evento, datos)``) son los que el
copiloto envía por SSE: ``delta``, ``replace``, ``tool_call``, ``tool_result``,
``notice``, ``approval_required``, ``done`` y ``error``.
"""
import json
import time
import uuid
from datetime import timedelta
from decimal import Decimal

import structlog
from flask import current_app
from pydantic import ValidationError as PydanticValidationError

from ..ai import gateway, guardrails, prompts
from ..ai.errors import BudgetExceededError
from ..errors import ConflictError, DomainError, NotFoundError
from ..extensions import db
from ..models import AgentDefinition, AgentRun, AuditAction, utcnow
from ..security.audit import audit
from . import definitions
from .actor import Actor
from .tools import MAX_RESULT_CHARS, ToolSpec

log = structlog.get_logger(__name__)
REJECTED_MESSAGE = ("La persona ha rechazado esta acción{comment}. No la repitas: explica qué harías en su lugar "
                    "o pregunta cómo prefiere seguir.")


def context_block(agent: AgentDefinition, variables: dict) -> str:
    """Contexto de la conversación a partir de la plantilla de usuario del prompt del
    agente (persona, fecha, memoria...). Va en el primer mensaje, no en el sistema."""
    prompt = prompts.get_active(agent.prompt_name)
    _, rendered = prompt.render({name: variables.get(name, "") for name in prompts.variables_of(prompt.user_template)})
    return rendered.strip()


def _text_of(content: list[dict] | None) -> str:
    return "".join(b.get("text", "") for b in content or [] if b.get("type") == "text")


def _tool_result(tool_use_id: str, payload, is_error: bool = False) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + " …[recortado]"
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": text}
    if is_error:
        block["is_error"] = True
    return block


class AgentSession:
    """Una ejecución en curso (nueva o reanudada tras una aprobación)."""

    def __init__(self, agent: AgentDefinition, actor: Actor, run: AgentRun, messages: list[dict]):
        self.agent = agent
        self.actor = actor
        self.run = run
        self.messages = messages
        self.tools = {spec.name: (spec, level) for spec, level in definitions.runtime_tools(agent, actor)}
        self.started = time.monotonic()
        self.text = ""  # texto mostrado a la persona en esta ejecución (o tramo)
        self.system_prompt = prompts.get_active(agent.prompt_name).system_prompt

    # ---------------------------------------------------------------- creación
    @classmethod
    def start(cls, agent: AgentDefinition, actor: Actor, user_content: str, *, history: list[dict] | None = None,
              variables: dict | None = None, mode: str = "chat", conversation_id: int | None = None) -> "AgentSession":
        context = context_block(agent, variables or {})
        first = [{"type": "text", "text": f"<contexto>\n{context}\n</contexto>"}] if context else []
        messages = [*(history or [])]
        messages.append({"role": "user", "content": [*first, {"type": "text", "text": user_content}]})
        run = AgentRun(run_uid=str(uuid.uuid4()), agent_id=agent.id, agent_version=agent.version_number,
                       user_id=actor.user_id, conversation_id=conversation_id, mode=mode, status="running",
                       correlation_id=str(uuid.uuid4()), tool_calls=[])
        db.session.add(run)
        db.session.commit()
        return cls(agent, actor, run, messages)

    @staticmethod
    def claim(run_uid: str, actor: Actor) -> AgentRun:
        """Reclama una ejecución que espera aprobación. Solo una petición la consigue."""
        run = db.session.scalar(db.select(AgentRun).filter_by(run_uid=run_uid))
        if run is None or run.user_id != actor.user_id:
            raise NotFoundError("Ejecución no encontrada.")
        if run.status == "awaiting_approval" and run.expires_at and run.expires_at < utcnow():
            _expire(run)
            db.session.commit()
        if run.status != "awaiting_approval":
            raise ConflictError("Esta acción ya no espera confirmación (se resolvió o caducó).")
        claimed = db.session.execute(
            db.update(AgentRun).where(AgentRun.id == run.id, AgentRun.status == "awaiting_approval")
            .values(status="running").execution_options(synchronize_session=False)).rowcount
        db.session.commit()
        if claimed != 1:
            raise ConflictError("Esta acción ya se está resolviendo.")
        db.session.refresh(run)
        return run

    @classmethod
    def load(cls, run_id: int, actor: Actor) -> "AgentSession":
        run = db.session.get(AgentRun, run_id)
        agent = db.session.get(AgentDefinition, run.agent_id)
        return cls(agent, actor, run, list((run.state or {}).get("messages") or []))

    # ---------------------------------------------------------------- bucle
    def loop(self):
        agent, run = self.agent, self.run
        tool_defs = [spec.api_schema() for spec, _ in self.tools.values()] or None
        try:
            while True:
                if run.iterations >= agent.max_iterations:
                    yield from self._finish("max_iterations", "He llegado al límite de pasos para esta petición. "
                                                              "Dime cómo quieres seguir.")
                    return
                if time.monotonic() - self.started > agent.timeout_seconds:
                    yield from self._finish("timeout", "Esta petición está tardando demasiado; la he detenido.")
                    return
                run.iterations += 1
                db.session.commit()
                turn_text = ""
                stream = gateway.converse(agent.llm_service_type, prompt_name=agent.prompt_name,
                                          messages=self.messages, tools=tool_defs, user_id=run.user_id,
                                          correlation_id=run.correlation_id, stream=True)
                try:
                    while True:
                        delta = next(stream)
                        if not turn_text and self.text:
                            yield "delta", {"text": "\n\n"}  # separa el texto de cada iteración
                        turn_text += delta
                        yield "delta", {"text": delta}
                except StopIteration as done:
                    result = done.value
                run.input_tokens += result.input_tokens
                run.output_tokens += result.output_tokens
                run.cost_usd = Decimal(run.cost_usd or 0) + result.cost_usd
                db.session.commit()
                content = result.content or [{"type": "text", "text": result.text}]
                self.messages.append({"role": "assistant", "content": content})

                safe = yield from self._check_output(_text_of(content) or turn_text)
                if not safe:
                    return
                if result.stop_reason in ("max_tokens", "model_context_window_exceeded"):
                    yield from self._finish("max_tokens", "La respuesta era demasiado larga y se cortó.")
                    return
                calls = [b for b in content if b.get("type") == "tool_use"]
                if result.stop_reason != "tool_use" or not calls:
                    yield from self._finish("completed")
                    return
                results, pending = [], []
                for call in calls:
                    block = yield from self._handle_call(call, pending)
                    if block is not None:
                        results.append(block)
                if pending:
                    yield from self._pause(results, pending)
                    return
                self.messages.append({"role": "user", "content": results})
        except BudgetExceededError as exc:
            yield from self._fail("budget", str(exc))
        except DomainError as exc:
            yield from self._fail("error", exc.message)
        except Exception as exc:
            log.exception("agent_run_crashed", run=run.run_uid, agent=agent.slug)
            yield from self._fail("crash", "Ha fallado algo inesperado. Inténtalo de nuevo.", detail=type(exc).__name__)

    def approve(self, approved: bool, comment: str | None = None):
        """Ejecuta (o rechaza) las acciones pendientes y continúa el bucle."""
        state = self.run.state or {}
        results = list(state.get("results") or [])
        pending = list(self.run.pending or [])
        self.run.state, self.run.pending, self.run.expires_at = None, None, None
        for call in pending:
            if approved:
                spec, level = self.tools.get(call["name"], (None, None))
                if spec is None:  # le han quitado el permiso o la herramienta mientras tanto
                    results.append(_tool_result(call["id"], "Esta herramienta ya no está disponible.", True))
                    continue
                block = yield from self._execute(spec, level, call, approved=True)
                results.append(block)
            else:
                note = f" (motivo: {comment[:300]})" if comment else ""
                results.append(_tool_result(call["id"], REJECTED_MESSAGE.format(comment=note), True))
                self._record(call["name"], "approve", ok=False, ms=0, approved=False)
                yield "tool_result", {"id": call["id"], "name": call["name"], "ok": False, "rejected": True}
        audit(AuditAction.AI_AGENT_APPROVAL, "INFO", user_id=self.actor.user_id, resource_type="agent_runs",
              resource_id=self.run.run_uid, details={"approved": approved, "tools": [c["name"] for c in pending]})
        # Mismo orden que las llamadas originales
        order = {c["id"]: i for i, c in enumerate(state.get("calls") or [])}
        results.sort(key=lambda b: order.get(b["tool_use_id"], 0))
        self.messages.append({"role": "user", "content": results})
        yield from self.loop()

    # ---------------------------------------------------------------- herramientas
    def _handle_call(self, call: dict, pending: list[dict]):
        name = call.get("name")
        spec, level = self.tools.get(name, (None, None))
        if spec is None:
            self._record(name, None, ok=False, ms=0, error="not_available")
            return _tool_result(call["id"], f"La herramienta '{name}' no está disponible para esta persona.", True)
        if len(self.run.tool_calls or []) >= self.agent.max_tool_calls:
            return _tool_result(call["id"], "Se ha alcanzado el límite de herramientas de esta petición. "
                                            "Responde con lo que ya tienes.", True)
        try:
            data = spec.input_model.model_validate(call.get("input") or {})
        except PydanticValidationError as exc:
            self._record(name, level, ok=False, ms=0, error="invalid_input")
            errors = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
            return _tool_result(call["id"], f"Entrada no válida: {errors}", True)
        if level == "approve":
            if self.run.mode == "sandbox":
                self._record(name, level, ok=True, ms=0, simulated=True)
                yield "tool_call", {"id": call["id"], "name": name, "title": spec.title,
                                    "summary": spec.describe(data), "simulated": True}
                return _tool_result(call["id"], {"simulated": True, "message": "Modo de pruebas: la acción no se "
                                                 "ejecuta. En uso real la persona tendría que confirmarla."})
            pending.append({"id": call["id"], "name": name, "input": data.model_dump(mode="json"),
                            "title": spec.title, "summary": spec.describe(data)})
            return None
        return (yield from self._execute(spec, level, call, data=data))

    def _execute(self, spec: ToolSpec, level: str, call: dict, data=None, approved: bool | None = None):
        started = time.monotonic()
        if data is None:
            data = spec.input_model.model_validate(call.get("input") or {})
        yield "tool_call", {"id": call["id"], "name": spec.name, "title": spec.title, "summary": spec.describe(data)}
        try:
            if not spec.allowed_for(self.actor):  # el permiso se comprueba otra vez al ejecutar
                raise DomainError("Tu rol no permite esta acción.")
            payload = spec.handler(self.actor, data)
            ok, block = True, _tool_result(call["id"], payload)
        except DomainError as exc:
            db.session.rollback()
            payload = getattr(exc, "message", None) or str(exc)
            ok, block = False, _tool_result(call["id"], payload, True)
        except Exception as exc:
            db.session.rollback()
            log.exception("agent_tool_failed", tool=spec.name, run=self.run.run_uid)
            payload = "La herramienta ha fallado. Inténtalo de otra forma o informa a la persona."
            ok, block = False, _tool_result(call["id"], payload, True)
            payload = {"error": type(exc).__name__}
        ms = int((time.monotonic() - started) * 1000)
        self._record(spec.name, level, ok=ok, ms=ms, approved=approved)
        event = {"id": call["id"], "name": spec.name, "ok": ok, "ms": ms}
        if not ok:
            event["error"] = payload if isinstance(payload, str) else "error"
        yield "tool_result", event
        if ok and level in ("notify", "approve"):
            yield "notice", {"tool": spec.name, "message": (payload or {}).get("message") or f"Hecho: {spec.title}"}
        return block

    def _record(self, name, level, *, ok: bool, ms: int, **extra) -> None:
        calls = list(self.run.tool_calls or [])
        calls.append({"name": name, "level": level, "ok": ok, "ms": ms, "iteration": self.run.iterations,
                      **{k: v for k, v in extra.items() if v is not None}})
        self.run.tool_calls = calls

    # ---------------------------------------------------------------- salida y cierre
    def _check_output(self, turn_text: str):
        if not turn_text.strip():
            return True
        checked = guardrails.check_output(turn_text, self.system_prompt)
        if checked.blocked:
            audit(AuditAction.AI_OUTPUT_BLOCKED, "WARNING", user_id=self.actor.user_id, resource_type="agent_runs",
                  resource_id=self.run.run_uid, details={"reasons": checked.reasons})
            self.text = ""
            yield from self._fail("guardrail", "La respuesta generada no se puede mostrar por seguridad.", retract=True)
            return False
        self.text = "\n\n".join(p for p in (self.text, checked.text) if p)
        if checked.action != "allow":
            yield "replace", {"text": self.text}
        return True

    def _pause(self, results: list[dict], pending: list[dict]):
        ttl = current_app.config.get("AGENT_APPROVAL_TTL_MINUTES", 15)
        calls = [b for b in self.messages[-1]["content"] if b.get("type") == "tool_use"]
        run = self.run
        run.status, run.pending = "awaiting_approval", pending
        run.state = {"messages": self.messages, "results": results,
                     "calls": [{"id": c["id"], "name": c["name"]} for c in calls]}
        run.expires_at = utcnow() + timedelta(minutes=ttl)
        db.session.commit()
        yield "approval_required", {"run_id": run.run_uid, "expires_at": run.expires_at.isoformat() + "Z",
                                    "actions": [{k: p[k] for k in ("id", "name", "title", "summary", "input")}
                                                for p in pending]}

    def _finish(self, reason: str, message: str | None = None):
        run = self.run
        if message:
            yield "delta", {"text": ("\n\n" if self.text else "") + message}
            self.text = "\n\n".join(p for p in (self.text, message) if p)
        run.status = "completed" if reason == "completed" else ("max_iterations" if reason == "max_iterations"
                                                                 else "failed")
        run.stop_reason = reason
        self._close()
        yield "done", self.summary()

    def _fail(self, reason: str, message: str, detail: str | None = None, retract: bool = False):
        db.session.rollback()
        run = self.run
        run.status, run.stop_reason, run.error = "failed", reason, (detail or message)[:500]
        self._close()
        yield "error", {"message": message, "retract": retract, "run_id": run.run_uid}

    def _close(self) -> None:
        run = self.run
        run.state, run.pending, run.expires_at = None, None, None
        run.finished_at = utcnow()
        run.duration_ms = int((run.finished_at - run.created_at).total_seconds() * 1000)
        db.session.commit()
        log.info("agent_run_finished", run=run.run_uid, agent=self.agent.slug, status=run.status,
                 iterations=run.iterations, tools=len(run.tool_calls or []), cost=float(run.cost_usd or 0))

    def summary(self) -> dict:
        run = self.run
        return {"run_id": run.run_uid, "status": run.status, "stop_reason": run.stop_reason,
                "iterations": run.iterations, "tool_calls": len(run.tool_calls or []),
                "cost_usd": f"{Decimal(run.cost_usd or 0):.6f}", "text": self.text.strip()}


def _expire(run: AgentRun) -> None:
    run.status, run.stop_reason = "expired", "approval_timeout"
    run.state, run.pending = None, None
    run.finished_at = utcnow()


def expire_stale() -> int:
    """Caduca las ejecuciones que llevan demasiado esperando una aprobación."""
    rows = db.session.scalars(db.select(AgentRun).where(AgentRun.status == "awaiting_approval",
                                                        AgentRun.expires_at < utcnow())).all()
    for run in rows:
        _expire(run)
    db.session.commit()
    return len(rows)
