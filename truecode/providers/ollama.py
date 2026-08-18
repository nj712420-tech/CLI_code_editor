"""Ollama provider — uses OpenAI-compatible API with Ollama-specific defaults."""

from __future__ import annotations

from truecode.config import ApiConfig
from truecode.providers.base import Provider
from truecode.providers.openai_compat import OpenAICompatibleProvider


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama provider using OpenAI-compatible API.

    Ollama exposes an OpenAI-compatible endpoint at /v1.
    This provider just sets the default base_url and model appropriately.
    """

    def __init__(self, config: ApiConfig) -> None:
        # Override base_url if not explicitly set to non-default
        if config.base_url in ("http://localhost:11434/v1", "https://api.openai.com/v1"):
            config.base_url = "http://localhost:11434/v1"
        super().__init__(config)


def factory(config: ApiConfig) -> Provider:
    return OllamaProvider(config)


__all__ = ["OllamaProvider", "factory"]
