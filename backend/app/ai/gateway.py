"""Punto de paso obligado de toda llamada a un LLM (patrón LLM Factory, Capítulo 11).

Para cada llamada:

1. Lee la configuración del tipo de tarea (modelo, reserva, tokens, esfuerzo).
2. Aplica los presupuestos (aviso, frenado o bloqueo).
3. Carga la versión activa del prompt y sustituye las variables.
4. Pide la respuesta al servicio de IA con la cadena de modelos.
5. Registra en ``llm_usage_log`` cada intento, también los fallidos, con tokens,
   coste calculado con la tabla de precios, latencia, versión y hash del prompt.

Ningún otro código del backend llama al servicio de IA para generar texto: así
no hay llamadas sin registrar ni costes invisibles.
"""
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal

import structlog
from flask import current_app, g, has_request_context

from ..extensions import db
from ..models import LLMServiceConfig, LLMUsageLog
from . import budget, prompts
from .client import AIServiceError, get_ai_client
from .errors import AIDisabledError, AIRejectedError, AIUnavailableError
from .pricing import cost_usd

log = structlog.get_logger(__name__)
OUTPUT_SAMPLE_CHARS = 500


@dataclass
class AIResult:
    text: str
    data: dict | list | None
    usage_log_id: int
    provider: str
    model: str
    prompt_name: str
    prompt_version: int
    cost_usd: Decimal
    latency_ms: int
    is_fallback: bool
    stop_reason: str | None
    correlation_id: str


def get_config(service_type: str) -> LLMServiceConfig:
    if not current_app.config.get("AI_ENABLED", True):
        raise AIDisabledError("Las funciones de IA están desactivadas en esta instalación.")
    config = db.session.get(LLMServiceConfig, service_type)
    if config is None or not config.is_active:
        raise AIDisabledError(f"El servicio de IA '{service_type}' está desactivado.")
    return config


def _request_id() -> str | None:
    return g.get("request_id") if has_request_context() else None


def _log_attempts(attempts: list[dict], *, service_type: str, prompt: prompts.ActivePrompt, user_id: int | None,
                  correlation_id: str, text: str | None, is_fallback: bool) -> list[LLMUsageLog]:
    rows = []
    for i, att in enumerate(attempts):
        last_success = att.get("success") and i == len(attempts) - 1
        row = LLMUsageLog(
            service_type=service_type, provider=att["provider"], model_name=att["model"], prompt_id=prompt.id,
            input_tokens=att.get("input_tokens") or 0, output_tokens=att.get("output_tokens") or 0,
            cache_read_tokens=att.get("cache_read_tokens") or 0, cache_write_tokens=att.get("cache_write_tokens") or 0,
            cost_usd=cost_usd(att["provider"], att["model"], att.get("input_tokens") or 0,
                              att.get("output_tokens") or 0, att.get("cache_read_tokens") or 0,
                              att.get("cache_write_tokens") or 0),
            latency_ms=att.get("latency_ms"), success=bool(att.get("success")), error_type=att.get("error_type"),
            stop_reason=att.get("stop_reason"), is_fallback=bool(last_success and is_fallback),
            prompt_hash=prompt.content_hash, user_id=user_id, request_id=_request_id(),
            correlation_id=correlation_id,
            output_sample=(text or "")[:OUTPUT_SAMPLE_CHARS] if last_success else None,
        )
        db.session.add(row)
        rows.append(row)
    db.session.flush()
    return rows


def run(service_type: str, *, variables: dict | None = None, user_id: int | None = None,
        prompt_name: str | None = None, history: list[dict] | None = None, json_schema: dict | None = None,
        correlation_id: str | None = None, max_tokens: int | None = None) -> AIResult:
    """Ejecuta una tarea de IA. Hace commit del registro de uso (también si falla)."""
    config = get_config(service_type)
    budget.check(service_type, user_id)
    prompt = prompts.get_active(prompt_name or config.prompt_name or service_type)
    system, user_message = prompt.render(variables or {})
    messages = [*(history or [])]
    if user_message:
        messages.append({"role": "user", "content": user_message})
    correlation_id = correlation_id or str(uuid.uuid4())
    payload = {
        "service_type": service_type, "targets": config.targets(), "system": system, "messages": messages,
        "max_tokens": max_tokens or config.max_tokens, "effort": config.effort, "json_schema": json_schema,
        "timeout_seconds": current_app.config.get("AI_REQUEST_TIMEOUT", 180), "correlation_id": correlation_id,
    }
    started = time.monotonic()
    try:
        body = get_ai_client().complete(payload)
    except AIServiceError as exc:
        attempts = exc.body.get("attempts") or []
        if not attempts:
            # Ni siquiera se llegó a un proveedor: se registra igualmente el fallo
            attempts = [{"provider": config.provider, "model": config.model_name, "success": False,
                         "error_type": "ai_service_unreachable" if exc.status is None else f"http_{exc.status}"}]
        _log_attempts(attempts, service_type=service_type, prompt=prompt, user_id=user_id,
                      correlation_id=correlation_id, text=None, is_fallback=False)
        db.session.commit()
        log.warning("ai_call_failed", service_type=service_type, status=exc.status, error=str(exc))
        if exc.status == 422:
            raise AIRejectedError("El proveedor de IA ha rechazado la petición.") from exc
        raise AIUnavailableError("La IA no está disponible en este momento. Inténtalo de nuevo más tarde.") from exc

    rows = _log_attempts(body.get("attempts") or [], service_type=service_type, prompt=prompt, user_id=user_id,
                         correlation_id=correlation_id, text=body.get("text"),
                         is_fallback=bool(body.get("is_fallback")))
    db.session.commit()
    final = rows[-1]
    if body.get("stop_reason") == "refusal":
        raise AIRejectedError("El modelo no ha querido responder a esta petición.")
    return AIResult(
        text=body.get("text") or "", data=body.get("data"), usage_log_id=final.id,
        provider=body.get("provider") or final.provider, model=body.get("model") or final.model_name,
        prompt_name=prompt.name, prompt_version=prompt.version, cost_usd=sum((r.cost_usd for r in rows), Decimal(0)),
        latency_ms=int((time.monotonic() - started) * 1000), is_fallback=bool(body.get("is_fallback")),
        stop_reason=body.get("stop_reason"), correlation_id=correlation_id,
    )


def correlation_cost(correlation_id: str) -> Decimal:
    return Decimal(str(db.session.scalar(
        db.select(db.func.coalesce(db.func.sum(LLMUsageLog.cost_usd), 0))
        .where(LLMUsageLog.correlation_id == correlation_id)) or 0))
