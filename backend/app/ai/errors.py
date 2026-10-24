"""Errores de la capa de IA, con mensajes que se pueden mostrar al usuario."""
from ..errors import DomainError


class AIUnavailableError(DomainError):
    """El servicio de IA o todos los proveedores de la cadena están caídos."""

    status_code = 503
    error_type = "ai_unavailable"


class AIDisabledError(DomainError):
    status_code = 503
    error_type = "ai_disabled"


class AIRejectedError(DomainError):
    """El proveedor ha rechazado la petición (petición mal formada o rechazo del modelo)."""

    status_code = 422
    error_type = "ai_rejected"


class BudgetExceededError(DomainError):
    status_code = 429
    error_type = "budget_exceeded"


class GuardrailBlockedError(DomainError):
    status_code = 422
    error_type = "guardrail"
