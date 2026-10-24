"""Esquemas de entrada del servicio de IA. Todo lo que no se declara se rechaza."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MODEL_PATTERN = r"^[A-Za-z0-9._:/\-]{1,100}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(Strict):
    provider: Literal["anthropic", "openai_compatible"]
    model: str = Field(pattern=MODEL_PATTERN)


class Message(Strict):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=600_000)


class CompleteRequest(Strict):
    service_type: str = Field(pattern=r"^[a-z0-9_.]{1,50}$")
    targets: list[Target] = Field(min_length=1, max_length=4)
    system: str = Field(min_length=1, max_length=200_000)
    messages: list[Message] = Field(min_length=1, max_length=60)
    max_tokens: int = Field(ge=1, le=64_000)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    json_schema: dict | None = None
    timeout_seconds: float = Field(default=180, ge=5, le=900)
    correlation_id: str | None = Field(default=None, max_length=64)


class EmbedRequest(Strict):
    texts: list[str] = Field(min_length=1, max_length=256)
    kind: Literal["query", "document"] = "document"


class Chunk(Strict):
    text: str = Field(min_length=1, max_length=20_000)
    metadata: dict = Field(default_factory=dict)


class IndexRequest(Strict):
    collection: str
    ref_id: int
    chunks: list[Chunk] = Field(max_length=5_000)
    # Payload común a todos los fragmentos: título, tipo, propietario, roles, vigencia...
    common: dict = Field(default_factory=dict)


class Access(Strict):
    user_id: int | None = None
    roles: list[str] = Field(default_factory=list, max_length=50)
    bypass: bool = False  # tareas del sistema y roles con permiso de gestión


class SearchRequest(Strict):
    collections: list[str] = Field(min_length=1, max_length=4)
    query: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(default=6, ge=1, le=50)
    score_threshold: float | None = Field(default=None, ge=-1, le=1)
    only_current: bool = True
    not_expired: bool = False
    ref_ids: list[int] | None = Field(default=None, max_length=500)
    doc_types: list[str] | None = Field(default=None, max_length=20)
    access: Access | None = None


class RefRequest(Strict):
    collection: str
    ref_id: int


class PayloadRequest(RefRequest):
    payload: dict


class SimilarityRequest(Strict):
    """Similitud coseno entre unos textos y otros (puntuación semántica, Capítulo 9)."""

    queries: list[str] = Field(min_length=1, max_length=50)
    candidates: list[str] = Field(min_length=1, max_length=200)
