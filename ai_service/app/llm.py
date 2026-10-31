"""Ejecución de una petición a un LLM con cadena de reserva (Capítulo 11).

El backend envía la cadena de destinos ya resuelta (proveedor y modelo por
orden de preferencia, leída de su configuración). Aquí se recorre la cadena:
se salta un proveedor con el circuito abierto, se prueba el siguiente si uno
falla, y se devuelven *todos* los intentos con sus tokens y latencia para que el
backend registre cada llamada, también las fallidas.
"""
import json
import time
from dataclasses import asdict, dataclass, field

import structlog

from .circuit import CircuitBreaker
from .providers import ProviderError, ProviderResult

log = structlog.get_logger(__name__)


@dataclass
class Attempt:
    provider: str
    model: str
    success: bool
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    stop_reason: str | None = None
    error_type: str | None = None


@dataclass
class CompletionOutcome:
    attempts: list[Attempt] = field(default_factory=list)
    result: ProviderResult | None = None
    provider: str | None = None
    data: dict | list | None = None
    error: str | None = None
    rejected: bool = False  # error de la petición (400): no es culpa del proveedor
    is_fallback: bool = False  # la respuesta la dio un destino que no era el primero

    def to_dict(self) -> dict:
        return {
            "text": self.result.text if self.result else None,
            "data": self.data,
            "provider": self.provider,
            "model": self.result.model if self.result else None,
            "stop_reason": self.result.stop_reason if self.result else None,
            "content": self.result.content if self.result else None,
            "is_fallback": self.is_fallback,
            "attempts": [asdict(a) for a in self.attempts],
        }


def parse_json(text: str) -> dict | list:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0]
    return json.loads(cleaned)


async def complete(*, providers: dict, breaker: CircuitBreaker, targets: list[dict], system: str,
                   messages: list[dict], max_tokens: int, effort: str | None, json_schema: dict | None,
                   timeout: float, service_type: str, tools: list[dict] | None = None,
                   on_text=None, headers: dict[str, str] | None = None) -> CompletionOutcome:
    outcome = CompletionOutcome()
    streamed = {"any": False}

    async def relay(text: str) -> None:
        streamed["any"] = True
        await on_text(text)

    for position, target in enumerate(targets):
        if streamed["any"]:
            # La persona ya ha visto parte de la respuesta: otro modelo empezaría de cero
            break
        name, model = target["provider"], target["model"]
        provider = providers.get(name)
        if provider is None or not provider.configured:
            outcome.attempts.append(Attempt(name, model, False, error_type="not_configured"))
            continue
        if not breaker.is_available(name):
            outcome.attempts.append(Attempt(name, model, False, error_type="circuit_open"))
            continue

        convo = list(messages)
        # Un único reintento corrector si un proveedor sin salida estructurada nativa
        # devuelve JSON que no se puede leer (Capítulo 11)
        for json_try in range(2):
            started = time.monotonic()
            try:
                result = await provider.complete(model=model, system=system, messages=convo,
                                                 max_tokens=max_tokens, effort=effort,
                                                 json_schema=json_schema, timeout=timeout, tools=tools,
                                                 on_text=relay if on_text is not None else None,
                                                 headers=headers)
            except ProviderError as exc:
                latency = int((time.monotonic() - started) * 1000)
                outcome.attempts.append(Attempt(name, model, False, latency, error_type=exc.error_type))
                log.warning("llm_attempt_failed", service_type=service_type, provider=name, model=model,
                            error_type=exc.error_type, status=exc.status_code)
                if not exc.fallback:
                    outcome.rejected = True
                    outcome.error = str(exc)
                    return outcome
                if exc.error_type not in ("not_configured", "no_tool_support"):
                    breaker.record_failure(name)
                break  # siguiente proveedor de la cadena

            latency = int((time.monotonic() - started) * 1000)
            attempt = Attempt(name, model, True, latency, result.input_tokens, result.output_tokens,
                              result.cache_read_tokens, result.cache_write_tokens, result.stop_reason)
            outcome.attempts.append(attempt)
            breaker.record_success(name)

            if json_schema and result.stop_reason != "refusal":
                try:
                    outcome.data = parse_json(result.text)
                except (json.JSONDecodeError, IndexError):
                    log.warning("llm_json_parse_error", service_type=service_type, provider=name,
                                model=model, sample=result.text[:200])
                    if json_try == 0 and result.stop_reason != "max_tokens":
                        attempt.success = False
                        attempt.error_type = "invalid_json"
                        convo = [*messages, {"role": "assistant", "content": result.text or "(vacío)"},
                                 {"role": "user", "content": "Tu respuesta no era JSON válido. Devuelve "
                                  "solo el objeto JSON pedido, sin texto antes ni después."}]
                        continue
                    attempt.success = False
                    attempt.error_type = "invalid_json"
                    outcome.error = "La respuesta del modelo no es JSON válido"
                    return outcome
            outcome.result = result
            outcome.provider = name
            outcome.is_fallback = position > 0
            log.info("llm_completed", service_type=service_type, provider=name, model=result.model,
                     input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                     latency_ms=latency, fallback=len(outcome.attempts) > 1)
            return outcome

    outcome.error = ("La respuesta se interrumpió" if streamed["any"] else "Ningún proveedor de IA disponible")
    return outcome
