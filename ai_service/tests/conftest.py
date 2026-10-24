from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from qdrant_client import AsyncQdrantClient

from app.circuit import CircuitBreaker
from app.embeddings import HashEmbedder
from app.main import Runtime, app, get_runtime
from app.providers import AnthropicProvider, OpenAICompatibleProvider
from app.settings import Settings, get_settings
from app.vectorstore import VectorStore

API_HEADERS = {"X-API-Key": "secret"}


def make_settings(**overrides) -> Settings:
    base = {"api_key": "secret", "anthropic_api_key": "sk-test", "qdrant_api_key": "",
            "embedding_provider": "hash", "fallback_base_url": ""}
    base.update(overrides)
    return Settings(**base)


class FakeStream:
    def __init__(self, message, fail_after_text: Exception | None = None):
        self._message = message
        self._fail = fail_after_text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._events()

    async def _events(self):
        for block in self._message.content:
            if block.type == "text":
                for word in block.text.split(" "):
                    yield SimpleNamespace(type="text", text=word + " ")
                if self._fail is not None:
                    raise self._fail

    async def get_final_message(self):
        return self._message


class FakeAnthropic:
    """Sustituye al cliente del SDK: devuelve respuestas programadas en orden."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0) if self.responses else "ok"
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):  # (texto, excepción a mitad del streaming)
            return FakeStream(fake_message(item[0], kwargs.get("model")), item[1])
        return FakeStream(fake_message(item, kwargs.get("model")))


def fake_message(text, model="claude-sonnet-5-5", stop_reason="end_turn", input_tokens=120, output_tokens=40):
    if isinstance(text, SimpleNamespace):
        return text
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0),
        model=model, stop_reason=stop_reason,
    )


@pytest.fixture()
def fake_anthropic():
    return FakeAnthropic()


@pytest.fixture()
def runtime(fake_anthropic):
    settings = make_settings()
    embedder = HashEmbedder()
    store = VectorStore(AsyncQdrantClient(location=":memory:"), embedder)
    return Runtime(
        settings=settings,
        providers={"anthropic": AnthropicProvider(settings, client=fake_anthropic),
                   "openai_compatible": OpenAICompatibleProvider(settings)},
        breaker=CircuitBreaker(3, 30, 120),
        embedder=embedder,
        store=store,
    )


@pytest.fixture()
def client(runtime):
    app.dependency_overrides[get_settings] = lambda: runtime.settings
    app.dependency_overrides[get_runtime] = lambda: runtime
    yield TestClient(app)
    app.dependency_overrides.clear()
