"""Llamadas a Claude a través del gateway LLM corporativo (ADR-019)."""
import json

import anthropic
import httpx2  # el SDK de Anthropic 2.x usa httpx2

from app.main import app, get_settings
from app.providers import AnthropicProvider, OpenAICompatibleProvider

from .conftest import API_HEADERS, make_settings
from .test_health import _qdrant_ok

GATEWAY = {"llm_gateway_enabled": True, "llm_gateway_url": "http://platia-gateway:8000",
           "llm_gateway_api_key": "plgw-app-platia-prueba", "anthropic_api_key": ""}


def _sse(*events: tuple[str, dict]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


REPLY = _sse(
    ("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 50, "output_tokens": 1}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hola"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                       "usage": {"output_tokens": 7}}),
    ("message_stop", {"type": "message_stop"}),
)


def _sdk_client(seen: list) -> anthropic.AsyncAnthropic:
    """El SDK real con un transporte simulado: así se ve la petición HTTP que sale."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, content=REPLY, headers={"content-type": "text/event-stream"})

    return anthropic.AsyncAnthropic(api_key=GATEWAY["llm_gateway_api_key"], base_url=GATEWAY["llm_gateway_url"],
                                    http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def test_cliente_del_sdk_apunta_al_gateway_con_su_clave():
    provider = AnthropicProvider(make_settings(**GATEWAY))
    assert provider.configured and provider.via_gateway
    client = provider._get_client()
    assert str(client.base_url).rstrip("/") == "http://platia-gateway:8000"
    assert client.api_key == "plgw-app-platia-prueba"
    # Sin la clave del gateway no se puede llamar, aunque haya clave de Anthropic
    assert not AnthropicProvider(make_settings(**{**GATEWAY, "llm_gateway_api_key": "",
                                                  "anthropic_api_key": "sk-x"})).configured
    # La reserva directa queda desactivada: todo pasa por el gateway
    assert not OpenAICompatibleProvider(make_settings(**GATEWAY, fallback_base_url="https://llm.interno/v1")).configured


def test_complete_envia_tarea_persona_y_correlacion(client, runtime):
    seen: list[httpx2.Request] = []
    settings = make_settings(**GATEWAY)
    runtime.settings = settings
    runtime.providers["anthropic"] = AnthropicProvider(settings, client=_sdk_client(seen))
    resp = client.post("/v1/complete", headers=API_HEADERS, json={
        "service_type": "proposal_generation", "targets": [{"provider": "anthropic", "model": "claude-sonnet-5-5"}],
        "system": "Eres útil", "messages": [{"role": "user", "content": "Hola"}], "max_tokens": 100,
        "correlation_id": "4f6c2a1e-0000-4000-8000-000000000001", "user_ref": "42"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "Hola" and resp.json()["attempts"][0]["output_tokens"] == 7
    [request] = seen
    assert str(request.url) == "http://platia-gateway:8000/v1/messages"
    # El SDK 2.x manda la clave como Bearer; el gateway acepta las dos formas
    assert request.headers["authorization"] == "Bearer plgw-app-platia-prueba"
    assert request.headers["x-platia-purpose"] == "proposal_generation"
    assert request.headers["x-platia-user-id"] == "42"
    assert request.headers["x-request-id"] == "4f6c2a1e-0000-4000-8000-000000000001"
    assert json.loads(request.content)["model"] == "claude-sonnet-5-5"


def test_sin_gateway_no_hay_cabeceras_propias(client, runtime, fake_anthropic):
    resp = client.post("/v1/complete", headers=API_HEADERS, json={
        "service_type": "chat_rag", "targets": [{"provider": "anthropic", "model": "claude-sonnet-5-5"}],
        "system": "s", "messages": [{"role": "user", "content": "x"}], "max_tokens": 10, "user_ref": "7"})
    assert resp.status_code == 200
    assert "extra_headers" not in fake_anthropic.calls[0]


def test_persona_con_formato_no_valido(client):
    resp = client.post("/v1/complete", headers=API_HEADERS, json={
        "service_type": "chat_rag", "targets": [{"provider": "anthropic", "model": "claude-sonnet-5-5"}],
        "system": "s", "messages": [{"role": "user", "content": "x"}], "max_tokens": 10, "user_ref": "a b"})
    assert resp.status_code == 422


def test_gateway_caido_es_un_fallo_de_conexion(client, runtime):
    def down(request):
        raise httpx2.ConnectError("rechazada", request=request)

    settings = make_settings(**GATEWAY)
    runtime.settings = settings
    runtime.providers["anthropic"] = AnthropicProvider(settings, client=anthropic.AsyncAnthropic(
        api_key="plgw-x", base_url="http://platia-gateway:8000", max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(down))))
    resp = client.post("/v1/complete", headers=API_HEADERS, json={
        "service_type": "chat_rag", "targets": [{"provider": "anthropic", "model": "claude-sonnet-5-5"}],
        "system": "s", "messages": [{"role": "user", "content": "x"}], "max_tokens": 10})
    assert resp.status_code == 503
    assert resp.json()["attempts"][0]["error_type"] == "connection"


def test_salud_con_gateway(client, runtime):
    for key, expected in (("plgw-app-platia-prueba", "healthy"), ("", "degraded")):
        settings = make_settings(**{**GATEWAY, "llm_gateway_api_key": key})
        runtime.settings = settings
        app.dependency_overrides[get_settings] = lambda s=settings: s
        with _qdrant_ok():
            body = client.get("/health", headers=API_HEADERS).json()
        assert body["status"] == expected and body["llm_gateway"] is True
        assert "anthropic_key" not in body["checks"]
        assert body["checks"]["llm_gateway"] == ("configured" if key else "missing")
