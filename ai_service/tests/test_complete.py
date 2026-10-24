import anthropic
import httpx
import httpx2

from app.circuit import CircuitBreaker
from app.providers import OpenAICompatibleProvider

from .conftest import API_HEADERS, make_settings


def _body(**overrides):
    body = {
        "service_type": "document_analysis",
        "targets": [{"provider": "anthropic", "model": "claude-sonnet-5-5"}],
        "system": "Eres un analista.",
        "messages": [{"role": "user", "content": "Analiza esto"}],
        "max_tokens": 500,
    }
    body.update(overrides)
    return body


def _api_error(status: int):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIStatusError(f"error {status}", response=httpx2.Response(status, request=req), body=None)


def test_complete_returns_text_and_usage(client, fake_anthropic):
    fake_anthropic.responses = ["Respuesta"]
    resp = client.post("/v1/complete", json=_body(effort="low"), headers=API_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == "Respuesta"  # los bloques de razonamiento no se devuelven
    assert body["provider"] == "anthropic" and body["is_fallback"] is False
    assert body["attempts"] == [{
        "provider": "anthropic", "model": "claude-sonnet-5-5", "success": True,
        "latency_ms": body["attempts"][0]["latency_ms"], "input_tokens": 120, "output_tokens": 40,
        "cache_read_tokens": 0, "cache_write_tokens": 0, "stop_reason": "end_turn", "error_type": None,
    }]
    call = fake_anthropic.calls[0]
    assert call["output_config"] == {"effort": "low"}
    # El prompt de sistema va marcado para la caché de prompts
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in call


def test_complete_requires_api_key(client):
    assert client.post("/v1/complete", json=_body()).status_code == 401


def test_complete_rejects_unknown_fields(client):
    resp = client.post("/v1/complete", json=_body(temperature=0.3), headers=API_HEADERS)
    assert resp.status_code == 422


def test_structured_output_is_parsed(client, fake_anthropic):
    fake_anthropic.responses = ['{"verdict": "GO", "confidence": 0.8}']
    schema = {"type": "object", "properties": {"verdict": {"type": "string"}}, "required": ["verdict"],
              "additionalProperties": False}
    resp = client.post("/v1/complete", json=_body(json_schema=schema), headers=API_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"] == {"verdict": "GO", "confidence": 0.8}
    assert fake_anthropic.calls[0]["output_config"]["format"] == {"type": "json_schema", "schema": schema}


def test_fallback_to_next_target_and_all_attempts_returned(client, fake_anthropic):
    fake_anthropic.responses = [_api_error(529), "Desde la reserva"]
    targets = [{"provider": "anthropic", "model": "claude-opus-5-5"},
               {"provider": "anthropic", "model": "claude-sonnet-5-5"}]
    resp = client.post("/v1/complete", json=_body(targets=targets), headers=API_HEADERS)
    body = resp.json()
    assert resp.status_code == 200
    assert body["text"] == "Desde la reserva" and body["is_fallback"] is True
    assert [(a["model"], a["success"], a["error_type"]) for a in body["attempts"]] == [
        ("claude-opus-5-5", False, "overloaded"), ("claude-sonnet-5-5", True, None)]


def test_bad_request_does_not_fall_back(client, fake_anthropic):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_anthropic.responses = [anthropic.BadRequestError("mal", response=httpx2.Response(400, request=req),
                                                          body=None)]
    targets = [{"provider": "anthropic", "model": "a"}, {"provider": "anthropic", "model": "b"}]
    resp = client.post("/v1/complete", json=_body(targets=targets), headers=API_HEADERS)
    assert resp.status_code == 422
    assert len(resp.json()["attempts"]) == 1


def test_all_targets_fail_returns_503_with_attempts(client, fake_anthropic):
    fake_anthropic.responses = [_api_error(500)]
    resp = client.post("/v1/complete", json=_body(), headers=API_HEADERS)
    assert resp.status_code == 503
    assert resp.json()["attempts"][0]["error_type"] == "server_error"


def test_unconfigured_fallback_provider_is_skipped(client, fake_anthropic):
    fake_anthropic.responses = ["ok"]
    targets = [{"provider": "openai_compatible", "model": "gpt-x"},
               {"provider": "anthropic", "model": "claude-haiku-5-5"}]
    resp = client.post("/v1/complete", json=_body(targets=targets), headers=API_HEADERS)
    assert resp.json()["attempts"][0]["error_type"] == "not_configured"
    assert resp.json()["text"] == "ok"


def test_circuit_opens_after_repeated_failures(client, fake_anthropic, runtime):
    fake_anthropic.responses = [_api_error(503)] * 3
    for _ in range(3):
        client.post("/v1/complete", json=_body(), headers=API_HEADERS)
    assert runtime.breaker.state("anthropic") == "open"
    resp = client.post("/v1/complete", json=_body(), headers=API_HEADERS)
    assert resp.status_code == 503
    assert resp.json()["attempts"][0]["error_type"] == "circuit_open"
    assert len(fake_anthropic.calls) == 3  # con el circuito abierto ya no se llama


def test_circuit_breaker_recovers():
    now = [0.0]
    breaker = CircuitBreaker(2, 30, 60, clock=lambda: now[0])
    breaker.record_failure("p")
    breaker.record_failure("p")
    assert breaker.state("p") == "open"
    now[0] = 61
    assert breaker.state("p") == "half_open" and breaker.is_available("p")
    breaker.record_success("p")
    breaker.record_success("p")
    assert breaker.state("p") == "closed"


def test_circuit_half_open_failure_reopens():
    now = [0.0]
    breaker = CircuitBreaker(1, 30, 60, clock=lambda: now[0])
    breaker.record_failure("p")
    now[0] = 61
    assert breaker.state("p") == "half_open"
    breaker.record_failure("p")
    assert breaker.state("p") == "open"


def test_failures_outside_window_do_not_count():
    now = [0.0]
    breaker = CircuitBreaker(2, 30, 60, clock=lambda: now[0])
    breaker.record_failure("p")
    now[0] = 40
    breaker.record_failure("p")
    assert breaker.state("p") == "closed"


def test_openai_compatible_provider_with_json_retry(client, runtime):
    replies = iter(["no es json", '{"ok": true}'])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "llama", "choices": [{"message": {"content": next(replies)},
                                         "finish_reason": "stop"}], "usage": {"prompt_tokens": 10,
                                                                              "completion_tokens": 5}})

    settings = make_settings(fallback_base_url="http://ollama:11434/v1")
    runtime.providers["openai_compatible"] = OpenAICompatibleProvider(settings, transport=httpx.MockTransport(handler))
    body = _body(targets=[{"provider": "openai_compatible", "model": "llama3"}],
                 json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}})
    resp = client.post("/v1/complete", json=body, headers=API_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"ok": True}
    assert [a["error_type"] for a in resp.json()["attempts"]] == ["invalid_json", None]
