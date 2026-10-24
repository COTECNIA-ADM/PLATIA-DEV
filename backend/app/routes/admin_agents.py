"""Agent Studio (Capítulo 15): crear, configurar, probar y vigilar agentes desde Admin.

- Definiciones como datos: modelo (tipo de tarea de la pasarela), prompt
  ``agent.<slug>`` versionado, herramientas con su nivel de autonomía y límites.
- Cada cambio guarda una versión completa que se puede restaurar.
- ``POST /<id>/test``: prueba en modo sandbox con los permisos de quien prueba;
  las acciones que crean datos o gastan no se ejecutan (se simulan).
- ``GET /<id>/metrics``: iteraciones, herramientas, finalización, coste y
  latencia, con avisos cuando un valor se sale de lo razonable.

Todo exige ``X-App-Code: admin`` y queda auditado.
"""
import statistics
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, jsonify, request

from ..agents import definitions, tools
from ..agents.actor import Actor
from ..agents.runner import AgentSession
from ..ai import prompts as prompt_service
from ..api.common import check_version, iso, paginate, parse_body
from ..api.schemas import AgentIn, AgentPatch, AgentTestIn, AgentToolsIn
from ..errors import ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import AgentDefinition, AgentDefinitionVersion, AgentRun, AuditAction, LLMServiceConfig, utcnow
from ..security.audit import audit
from ..security.context import platform_guard, require_permission
from ..security.ratelimit import rate_limit
from .admin import _admin_app_only

admin_agents_bp = Blueprint("admin_agents", __name__, url_prefix="/api/admin/agents")

# Umbrales de las métricas (Capítulo 15): por encima o por debajo, el agente necesita revisión
THRESHOLDS = {"avg_iterations": 7, "avg_tool_calls": 8, "completion_rate": 0.8, "error_rate": 0.1,
              "p95_duration_ms": 60000, "approval_rejection_rate": 0.3}
DEFAULT_CONTEXT_TEMPLATE = ("Persona: {{user_name}} (rol {{role}}). Fecha: {{today}}.\n"
                            "Lo que recuerdas de esta persona:\n{{memories}}\n"
                            "Resumen de la conversación hasta ahora:\n{{conversation_summary}}\n"
                            "Elementos mencionados:\n{{references}}\n"
                            "Pantalla actual: {{screen}}")


def _changed(agent: AgentDefinition, **details) -> None:
    audit(AuditAction.AGENT_CONFIG_CHANGED, "INFO", user_id=g.security.user_id, resource_type="agent_definitions",
          resource_id=agent.id, details={"slug": agent.slug, **details})


def agent_dict(a: AgentDefinition, full: bool = False) -> dict:
    out = {"id": a.id, "slug": a.slug, "name": a.name, "description": a.description, "status": a.status,
           "agent_type": a.agent_type, "llm_service_type": a.llm_service_type, "prompt_name": a.prompt_name,
           "version_number": a.version_number, "version": a.row_version, "tool_count": len(a.tools),
           "updated_at": iso(a.updated_at)}
    if full:
        try:
            prompt = prompt_service.get_active(a.prompt_name)
            out["prompt"] = {"version": prompt.version, "system_prompt": prompt.system_prompt,
                             "context_template": prompt.user_template}
        except NotFoundError:
            out["prompt"] = None
        out.update(max_iterations=a.max_iterations, max_tool_calls=a.max_tool_calls,
                   timeout_seconds=a.timeout_seconds, intent_keywords=a.intent_keywords or [],
                   success_criteria=a.success_criteria, test_cases=a.test_cases or [],
                   tools=[{"tool_name": t.tool_name, "approval_level": t.approval_level, "sort_order": t.sort_order,
                           "config": t.config, "min_level": tools.get(t.tool_name).min_level
                           if tools.get(t.tool_name) else None} for t in a.tools])
    return out


def _get(agent_id: int) -> AgentDefinition:
    agent = db.session.get(AgentDefinition, agent_id)
    if agent is None:
        raise NotFoundError("Agente no encontrado.")
    return agent


def _check_service(service_type: str | None) -> None:
    if service_type and db.session.get(LLMServiceConfig, service_type) is None:
        raise ValidationError(f"El tipo de tarea '{service_type}' no existe en la configuración de modelos.")


# ------------------------------------------------------------------ Catálogo y CRUD
@admin_agents_bp.get("/tools")
@platform_guard
@_admin_app_only
@require_permission("agents", "read")
@rate_limit("RATE_LIMIT_READ")
def tool_catalog():
    return jsonify(items=tools.catalog(), max_tools_per_agent=tools.MAX_TOOLS_PER_AGENT)


@admin_agents_bp.get("")
@platform_guard
@_admin_app_only
@require_permission("agents", "read")
@rate_limit("RATE_LIMIT_READ")
def list_agents():
    stmt = db.select(AgentDefinition).order_by(AgentDefinition.name)
    if status := request.args.get("status"):
        stmt = stmt.where(AgentDefinition.status == status)
    return jsonify(paginate(stmt, agent_dict))


@admin_agents_bp.post("")
@platform_guard
@_admin_app_only
@require_permission("agents", "write")
@rate_limit("RATE_LIMIT_WRITE")
def create_agent():
    data = parse_body(AgentIn)
    if db.session.scalar(db.select(AgentDefinition.id).filter_by(slug=data.slug)) is not None:
        raise ConflictError("Ya existe un agente con ese identificador.")
    _check_service(data.llm_service_type)
    tool_items = definitions.validate_tools([t.model_dump() for t in data.tools])  # antes de escribir nada
    prompt_name = f"agent.{data.slug}"
    if data.system_prompt:
        prompt_service.publish(prompt_name, data.system_prompt, data.context_template or DEFAULT_CONTEXT_TEMPLATE,
                               author_id=g.security.user_id, notes="Versión inicial (Agent Studio)",
                               service_type=data.llm_service_type or "agent_copilot")
    values = data.model_dump(exclude={"tools", "system_prompt", "context_template"}, exclude_none=True,
                             mode="json")
    agent = AgentDefinition(**values, prompt_name=prompt_name, status="draft", created_by=g.security.user_id)
    db.session.add(agent)
    db.session.flush()
    definitions.set_tools(agent, tool_items)
    definitions.save_version(agent, g.security.user_id, notes="Creación")
    db.session.commit()
    _changed(agent, action="created")
    return jsonify(agent_dict(agent, full=True)), 201


@admin_agents_bp.get("/<int:agent_id>")
@platform_guard
@_admin_app_only
@require_permission("agents", "read")
@rate_limit("RATE_LIMIT_READ")
def get_agent(agent_id: int):
    return jsonify(agent_dict(_get(agent_id), full=True))


@admin_agents_bp.patch("/<int:agent_id>")
@platform_guard
@_admin_app_only
@require_permission("agents", "write")
@rate_limit("RATE_LIMIT_WRITE")
def update_agent(agent_id: int):
    agent = _get(agent_id)
    data = parse_body(AgentPatch)
    check_version(agent, data.version)
    changes = data.model_dump(exclude={"version", "notes"}, exclude_unset=True, mode="json")
    _check_service(changes.get("llm_service_type"))
    if changes.get("status") == "active":
        try:
            prompt_service.get_active(agent.prompt_name)
        except NotFoundError as exc:
            raise ValidationError(f"Publica antes el prompt '{agent.prompt_name}' (Admin > Prompts).") from exc
        if not agent.tools:
            raise ValidationError("Un agente activo necesita al menos una herramienta.")
    for field, value in changes.items():
        setattr(agent, field, value)
    definitions.save_version(agent, g.security.user_id, notes=data.notes)
    db.session.commit()
    _changed(agent, action="updated", fields=sorted(changes))
    return jsonify(agent_dict(agent, full=True))


@admin_agents_bp.put("/<int:agent_id>/tools")
@platform_guard
@_admin_app_only
@require_permission("agents", "write")
@rate_limit("RATE_LIMIT_WRITE")
def set_agent_tools(agent_id: int):
    agent = _get(agent_id)
    data = parse_body(AgentToolsIn)
    check_version(agent, data.version)
    definitions.set_tools(agent, [t.model_dump() for t in data.tools])
    agent.updated_at = utcnow()  # cuenta como edición: sube row_version
    definitions.save_version(agent, g.security.user_id, notes="Herramientas")
    db.session.commit()
    _changed(agent, action="tools", tools=[t.tool_name for t in data.tools])
    return jsonify(agent_dict(agent, full=True))


@admin_agents_bp.get("/<int:agent_id>/versions")
@platform_guard
@_admin_app_only
@require_permission("agents", "read")
@rate_limit("RATE_LIMIT_READ")
def agent_versions(agent_id: int):
    agent = _get(agent_id)
    rows = db.session.scalars(db.select(AgentDefinitionVersion).filter_by(agent_id=agent.id)
                              .order_by(AgentDefinitionVersion.version_number.desc())).all()
    return jsonify(items=[{"version_number": v.version_number, "notes": v.notes, "created_by": v.created_by,
                           "created_at": iso(v.created_at), "snapshot": v.snapshot} for v in rows])


@admin_agents_bp.post("/<int:agent_id>/versions/<int:number>/restore")
@platform_guard
@_admin_app_only
@require_permission("agents", "write")
@rate_limit("RATE_LIMIT_WRITE")
def restore_version(agent_id: int, number: int):
    agent = _get(agent_id)
    version = db.session.scalar(db.select(AgentDefinitionVersion).filter_by(agent_id=agent.id,
                                                                            version_number=number))
    if version is None:
        raise NotFoundError("Versión no encontrada.")
    definitions.restore(agent, version, g.security.user_id)
    agent.updated_at = utcnow()
    db.session.commit()
    _changed(agent, action="restored", from_version=number)
    return jsonify(agent_dict(agent, full=True))


# ------------------------------------------------------------------ Pruebas
@admin_agents_bp.post("/<int:agent_id>/test")
@platform_guard
@_admin_app_only
@require_permission("agents", "write")
@rate_limit("RATE_LIMIT_AI")
def test_agent(agent_id: int):
    """Ejecuta el agente en sandbox (también en borrador) y devuelve la traza completa."""
    agent = _get(agent_id)
    data = parse_body(AgentTestIn)
    actor = Actor.for_user(g.security.user_id)
    variables = {"user_name": "Prueba", "role": actor.role or "", "today": utcnow().strftime("%Y-%m-%d"),
                 "memories": "(prueba sin memoria)", "conversation_summary": "(prueba)", "references": "(ninguna)",
                 "screen": "(ninguna)"}
    session = AgentSession.start(agent, actor, data.input, variables=variables, mode="sandbox")
    trace, text = [], ""
    for event, payload in session.loop():
        if event == "delta":
            text += payload["text"]
            continue
        trace.append({"event": event, **payload})
    used = [c["name"] for c in session.run.tool_calls or []]
    expected = set(data.expect_tools)
    return jsonify({"run_id": session.run.run_uid, "text": session.text or text, "trace": trace,
                    "tools_used": used, "summary": session.summary(),
                    "available_tools": sorted(session.tools),
                    "check": {"expected_tools": sorted(expected), "missing": sorted(expected - set(used)),
                              "passed": expected <= set(used)} if expected else None})


# ------------------------------------------------------------------ Métricas
def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))]


@admin_agents_bp.get("/<int:agent_id>/metrics")
@platform_guard
@_admin_app_only
@require_permission("agents", "read")
@rate_limit("RATE_LIMIT_READ")
def agent_metrics(agent_id: int):
    agent = _get(agent_id)
    try:
        days = max(1, min(366, int(request.args.get("days", 30))))
    except ValueError as exc:
        raise ValidationError("'days' debe ser un número.") from exc
    runs = db.session.scalars(db.select(AgentRun).where(
        AgentRun.agent_id == agent.id, AgentRun.mode == "chat",
        AgentRun.created_at >= utcnow() - timedelta(days=days))).all()
    finished = [r for r in runs if r.status not in ("running", "awaiting_approval")]
    calls = [c for r in runs for c in r.tool_calls or []]
    approvals = [c for c in calls if c.get("level") == "approve" and "approved" in c]
    tool_usage: dict[str, dict] = {}
    for c in calls:
        row = tool_usage.setdefault(c.get("name") or "?", {"calls": 0, "errors": 0, "total_ms": 0})
        row["calls"] += 1
        row["errors"] += 0 if c.get("ok") else 1
        row["total_ms"] += c.get("ms") or 0

    def rate(predicate, rows) -> float | None:
        return round(sum(1 for r in rows if predicate(r)) / len(rows), 3) if rows else None

    total_cost = sum((Decimal(r.cost_usd or 0) for r in runs), Decimal(0))
    metrics = {
        "runs": len(runs),
        "completion_rate": rate(lambda r: r.status == "completed", finished),
        "error_rate": rate(lambda r: r.status == "failed", finished),
        "max_iterations_rate": rate(lambda r: r.status == "max_iterations", finished),
        "avg_iterations": round(statistics.mean(r.iterations for r in runs), 2) if runs else None,
        "avg_tool_calls": round(statistics.mean(len(r.tool_calls or []) for r in runs), 2) if runs else None,
        "avg_cost_usd": f"{total_cost / len(runs):.6f}" if runs else None,
        "p95_duration_ms": _p95([r.duration_ms for r in finished if r.duration_ms is not None]),
        "approval_rejection_rate": rate(lambda c: not c["approved"], approvals),
        "stop_reasons": {k: sum(r.stop_reason == k for r in finished) for k in {r.stop_reason for r in finished}},
        "tools": {name: {**v, "avg_ms": v["total_ms"] // v["calls"]} for name, v in tool_usage.items()},
    }
    alerts = []
    for key, limit in THRESHOLDS.items():
        value = metrics.get(key)
        if value is None:
            continue
        low_is_bad = key == "completion_rate"
        if (value < limit) if low_is_bad else (value > limit):
            alerts.append({"metric": key, "value": value, "threshold": limit})
    return jsonify({"agent_id": agent.id, "days": days, "metrics": metrics, "thresholds": THRESHOLDS,
                    "alerts": alerts})


@admin_agents_bp.get("/runs")
@platform_guard
@_admin_app_only
@require_permission("agents", "read")
@rate_limit("RATE_LIMIT_READ")
def list_runs():
    stmt = db.select(AgentRun).order_by(AgentRun.id.desc())
    if agent_id := request.args.get("agent_id"):
        if not agent_id.isdigit():
            raise ValidationError("agent_id debe ser un número.")
        stmt = stmt.where(AgentRun.agent_id == int(agent_id))
    if status := request.args.get("status"):
        stmt = stmt.where(AgentRun.status == status)
    if mode := request.args.get("mode"):
        stmt = stmt.where(AgentRun.mode == mode)
    return jsonify(paginate(stmt, lambda r: {
        "run_id": r.run_uid, "agent_id": r.agent_id, "agent_version": r.agent_version, "user_id": r.user_id,
        "mode": r.mode, "status": r.status, "stop_reason": r.stop_reason, "iterations": r.iterations,
        "tool_calls": r.tool_calls or [], "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
        "cost_usd": f"{Decimal(r.cost_usd or 0):.6f}", "duration_ms": r.duration_ms, "error": r.error,
        "created_at": iso(r.created_at)}))
