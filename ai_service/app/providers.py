"""Proveedores de LLM detrás de una interfaz común (patrón LLM Factory, Capítulo 11).

- ``anthropic``: proveedor principal, con el SDK oficial de Anthropic.
- ``openai_compatible``: reserva opcional para cualquier API compatible con la de
  OpenAI (Azure OpenAI, OpenAI, Ollama, LM Studio). Solo se usa si se configura
  ``FALLBACK_LLM_BASE_URL`` y el backend lo pone en la cadena de un servicio.

Con ``LLM_GATEWAY_ENABLED`` (ADR-019), el proveedor ``anthropic`` habla con el gateway
corporativo en lugar de con Anthropic: mismo SDK y misma API, otra URL y otra clave, y
cabeceras ``X-Platia-*`` con la tarea, la persona y la correlación. La reserva directa
``openai_compatible`` se desactiva: todo lo que sale hacia un modelo pasa por el gateway.

Cada proveedor devuelve un ``ProviderResult`` con el texto y los tokens; los
errores se traducen a ``ProviderError`` indicando si tiene sentido probar con el
siguiente proveedor de la cadena.
"""
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import anthropic
import httpx
import structlog

from .settings import Settings

log = structlog.get_logger(__name__)


@dataclass
class ProviderResult:
    text: str
    model: str
    stop_reason: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Bloques completos de la respuesta (texto, tool_use y razonamiento con su firma):
    # el bucle de herramientas del backend los devuelve tal cual en el turno siguiente
    content: list[dict] = field(default_factory=list)


OnText = Callable[[str], Awaitable[None]] | None

_BLOCK_FIELDS = {
    "text": ("type", "text"),
    "tool_use": ("type", "id", "name", "input"),
    "thinking": ("type", "thinking", "signature"),
    "redacted_thinking": ("type", "data"),
}


def block_to_dict(block) -> dict | None:
    """Bloque del SDK -> dict con solo los campos que la API acepta de vuelta."""
    kind = getattr(block, "type", None)
    fields = _BLOCK_FIELDS.get(kind)
    if fields is None:
        return None
    return {f: getattr(block, f, None) for f in fields if getattr(block, f, None) is not None or f == "input"}


class ProviderError(Exception):
    """Fallo de un proveedor. ``fallback`` indica si conviene probar el siguiente."""

    def __init__(self, message: str, error_type: str, fallback: bool = True, status_code: int | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.fallback = fallback
        self.status_code = status_code


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings, client: "anthropic.AsyncAnthropic | None" = None):
        self._settings = settings
        self._client = client

    @property
    def via_gateway(self) -> bool:
        return self._settings.llm_gateway_enabled

    @property
    def configured(self) -> bool:
        if self._client is not None:
            return True
        if self.via_gateway:
            return bool(self._settings.llm_gateway_api_key)
        return bool(self._settings.anthropic_api_key)

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            options = {"max_retries": self._settings.llm_max_retries, "timeout": self._settings.llm_timeout_seconds}
            if self.via_gateway:
                # El SDK añade /v1/messages a la URL base y manda la clave como Bearer (el gateway
                # acepta también x-api-key)
                self._client = anthropic.AsyncAnthropic(api_key=self._settings.llm_gateway_api_key,
                                                        base_url=self._settings.llm_gateway_url, **options)
            else:
                self._client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key, **options)
        return self._client

    async def complete(self, *, model: str, system: str, messages: list[dict], max_tokens: int,
                       effort: str | None, json_schema: dict | None, timeout: float,
                       tools: list[dict] | None = None, on_text: OnText = None,
                       headers: dict[str, str] | None = None) -> ProviderResult:
        if not self.configured:
            missing = "LLM_GATEWAY_API_KEY" if self.via_gateway else "ANTHROPIC_API_KEY"
            raise ProviderError(f"{missing} no está configurada", "not_configured")
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            # El prompt de sistema es estable por servicio: se marca para la caché de
            # prompts (si es lo bastante largo, las llamadas siguientes cuestan ~10 %).
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
        }
        output_config: dict = {}
        if effort:
            output_config["effort"] = effort
        if json_schema:
            # Salida estructurada nativa: el texto devuelto es JSON válido según el esquema
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        if output_config:
            kwargs["output_config"] = output_config
        if tools:
            kwargs["tools"] = tools
        if headers:
            # Cabeceras del gateway (tarea, persona, correlación): Anthropic no las recibe
            kwargs["extra_headers"] = headers
        try:
            # Siempre en streaming: evita los cortes por tiempo en respuestas largas.
            # Con on_text, el texto se reenvía según llega (chat del copiloto).
            async with self._get_client().messages.stream(**kwargs, timeout=timeout) as stream:
                if on_text is not None:
                    async for event in stream:
                        if getattr(event, "type", None) == "text" and getattr(event, "text", ""):
                            await on_text(event.text)
                message = await stream.get_final_message()
        except anthropic.BadRequestError as exc:
            # Petición mal formada: el siguiente proveedor fallaría igual
            raise ProviderError(_short(exc), "bad_request", fallback=False, status_code=400) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderError("Tiempo de espera agotado", "timeout") from exc
        except anthropic.APIConnectionError as exc:
            target = "el gateway LLM" if self.via_gateway else "Anthropic"
            raise ProviderError(f"No se puede conectar con {target}", "connection") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(_short(exc), _status_type(exc.status_code), status_code=exc.status_code) from exc

        text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
        usage = message.usage
        return ProviderResult(
            text=text,
            model=message.model or model,
            stop_reason=message.stop_reason,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            content=[b for b in (block_to_dict(x) for x in message.content) if b is not None],
        )


class OpenAICompatibleProvider:
    """Reserva con la API de chat de OpenAI. No es para llamar a Claude."""

    name = "openai_compatible"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport

    @property
    def configured(self) -> bool:
        # Con el gateway activo no hay salida directa a otro proveedor (ADR-019)
        return bool(self._settings.fallback_base_url) and not self._settings.llm_gateway_enabled

    async def complete(self, *, model: str, system: str, messages: list[dict], max_tokens: int,
                       effort: str | None, json_schema: dict | None, timeout: float,
                       tools: list[dict] | None = None, on_text: OnText = None,
                       headers: dict[str, str] | None = None) -> ProviderResult:
        if not self.configured:
            raise ProviderError("FALLBACK_LLM_BASE_URL no está configurada", "not_configured")
        if tools or any(not isinstance(m.get("content"), str) for m in messages):
            # El bucle de herramientas usa el formato de Anthropic: la reserva genérica
            # no lo comparte, así que el agente no cambia de proveedor a mitad de tarea
            raise ProviderError("El proveedor de reserva no admite herramientas", "no_tool_support")
        if json_schema:
            # Sin salida estructurada nativa común a todos: instrucción en el prompt
            # (portable) y el backend valida el resultado (Capítulo 11).
            system = (f"{system}\n\nResponde exclusivamente con un objeto JSON válido que cumpla "
                      f"este esquema, sin texto adicional ni bloques de código:\n{json.dumps(json_schema)}")
        payload: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if json_schema:
            payload["response_format"] = {"type": "json_object"}
        headers = {}
        if self._settings.fallback_api_key:
            headers["Authorization"] = f"Bearer {self._settings.fallback_api_key}"
            headers["api-key"] = self._settings.fallback_api_key  # Azure OpenAI
        url = self._settings.fallback_base_url.rstrip("/") + "/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError("Tiempo de espera agotado", "timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("No se puede conectar con el proveedor de reserva", "connection") from exc
        if resp.status_code == 400:
            raise ProviderError("Petición rechazada por el proveedor de reserva", "bad_request",
                                fallback=False, status_code=400)
        if resp.status_code >= 300:
            raise ProviderError(f"Error {resp.status_code} del proveedor de reserva",
                                _status_type(resp.status_code), status_code=resp.status_code)
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        text = (choice.get("message") or {}).get("content") or ""
        if on_text is not None and text:
            await on_text(text)
        return ProviderResult(
            text=text,
            model=data.get("model") or model,
            stop_reason=choice.get("finish_reason"),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            content=[{"type": "text", "text": text}] if text else [],
        )


def _status_type(status: int | None) -> str:
    return {401: "authentication", 403: "permission", 404: "not_found", 413: "too_large",
            429: "rate_limited", 529: "overloaded"}.get(status or 0, "server_error" if (status or 0) >= 500
                                                       else f"http_{status}")


def _short(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc)
    return message[:300]
