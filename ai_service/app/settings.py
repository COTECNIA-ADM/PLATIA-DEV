"""Configuración del servicio de IA, leída de variables de entorno (Apéndice F)."""
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default_factory=lambda: os.environ.get("AI_SERVICE_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    default_model: str = field(
        default_factory=lambda: os.environ.get("CLAUDE_DEFAULT_MODEL", "claude-sonnet-5-5")
    )
    qdrant_url: str = field(
        default_factory=lambda: (
            f"http://{os.environ.get('QDRANT_HOST', 'qdrant')}:{os.environ.get('QDRANT_PORT', '6333')}"
        )
    )
    qdrant_api_key: str = field(default_factory=lambda: os.environ.get("QDRANT_API_KEY", ""))


def get_settings() -> Settings:
    return Settings()
