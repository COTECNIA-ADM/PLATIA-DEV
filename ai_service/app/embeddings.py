"""Modelos de embeddings (Capítulo 12).

El libro usa text-embedding-3-large de OpenAI. Aquí, para no exigir otra clave de
pago, el proveedor por defecto es un modelo multilingüe **local** (fastembed,
ONNX en CPU) que se descarga al construir la imagen. Alternativas (ADR-011):

- ``voyage``: Voyage AI, el proveedor que recomienda Anthropic (requiere clave).
- ``hash``: vectores por hashing de palabras. No captura significado: solo
  sirve para tests y entornos sin acceso a internet.

Cambiar de modelo obliga a reindexar: por eso el nombre físico de cada colección
de Qdrant lleva la huella del modelo (``slug``) y un modelo nuevo empieza con
colecciones vacías en lugar de mezclar vectores incompatibles.
"""
import hashlib
import math
import re
import threading

import httpx
import structlog

from .settings import Settings

log = structlog.get_logger(__name__)

_WORD = re.compile(r"\w+", re.UNICODE)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())[-24:]


class HashEmbedder:
    """Bolsa de palabras con hashing, normalizada. Determinista y sin dependencias."""

    provider = "hash"

    def __init__(self, dims: int = 384):
        self.dims = dims
        self.model = f"hash-{dims}"
        self.slug = f"hash{dims}"
        self.status = "ready"

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for word in _WORD.findall(text.lower()):
            digest = hashlib.md5(word.encode()).digest()
            index = int.from_bytes(digest[:4], "little") % self.dims
            vec[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        return [self._vector(t) for t in texts]


class LocalEmbedder:
    """fastembed (ONNX). El modelo se carga la primera vez y se reutiliza."""

    provider = "local"

    def __init__(self, model: str, cache_dir: str):
        self.model = model
        self.cache_dir = cache_dir
        self.slug = _slug(model.split("/")[-1])
        self._model = None
        self._lock = threading.Lock()
        self.status = "not_loaded"
        self.dims = self._known_dims(model)

    @staticmethod
    def _known_dims(model: str) -> int | None:
        try:
            from fastembed import TextEmbedding

            for desc in TextEmbedding.list_supported_models():
                if desc["model"].lower() == model.lower():
                    return int(desc["dim"])
        except Exception:
            return None
        return None

    def load(self):
        with self._lock:
            if self._model is None:
                self.status = "loading"
                try:
                    from fastembed import TextEmbedding

                    self._model = TextEmbedding(model_name=self.model, cache_dir=self.cache_dir)
                    self.status = "ready"
                    log.info("embedding_model_loaded", model=self.model)
                except Exception as exc:
                    self.status = "error"
                    log.error("embedding_model_load_failed", model=self.model, error=str(exc))
                    raise
        return self._model

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        model = self.load()
        method = model.query_embed if kind == "query" else model.passage_embed
        vectors = [list(map(float, v)) for v in method(texts, batch_size=32)]
        if vectors and self.dims is None:
            self.dims = len(vectors[0])
        return vectors


class VoyageEmbedder:
    provider = "voyage"
    url = "https://api.voyageai.com/v1/embeddings"

    def __init__(self, api_key: str, model: str = "voyage-3.5", transport=None):
        self.api_key = api_key
        self.model = model
        self.slug = _slug(model)
        self.dims = 1024
        self.status = "ready" if api_key else "error"
        self._transport = transport

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("VOYAGE_API_KEY no está configurada")
        vectors: list[list[float]] = []
        with httpx.Client(timeout=60, transport=self._transport) as client:
            for start in range(0, len(texts), 128):
                resp = client.post(self.url, headers={"Authorization": f"Bearer {self.api_key}"},
                                   json={"input": texts[start:start + 128], "model": self.model,
                                         "input_type": "query" if kind == "query" else "document"})
                resp.raise_for_status()
                vectors += [item["embedding"] for item in sorted(resp.json()["data"], key=lambda d: d["index"])]
        if vectors:
            self.dims = len(vectors[0])
        return vectors


def build_embedder(settings: Settings):
    provider = settings.embedding_provider.lower()
    if provider == "hash":
        return HashEmbedder()
    if provider == "voyage":
        model = settings.embedding_model if settings.embedding_model.startswith("voyage") else "voyage-3.5"
        return VoyageEmbedder(settings.voyage_api_key, model)
    return LocalEmbedder(settings.embedding_model, settings.embedding_cache_dir)
