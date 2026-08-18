"""Request handler — orchestrates prompt → provider → history.

Headless by design: the TUI and the `chat` subcommand consume the same
`single_turn` pipeline so behavior stays identical everywhere.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable

from aide.config import Config
from aide.core.history import SessionHistory
from aide.providers import ChatMessage, Provider, StreamEvent
from aide.providers.openai_compat import factory

logger = logging.getLogger(__name__)

PREAMBLE = "You are aide, a helpful AI coding assistant running inside a terminal."


class RequestHandler:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.history = SessionHistory()
        self.provider: Provider | None = None

    async def aclose(self) -> None:
        if self.provider is not None:
            await self.provider.close()

    async def _get_provider(self) -> Provider:
        if self.provider is None:
            self.provider = factory(self.config.api)
        return self.provider

    async def ask(
        self,
        prompt: str,
        *,
        context: list[ChatMessage] | None = None,
        on_event: Callable[[StreamEvent], None] | None = None,
    ) -> str:
        """Send one user turn, record history, return the full assistant text."""
        self.history.record_message("user", prompt)
        messages = [ChatMessage(role="system", content=PREAMBLE)]
        messages.extend(context or [])
        messages.extend(self.history.messages)

        provider = await self._get_provider()
        collected: list[str] = []
        async for event in provider.stream_chat(
            messages,
            temperature=self.config.api.temperature,
            max_tokens=self.config.api.max_tokens,
        ):
            if on_event is not None:
                on_event(event)
            if event.kind == "delta":
                collected.append(event.text)
            elif event.kind == "usage":
                self.history.record_usage(event.usage)
        full = "".join(collected)
        self.history.record_message("assistant", full)
        return full

    async def stream_ask(
        self,
        prompt: str,
        *,
        context: list[ChatMessage] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Same as `ask` but yields events so the TUI renders incrementally."""
        self.history.record_message("user", prompt)
        messages = [ChatMessage(role="system", content=PREAMBLE)]
        messages.extend(context or [])
        messages.extend(self.history.messages)

        provider = await self._get_provider()
        collected: list[str] = []
        async for event in provider.stream_chat(
            messages,
            temperature=self.config.api.temperature,
            max_tokens=self.config.api.max_tokens,
        ):
            yield event
            if event.kind == "delta":
                collected.append(event.text)
            elif event.kind == "usage":
                self.history.record_usage(event.usage)
        self.history.record_message("assistant", "".join(collected))


def get_handler(config: Config | None = None) -> RequestHandler:
    from aide.config import load_config

    if config is None:
        config = load_config()
    return RequestHandler(config)
