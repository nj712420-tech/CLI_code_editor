"""Provider interface — every backend must implement these primitives."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from aide.config import ApiConfig

Role = Literal["system", "user", "assistant", "tool"]

ToolSchema = dict[str, Any]


@dataclass
class ChatMessage:
    role: Role
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    def to_api(self) -> dict[str, Any]:
        """Serialize to the OpenAI wire format."""
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id
        if self.tool_calls is not None:
            msg["tool_calls"] = self.tool_calls
        return msg


@dataclass
class ToolCall:
    """A single function call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]

    @property
    def summary(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.arguments.items())
        return f"{self.name}({args})"


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


@dataclass
class StreamEvent:
    """One unit of streamed output from a provider."""

    kind: Literal["delta", "thinking", "tool_call", "usage", "end", "error"]
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    error: str = ""


class Provider(ABC):
    """Thin capability surface every backend must satisfy."""

    def __init__(self, config: ApiConfig) -> None:
        self.config = config

    @abstractmethod
    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion.

        Yields deltas, optional tool_call events, a usage event, then 'end'.
        """
        raise NotImplementedError

    async def close(self) -> None:
        """Release any held resources. Implementations override if needed."""
        return

    # --- utilities shared by all providers --------------------------------

    @staticmethod
    def _age() -> float:
        return time.monotonic()
