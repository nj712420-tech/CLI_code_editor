"""OpenAI-compatible provider over httpx, consuming SSE streaming.

Works against any base_url that speaks the OpenAI chat-completions protocol,
notably Ollama (http://localhost:11434/v1) and other drop-in servers.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from aide.config import ApiConfig
from aide.core.errors import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
    ServerError,
    TimeoutError_,
)
from aide.providers.base import ChatMessage, Provider, StreamEvent, ToolCall, ToolSchema, Usage
from aide.providers.retry import retry_stream

_SSE_DATA = "data:"


class OpenAICompatibleProvider(Provider):
    def __init__(self, config: ApiConfig) -> None:
        super().__init__(config)
        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # -- Provider ----------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [m.to_api() for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if temperature is not None:
            payload["temperature"] = temperature
        elif self.config.temperature is not None:
            payload["temperature"] = self.config.temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        elif self.config.max_tokens:
            payload["max_tokens"] = self.config.max_tokens
        if tools is not None:
            payload["tools"] = tools

        headers = {"Authorization": f"Bearer {self.config.api_key}", "Accept": "text/event-stream"}

        async def _stream_once() -> AsyncIterator[StreamEvent]:
            try:
                request = self._client.build_request(
                    "POST", "/chat/completions", json=payload, headers=headers
                )
                response = await self._client.send(request, stream=True)
            except httpx.TimeoutException as exc:
                raise TimeoutError_(f"Request timed out after {self.config.timeout}s") from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"Transport error: {exc}") from exc

            try:
                status = response.status_code
                if status == 401 or status == 403:
                    raise AuthenticationError(f"Provider rejected credentials (HTTP {status})")
                if status == 429:
                    raise RateLimitError("Provider rate limited us (HTTP 429)")
                if status >= 500:
                    raise ServerError(f"Provider server error (HTTP {status})")
                if status != 200:
                    raise ProviderError(f"Unexpected HTTP {status}")
                async for event in self._iter_sse(response):
                    if event is None:
                        continue
                    yield event
            finally:
                await response.aclose()

        # Retry on rate limits and server errors
        async for event in retry_stream(
            _stream_once,
            max_retries=3,
            base_delay=1.0,
            max_delay=30.0,
            retryable_exceptions=(
                RateLimitError,
                ServerError,
                ProviderError,
                TimeoutError,
                ConnectionError,
            ),
        ):
            yield event

    # -- internals ---------------------------------------------------------

    async def _iter_sse(self, response: httpx.Response) -> AsyncIterator[StreamEvent | None]:
        usage = Usage()
        # Accumulate streamed tool-call fragments: index -> {id, name, arguments}
        tool_fragments: dict[int, dict[str, str]] = {}
        async for raw in response.aiter_lines():
            line = raw.strip()
            if not line:
                continue
            if line == "data: [DONE]":
                break
            if not line.startswith(_SSE_DATA):
                continue
            try:
                data: dict[str, Any] = json.loads(line[len(_SSE_DATA) :].strip())
            except json.JSONDecodeError:
                continue
            choices = data.get("choices") or []
            if not choices:
                # usage-only chunk (final) or a heartbeat
                chunk_usage = data.get("usage")
                if chunk_usage:
                    usage = Usage(
                        prompt_tokens=int(chunk_usage.get("prompt_tokens", 0)),
                        completion_tokens=int(chunk_usage.get("completion_tokens", 0)),
                    )
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            if delta.get("content"):
                yield StreamEvent(
                    kind="delta",
                    text=str(delta["content"]),
                )
            # reasoning models stream their chain-of-thought in `reasoning`
            if delta.get("reasoning"):
                yield StreamEvent(
                    kind="thinking",
                    text=str(delta["reasoning"]),
                )
            # tool call fragments (OpenAI streams them per-index)
            for call in delta.get("tool_calls") or []:
                index = int(call.get("index", 0))
                frag = tool_fragments.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if call.get("id"):
                    frag["id"] = str(call["id"])
                fn = call.get("function") or {}
                if fn.get("name"):
                    frag["name"] = str(fn["name"])
                if fn.get("arguments"):
                    frag["arguments"] += str(fn["arguments"])
            if choice.get("usage"):
                chunk_usage = choice["usage"]
                usage = Usage(
                    prompt_tokens=int(chunk_usage.get("prompt_tokens", 0)),
                    completion_tokens=int(chunk_usage.get("completion_tokens", 0)),
                )
        if tool_fragments:
            calls: list[ToolCall] = []
            for index in sorted(tool_fragments):
                frag = tool_fragments[index]
                try:
                    args: dict[str, Any] = (
                        json.loads(frag["arguments"]) if frag["arguments"] else {}
                    )
                except json.JSONDecodeError:
                    args = {}
                calls.append(
                    ToolCall(id=frag["id"] or f"call_{index}", name=frag["name"], arguments=args)
                )
            yield StreamEvent(kind="tool_call", tool_calls=calls)
        yield StreamEvent(kind="usage", usage=usage)
        yield StreamEvent(kind="end")


def factory(config: ApiConfig) -> Provider:
    """Main provider factory - dispatches based on config.provider."""
    provider_type = getattr(config, "provider", "openai_compat")
    if provider_type == "anthropic":
        from aide.providers.anthropic import factory as anthropic_factory

        return anthropic_factory(config)
    elif provider_type == "ollama":
        from aide.providers.ollama import factory as ollama_factory

        return ollama_factory(config)
    else:
        return OpenAICompatibleProvider(config)


__all__ = ["OpenAICompatibleProvider", "factory"]
