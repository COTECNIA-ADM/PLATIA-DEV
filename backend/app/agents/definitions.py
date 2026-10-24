"""Agentes definidos como datos (Agent Studio, Capítulo 15).

Una definición dice qué modelo (tipo de tarea de la pasarela), qué prompt
(``agent.<slug>``), qué herramientas con qué nivel de autonomía y qué límites.
Cada cambio guarda una copia completa (versión) que se puede restaurar.
"""
from ..errors import NotFoundError, ValidationError
from ..extensions import db
from ..models import AgentDefinition, AgentDefinitionVersion, AgentToolAssignment
from . import tools as tool_registry

SNAPSHOT_FIELDS = ("slug", "name", "description", "status", "agent_type", "llm_service_type", "prompt_name",
                   "max_iterations", "max_tool_calls", "timeout_seconds", "intent_keywords", "success_criteria",
                   "test_cases")


def snapshot(agent: AgentDefinition) -> dict:
    return {**{f: getattr(agent, f) for f in SNAPSHOT_FIELDS},
            "tools": [{"tool_name": t.tool_name, "approval_level": t.approval_level, "sort_order": t.sort_order,
                       "config": t.config} for t in sorted(agent.tools, key=lambda t: t.sort_order)]}


def by_slug(slug: str, *, active_only: bool = True) -> AgentDefinition:
    agent = db.session.scalar(db.select(AgentDefinition).filter_by(slug=slug))
    if agent is None or (active_only and agent.status != "active"):
        raise NotFoundError(f"El agente '{slug}' no existe o no está activo.")
    return agent


def validate_tools(items: list[dict]) -> list[dict]:
    """Herramientas conocidas, sin repetir, como mucho 12 y nunca por debajo de su nivel mínimo."""
    if len(items) > tool_registry.MAX_TOOLS_PER_AGENT:
        raise ValidationError(f"Un agente puede tener como mucho {tool_registry.MAX_TOOLS_PER_AGENT} herramientas: "
                              "con más, el modelo elige peor. Divide el trabajo en dos agentes.")
    seen, out = set(), []
    for i, item in enumerate(items):
        spec = tool_registry.get(item["tool_name"])
        if spec is None:
            raise ValidationError(f"La herramienta '{item['tool_name']}' no existe.")
        if spec.name in seen:
            raise ValidationError(f"La herramienta '{spec.name}' está repetida.")
        seen.add(spec.name)
        level = item.get("approval_level") or spec.min_level
        if spec.effective_level(level) != level:
            raise ValidationError(f"'{spec.name}' crea datos o tiene coste: su nivel mínimo es '{spec.min_level}'.")
        out.append({"tool_name": spec.name, "approval_level": level, "sort_order": item.get("sort_order", i),
                    "config": item.get("config")})
    return out


def set_tools(agent: AgentDefinition, items: list[dict]) -> None:
    items = validate_tools(items)
    agent.tools.clear()
    db.session.flush()
    for item in items:
        agent.tools.append(AgentToolAssignment(**item))


def save_version(agent: AgentDefinition, author_id: int | None, notes: str | None = None) -> AgentDefinitionVersion:
    """Guarda la definición tal como queda (no hace commit)."""
    db.session.flush()
    last = db.session.scalar(db.select(db.func.max(AgentDefinitionVersion.version_number))
                             .filter_by(agent_id=agent.id)) or 0
    agent.version_number = last + 1
    version = AgentDefinitionVersion(agent_id=agent.id, version_number=last + 1, snapshot=snapshot(agent),
                                     notes=notes, created_by=author_id)
    db.session.add(version)
    return version


def restore(agent: AgentDefinition, version: AgentDefinitionVersion, author_id: int | None) -> None:
    data = dict(version.snapshot)
    tools = data.pop("tools", [])
    data.pop("slug", None)
    for field, value in data.items():
        setattr(agent, field, value)
    set_tools(agent, tools)
    save_version(agent, author_id, notes=f"Restaurada la versión {version.version_number}")


def runtime_tools(agent: AgentDefinition, actor) -> list[tuple[tool_registry.ToolSpec, str]]:
    """Herramientas que el agente puede usar *con esta persona*: las asignadas que sus
    permisos permiten, con su nivel efectivo. Las demás ni se ofrecen al modelo."""
    out = []
    for assignment in sorted(agent.tools, key=lambda t: t.sort_order):
        spec = tool_registry.get(assignment.tool_name)
        if spec is not None and spec.allowed_for(actor):
            out.append((spec, spec.effective_level(assignment.approval_level)))
    return out
