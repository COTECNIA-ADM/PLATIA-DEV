"""Registro de módulos y acciones de permiso (Capítulo 7).

Cada ``require_permission(módulo, acción)`` se comprueba contra este registro al
importar el blueprint: un nombre de módulo mal escrito hace fallar el arranque
(y los tests) en lugar de dejar un endpoint protegido por un permiso que no
tiene nadie, o por el de otro módulo.
"""

MODULES: dict[str, set[str]] = {
    # --- operations
    "clients": {"read", "write", "delete"},
    "opportunities": {"read", "write", "delete", "manage", "export"},
    "documents": {"read", "upload", "write", "delete", "manage"},
    "proposals": {"read", "write", "delete", "manage", "approve", "send"},
    "templates": {"read", "write"},
    "portfolio": {"read", "write"},
    "talent": {"read", "write", "delete"},
    "alerts": {"read", "write"},
    "notifications": {"read"},
    "copilot": {"read", "write"},  # conversaciones y memoria propias (fase 5c)
    "reports": {"read", "generate"},
    # --- analytics
    "dashboards": {"read", "write"},  # también objetivos y pesos del mapa de oportunidad (fase 9a)
    "competitors": {"read", "write", "delete"},  # perfiles de competidores con DAFO (fase 9a)
    # --- admin
    "users": {"read", "write"},
    "roles": {"read", "write"},
    "llm_config": {"read", "write"},
    "prompts": {"read", "write"},
    "audit": {"read"},
    "health": {"read"},
    "tasks": {"read", "write"},
    "search": {"read", "write"},  # patrones del clasificador e índices (fase 5b)
    "agents": {"read", "write"},  # Agent Studio (fase 5c)
    # --- security
    "guardrails": {"read"},
}

# Módulos que tienen sentido en cada aplicación (para el editor de roles de Admin).
# Un módulo puede estar en varias: los permisos se guardan por rol y cada rol es de una app.
APP_MODULES: dict[str, tuple[str, ...]] = {
    "operations": ("clients", "opportunities", "documents", "proposals", "templates", "portfolio", "talent",
                   "alerts", "notifications", "copilot", "reports"),
    "analytics": ("dashboards", "competitors", "reports", "copilot"),
    "admin": ("users", "roles", "llm_config", "prompts", "audit", "health", "tasks", "search", "agents"),
    "security": ("audit", "alerts", "guardrails"),
}

# Clave especial: lista de módulos de IA, no acciones (Capítulo 6)
AI_MODULES = {"document_analyzer", "proposal_generator", "cv_analyzer", "copilot_chat", "analytics_assistant"}


class UnknownPermissionError(LookupError):
    pass


def check(module: str, action: str) -> None:
    if action not in MODULES.get(module, set()):
        raise UnknownPermissionError(
            f"Permiso desconocido '{module}.{action}'. Añádelo a app/security/registry.py."
        )


def validate_permissions(permissions: dict) -> list[str]:
    """Devuelve los errores de un diccionario de permisos de rol (vacío si es válido)."""
    errors = []
    for module, actions in (permissions or {}).items():
        if module == "ai_modules_access":
            errors += [f"ai_modules_access.{m}" for m in actions if m not in AI_MODULES]
            continue
        if module not in MODULES:
            errors.append(module)
            continue
        errors += [f"{module}.{a}" for a in actions if a not in MODULES[module]]
    return errors
