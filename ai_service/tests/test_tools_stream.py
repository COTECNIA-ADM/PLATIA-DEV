"""Herramientas (tool use) y respuestas en streaming para el copiloto (Capítulos 14 y 15)."""
import json
from types import SimpleNamespace

import anthropic
import httpx2

from .conftest import API_HEADERS

TOOL = {"name": "search_opportunities", "description": "Busca oportunidades en el buscador de la plataforma.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
                         "additionalProperties": False}}


def _body(**overrides):
    body = {"service_type": "agent_copilot",
            "targets": [{"provider": "anthropic", "model": "claude-sonnet-5-5"},
                        {"provider": "anthropic", "model": "claude-haiku-5-5"}],
            "system": "Eres el copiloto.", "messages": [{"role": "user", "content": "Busca contratos de SOC"}],
            "max_tokens": 800}
    body.update(overrides)
    return body


def _tool_message():
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking="", signature="sig-1"),
                 SimpleNamespace(type="text", text="Voy a buscar."),
                 SimpleNamespace(type="tool_use", id="toolu_1", name="search_opportunities",
                                 input={"query": "SOC"})],
        usage=SimpleNamespace(input_tokens=300, output_tokens=50, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
        model="claude-sonnet-5-5", stop_reason="tool_use")


def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    for chunk in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_tools_and_content_blocks_round_trip(client, fake_anthropic):
    fake_anthropic.responses = [_tool_message()]
    resp = client.post("/v1/complete", json=_body(tools=[TOOL]), headers=API_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stop_reason"] == "tool_use"
    assert body["content"] == [{"type": "thinking", "thinking": "", "signature": "sig-1"},
                               {"type": "text", "text": "Voy a buscar."},
                               {"type": "tool_use", "id": "toolu_1", "name": "search_opportunities",
                                "input": {"query": "SOC"}}]
    assert fake_anthropic.calls[0]["tools"][0]["strict"] is True

    # El turno siguiente devuelve los bloques tal cual con el resultado de la herramienta
    follow = [{"role": "user", "content": "Busca contratos de SOC"},
              {"role": "assistant", "content": body["content"]},
              {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                            "content": '{"items": []}'}]}]
    fake_anthropic.responses = ["No hay resultados."]
    resp = client.post("/v1/complete", json=_body(tools=[TOOL], messages=follow), headers=API_HEADERS)
    assert resp.status_code == 200 and resp.json()["text"] == "No hay resultados."
    assert fake_anthropic.calls[1]["messages"][1]["content"][0]["signature"] == "sig-1"


def test_rejects_unknown_block_types_and_bad_tool_names(client):
    bad = [{"role": "user", "content": [{"type": "image", "source": {}}]}]
    assert client.post("/v1/complete", json=_body(messages=bad), headers=API_HEADERS).status_code == 422
    tool = {**TOOL, "name": "Rm -rf"}
    assert client.post("/v1/complete", json=_body(tools=[tool]), headers=API_HEADERS).status_code == 422


def test_stream_sends_deltas_then_final(client, fake_anthropic):
    fake_anthropic.responses = ["Hay tres oportunidades abiertas."]
    resp = client.post("/v1/stream", json=_body(), headers=API_HEADERS)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    events = _events(resp.text)
    assert "".join(e[1]["text"] for e in events if e[0] == "delta").strip() == "Hay tres oportunidades abiertas."
    kind, final = events[-1]
    assert kind == "final" and final["attempts"][0]["success"] and final["content"][-1]["type"] == "text"


def test_stream_falls_back_only_before_any_text(client, fake_anthropic):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    overloaded = anthropic.APIStatusError("overloaded", response=httpx2.Response(529, request=req), body=None)
    fake_anthropic.responses = [overloaded, "Respuesta de reserva"]
    events = _events(client.post("/v1/stream", json=_body(), headers=API_HEADERS).text)
    assert events[-1][0] == "final" and events[-1][1]["is_fallback"] is True

    # Si ya se emitió texto, no se cambia de modelo: se informa del corte
    cut = anthropic.APIConnectionError(request=req)
    fake_anthropic.responses = [("Empiezo a responder", cut), "No debería usarse"]
    events = _events(client.post("/v1/stream", json=_body(), headers=API_HEADERS).text)
    assert events[0][0] == "delta"
    assert events[-1][0] == "error" and events[-1][1]["detail"] == "La respuesta se interrumpió"
    assert len(events[-1][1]["attempts"]) == 1


def test_fallback_provider_is_skipped_with_tools(client, runtime, fake_anthropic):
    from app.providers import OpenAICompatibleProvider

    from .conftest import make_settings

    runtime.providers["openai_compatible"] = OpenAICompatibleProvider(
        make_settings(fallback_base_url="http://reserva.local/v1"))
    fake_anthropic.responses = [anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x"))]
    body = _body(tools=[TOOL], targets=[{"provider": "anthropic", "model": "claude-sonnet-5-5"},
                                        {"provider": "openai_compatible", "model": "gpt-x"}])
    resp = client.post("/v1/complete", json=body, headers=API_HEADERS)
    assert resp.status_code == 503
    assert [a["error_type"] for a in resp.json()["attempts"]] == ["connection", "no_tool_support"]
    assert runtime.breaker.state("openai_compatible") == "closed"
