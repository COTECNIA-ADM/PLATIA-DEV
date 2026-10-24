"""Proveedores de LLM detrás de una interfaz común (patrón LLM Factory, Capítulo 11).

- ``anthropic``: proveedor principal, con el SDK oficial de Anthropic.
- ``openai_compatible``: reserva opcional para cualquier API compatible con la de
  OpenAI (Azure OpenAI, OpenAI, Ollama, LM Studio). Solo se usa si se configura
  ``FALLBACK_LLM_BASE_URL`` y el backend lo pone en la cadena de un servicio.

Cada proveedor devuelve un ``ProviderResult`` con el texto y los tokens; los
errores se traducen a ``ProviderError`` indicando si tiene sentido probar con el
siguiente proveedor de la cadena.
"""
import json
from dataclasses import dataclass

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
    def configured(self) -> bool:
        return bool(self._settings.anthropic_api_key) or self._client is not None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(
                api_key=self._settings.anthropic_api_key,
                max_retries=self._settings.llm_max_retries,
                timeout=self._settings.llm_timeout_seconds,
            )
        return self._client

    async def complete(self, *, model: str, system: str, messages: list[dict], max_tokens: int,
                       effort: str | None, json_schema: dict | None, timeout: float) -> ProviderResult:
        if not self.configured:
            raise ProviderError("ANTHROPIC_API_KEY no está configurada", "not_configured")
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
        try:
            # Siempre en streaming: evita los cortes por tiempo en respuestas largas
            async with self._get_client().messages.stream(**kwargs, timeout=timeout) as stream:
                message = await stream.get_final_message()
        except anthropic.BadRequestError as exc:
            # Petición mal formada: el siguiente proveedor fallaría igual
            raise ProviderError(_short(exc), "bad_request", fallback=False, status_code=400) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderError("Tiempo de espera agotado", "timeout") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("No se puede conectar con Anthropic", "connection") from exc
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
        )


class OpenAICompatibleProvider:
    """Reserva con la API de chat de OpenAI. No es para llamar a Claude."""

    name = "openai_compatible"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._settings.fallback_base_url)

    async def complete(self, *, model: str, system: str, messages: list[dict], max_tokens: int,
                       effort: str | None, json_schema: dict | None, timeout: float) -> ProviderResult:
        if not self.configured:
            raise ProviderError("FALLBACK_LLM_BASE_URL no está configurada", "not_configured")
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
        return ProviderResult(
            text=(choice.get("message") or {}).get("content") or "",
            model=data.get("model") or model,
            stop_reason=choice.get("finish_reason"),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )


def _status_type(status: int | None) -> str:
    return {401: "authentication", 403: "permission", 404: "not_found", 413: "too_large",
            429: "rate_limited", 529: "overloaded"}.get(status or 0, "server_error" if (status or 0) >= 500
                                                       else f"http_{status}")


def _short(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc)
    return message[:300]
