"""Configuración del servicio de IA, leída de variables de entorno (Apéndice F).

El servicio no tiene base de datos: qué modelo usar, qué prompt y cuánto se ha
gastado lo decide y lo registra el backend (ADR-011). Aquí solo hay credenciales
de proveedores, el modelo de embeddings y los límites técnicos.
"""
import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _float(name: str, default: str) -> float:
    return float(os.environ.get(name, default))


def _int(name: str, default: str) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default_factory=lambda: _env("AI_SERVICE_API_KEY"))

    # --- Anthropic (proveedor principal)
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    default_model: str = field(default_factory=lambda: _env("CLAUDE_DEFAULT_MODEL", "claude-sonnet-5-5"))
    premium_model: str = field(default_factory=lambda: _env("CLAUDE_PREMIUM_MODEL", "claude-opus-5-5"))
    fast_model: str = field(default_factory=lambda: _env("CLAUDE_FAST_MODEL", "claude-haiku-5-5"))
    llm_timeout_seconds: float = field(default_factory=lambda: _float("LLM_TIMEOUT_SECONDS", "180"))
    llm_max_retries: int = field(default_factory=lambda: _int("LLM_MAX_RETRIES", "2"))

    # --- Proveedor de reserva opcional con API compatible con OpenAI (Azure OpenAI,
    # OpenAI, Ollama o LM Studio). Vacío = sin reserva externa.
    fallback_base_url: str = field(default_factory=lambda: _env("FALLBACK_LLM_BASE_URL"))
    fallback_api_key: str = field(default_factory=lambda: _env("FALLBACK_LLM_API_KEY"))

    # --- Circuit breaker por proveedor (Capítulo 11)
    circuit_failure_threshold: int = field(default_factory=lambda: _int("CIRCUIT_FAILURE_THRESHOLD", "5"))
    circuit_window_seconds: float = field(default_factory=lambda: _float("CIRCUIT_WINDOW_SECONDS", "30"))
    circuit_recovery_seconds: float = field(default_factory=lambda: _float("CIRCUIT_RECOVERY_SECONDS", "120"))

    # --- Embeddings: local (por defecto, sin coste ni clave), voyage o hash (solo tests)
    embedding_provider: str = field(default_factory=lambda: _env("EMBEDDING_PROVIDER", "local"))
    embedding_model: str = field(
        default_factory=lambda: _env("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    )
    embedding_cache_dir: str = field(default_factory=lambda: _env("EMBEDDING_CACHE_DIR", "/models"))
    voyage_api_key: str = field(default_factory=lambda: _env("VOYAGE_API_KEY"))

    # --- Qdrant
    qdrant_url: str = field(
        default_factory=lambda: f"http://{_env('QDRANT_HOST', 'qdrant')}:{_env('QDRANT_PORT', '6333')}"
    )
    qdrant_api_key: str = field(default_factory=lambda: _env("QDRANT_API_KEY"))


def get_settings() -> Settings:
    return Settings()
