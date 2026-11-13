"""Clave de integración de n8n (ADR-020).

Las pocas rutas que n8n llama sin sesión de persona (respuesta de una ejecución, entradas de
fuera e incidencias) exigen ``N8N_CALLBACK_KEY`` en ``X-Platia-Integration-Key``. Se compara en
tiempo constante y cada rechazo queda en la auditoría.
"""
import hmac

from flask import current_app, request

from ..models import AuditAction
from .audit import audit

HEADER = "X-Platia-Integration-Key"


def integration_key_ok() -> bool:
    expected = current_app.config.get("N8N_CALLBACK_KEY") or ""
    given = request.headers.get(HEADER) or ""
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        audit(AuditAction.ACCESS_DENIED, "WARNING", details={"path": request.path, "reason": "integration_key"})
        return False
    return True
