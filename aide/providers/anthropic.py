"""Anthropic (Claude) provider — native API implementation."""

from __future__ import annotations

import json
import os
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


class AnthropicProvider(Provider):
    """Native Anthropic API provider."""

    API_VERSION = "2023-06-01"

    def __init__(self, config: ApiConfig) -> None:
        super().__init__(config)
        # Allow base_url override for enterprise/custom endpoints
        base = config.base_url.rstrip("/") if config.base_url else "https://api.anthropic.com"
        self._client = httpx.AsyncClient(
            base_url=base,
            timeout=config.timeout,
        )
        # Use ANTHROPIC_API_KEY env var if api_key is not set
        self._api_key = config.api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    async def close(self) -> None:
        await self._client.aclose()

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        # Convert messages to Anthropic format
        system_msg = ""
        anthropic_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_msg = msg.content
            elif msg.role == "tool":
                # Tool results are sent as user messages with tool_result content
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id or "",
                                "content": msg.content,
                            }
                        ],
                    }
                )
            elif msg.role == "assistant" and msg.tool_calls:
                # Assistant with tool calls
                content_blocks: list[dict[str, Any]] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id", f"call_{len(content_blocks)}"),
                            "name": tc.get("function", {}).get("name", ""),
                            "input": json.loads(tc.get("function", {}).get("arguments", "{}")),
                        }
                    )
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            else:
                # Regular user/assistant message
                role = "user" if msg.role == "user" else "assistant"
                anthropic_messages.append({"role": role, "content": msg.content})

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or self.config.max_tokens or 4096,
            "stream": True,
        }
        if system_msg:
            payload["system"] = system_msg
        if temperature is not None:
            payload["temperature"] = temperature
        elif self.config.temperature is not None:
            payload["temperature"] = self.config.temperature
        if tools:
            payload["tools"] = self._convert_tools(tools)

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }

        try:
            request = self._client.build_request(
                "POST", "/v1/messages", json=payload, headers=headers
            )
            response = await self._client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise TimeoutError_(f"Request timed out after {self.config.timeout}s") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Transport error: {exc}") from exc

        try:
            status = response.status_code
            if status == 401 or status == 403:
                raise AuthenticationError(f"Anthropic rejected credentials (HTTP {status})")
            if status == 429:
                raise RateLimitError("Anthropic rate limited us (HTTP 429)")
            if status >= 500:
                raise ServerError(f"Anthropic server error (HTTP {status})")
            if status != 200:
                body = await response.aread()
                raise ProviderError(f"Anthropic HTTP {status}: {body.decode()}")
            async for event in self._iter_sse(response):
                if event is None:
                    continue
                yield event
        finally:
            await response.aclose()

    def _convert_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        """Convert OpenAI tool schema to Anthropic format."""
        result: list[dict[str, Any]] = []
        for tool in tools:
            fn = tool.get("function", {})
            result.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return result

    async def _iter_sse(self, response: httpx.Response) -> AsyncIterator[StreamEvent | None]:
        usage = Usage()
        tool_fragments: dict[int, dict[str, Any]] = {}

        async for raw in response.aiter_lines():
            line = raw.strip()
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            try:
                data = json.loads(line[len("data:") :].strip())
            except json.JSONDecodeError:
                continue

            event_type = data.get("type")
            if event_type == "message_start":
                # Initial message metadata
                if "usage" in data.get("message", {}):
                    u = data["message"]["usage"]
                    usage = Usage(
                        prompt_tokens=u.get("input_tokens", 0),
                        completion_tokens=u.get("output_tokens", 0),
                    )
            elif event_type == "content_block_delta":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield StreamEvent(kind="delta", text=delta.get("text", ""))
                elif delta.get("type") == "thinking_delta":
                    yield StreamEvent(kind="thinking", text=delta.get("thinking", ""))
                elif delta.get("type") == "input_json_delta":
                    index = data.get("index", 0)
                    frag = tool_fragments.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if delta.get("partial_json"):
                        frag["arguments"] += delta["partial_json"]
            elif event_type == "content_block_start":
                block = data.get("content_block", {})
                if block.get("type") == "tool_use":
                    index = data.get("index", 0)
                    frag = tool_fragments.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    frag["id"] = block.get("id", f"call_{index}")
                    frag["name"] = block.get("name", "")
            elif event_type == "message_delta":
                if "usage" in data:
                    u = data["usage"]
                    usage = Usage(
                        prompt_tokens=u.get("input_tokens", 0),
                        completion_tokens=u.get("output_tokens", 0),
                    )
            elif event_type == "message_stop":
                break

        if tool_fragments:
            calls: list[ToolCall] = []
            for index in sorted(tool_fragments):
                frag = tool_fragments[index]
                try:
                    args = json.loads(frag["arguments"]) if frag["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                calls.append(
                    ToolCall(id=frag["id"] or f"call_{index}", name=frag["name"], arguments=args)
                )
            yield StreamEvent(kind="tool_call", tool_calls=calls)

        yield StreamEvent(kind="usage", usage=usage)
        yield StreamEvent(kind="end")


def factory(config: ApiConfig) -> Provider:
    return AnthropicProvider(config)


__all__ = ["AnthropicProvider", "factory"]
