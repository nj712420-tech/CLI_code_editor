"""AgentLoop — prompt → (tool | assistant) → stop (Phase 3 + F4.4 auto-repair)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from truecode.config import Config
from truecode.core.errors import AmbiguousMatchError, NoMatchError
from truecode.core.history import SessionHistory
from truecode.core.request_handler import PREAMBLE
from truecode.core.tool_registry import AskUser, ToolRegistry
from truecode.core.turn_cost import TokenLedger
from truecode.providers import ChatMessage, Provider, ToolCall, Usage
from truecode.providers.openai_compat import factory

logger = logging.getLogger(__name__)

DEFAULT_MAX_TURNS = 8
DEFAULT_MAX_TOOL_CALLS_PER_TURN = 8
DEFAULT_MAX_EDIT_RETRIES = 3


@dataclass
class AgentEvent:
    """An event the loop emits for the UI to render."""

    kind: Literal[
        "delta",
        "thinking",
        "tool_start",
        "tool_result",
        "tool_error",
        "usage",
        "ask",
        "permission",
        "permission_denied",
        "done",
        "error",
    ]
    text: str = ""
    call: ToolCall | None = None
    result: str = ""
    usage: Usage = field(default_factory=Usage)


class AgentLoop:
    """Orchestrates model ↔ tool interaction until the model answers."""

    def __init__(
        self,
        config: Config,
        registry: ToolRegistry,
        *,
        max_turns: int = DEFAULT_MAX_TURNS,
        max_tool_calls_per_turn: int = DEFAULT_MAX_TOOL_CALLS_PER_TURN,
        max_edit_retries: int = DEFAULT_MAX_EDIT_RETRIES,
        permission_handler: Callable[[str, str], Awaitable[str]] | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.max_turns = max_turns
        self.max_tool_calls_per_turn = max_tool_calls_per_turn
        self.max_edit_retries = max_edit_retries
        self.history = SessionHistory()
        self.ledger = TokenLedger()
        self.provider: Provider | None = None
        self._interrupted = False
        self._permission_handler = permission_handler
        self._always_allow: set[str] = set()

    def interrupt(self) -> None:
        """Request a cooperative stop; the loop halts at the next event."""
        self._interrupted = True

    async def _request_permission(self, call: ToolCall) -> bool:
        """Ask the user to approve a permission-required tool call.

        Returns True to proceed. Decisions are remembered per command for the
        session when the user chooses "always allow".
        """
        if call.name in self._always_allow:
            return True
        command = str(call.arguments.get("command", call.summary))
        if self._permission_handler is None:
            return False
        decision = await self._permission_handler(command, call.name)
        if decision == "always":
            self._always_allow.add(call.name)
            return True
        return decision == "allow"

    async def aclose(self) -> None:
        if self.provider is not None:
            await self.provider.close()

    async def _get_provider(self) -> Provider:
        if self.provider is None:
            self.provider = factory(self.config.api)
        return self.provider

    async def run(
        self,
        prompt: str,
        *,
        on_event: Callable[[AgentEvent], Any] | None = None,
    ) -> str:
        """Run the agent loop for one user prompt; returns the final answer."""
        self.history.record_message("user", prompt)
        messages: list[ChatMessage] = [ChatMessage(role="system", content=PREAMBLE)]
        messages.extend(self.history.messages)
        tools = self.registry.describe()

        provider = await self._get_provider()
        collected: list[str] = []
        for turn in range(1, self.max_turns + 1):
            if self._interrupted:
                break
            if on_event is not None:
                on_event(AgentEvent(kind="usage", usage=Usage()))
            collected, calls, usage = await self._one_turn(
                provider, messages, tools, turn, on_event
            )
            self.ledger.record(turn, usage)

            if self._interrupted:
                break

            if not calls:
                final = "".join(collected).strip()
                self.history.record_assistant_message(final, tool_calls=None)
                if on_event is not None:
                    on_event(AgentEvent(kind="usage", usage=usage))
                    on_event(AgentEvent(kind="done", text=final))
                return final

            # Assistant requested tools: echo the calls and append results.
            self.history.record_assistant_message("".join(collected), tool_calls=calls)
            messages.append(
                ChatMessage(
                    role="assistant",
                    content="".join(collected),
                    tool_calls=self._api_calls(calls),
                )
            )
            for call in calls[: self.max_tool_calls_per_turn]:
                await asyncio.sleep(0)  # let the UI breathe between tools
                if on_event is not None:
                    on_event(AgentEvent(kind="tool_start", call=call))
                if self.registry.requires_permission(call.name):
                    if on_event is not None:
                        on_event(
                            AgentEvent(
                                kind="permission",
                                text=f"permission needed: {call.summary}",
                                call=call,
                            )
                        )
                    allowed = await self._request_permission(call)
                    if not allowed:
                        if on_event is not None:
                            on_event(
                                AgentEvent(
                                    kind="permission_denied",
                                    text=f"user denied: {call.summary}",
                                    call=call,
                                )
                            )
                        self._interrupted = True
                        return f"user denied permission for {call.summary}; the task was stopped."
                try:
                    result = await self._execute_with_repair(call, on_event, messages)
                except AskUser as exc:
                    if on_event is not None:
                        on_event(
                            AgentEvent(
                                kind="ask",
                                text=f"model asks: {exc.question}",
                                call=call,
                            )
                        )
                    self._interrupted = True
                    return exc.question
                if self._interrupted:
                    return "".join(collected).strip()
                if on_event is not None:
                    on_event(
                        AgentEvent(
                            kind="tool_result" if not result.startswith("error") else "tool_error",
                            call=call,
                            result=result,
                        )
                    )
                self.history.record_tool_result(call.id, result)
                messages.append(ChatMessage(role="tool", content=result, tool_call_id=call.id))

        if self._interrupted:
            return "".join(collected).strip()
        if on_event is not None:
            on_event(AgentEvent(kind="error", text=f"reached max turns ({self.max_turns})"))
        return f"reached max turns ({self.max_turns}) without a final answer"

    async def _one_turn(
        self,
        provider: Provider,
        messages: list[ChatMessage],
        tools: list[dict[str, object]],
        turn: int,
        on_event: Callable[[AgentEvent], None] | None,
    ) -> tuple[list[str], list[ToolCall], Usage]:
        collected: list[str] = []
        calls: list[ToolCall] = []
        thinking: list[str] = []
        usage = Usage()
        async for event in provider.stream_chat(
            messages,
            temperature=self.config.api.temperature,
            max_tokens=self.config.api.max_tokens,
            tools=tools,
        ):
            if self._interrupted:
                break
            if event.kind == "delta":
                collected.append(event.text)
                if on_event is not None:
                    on_event(AgentEvent(kind="delta", text=event.text))
            elif event.kind == "thinking":
                thinking.append(event.text)
                if on_event is not None:
                    on_event(AgentEvent(kind="thinking", text=event.text))
            elif event.kind == "tool_call":
                calls = event.tool_calls
            elif event.kind == "usage":
                usage = event.usage
                self.history.record_usage(event.usage)
        return collected, calls, usage

    async def _execute_with_repair(
        self,
        call: ToolCall,
        on_event: Callable[[AgentEvent], None] | None,
        messages: list[ChatMessage],
    ) -> str:
        """Execute a tool call with auto-repair for edit_file failures."""
        if call.name != "edit_file":
            try:
                return self.registry.execute(call.name, call.arguments)
            except AskUser as exc:
                if on_event is not None:
                    on_event(
                        AgentEvent(
                            kind="ask",
                            text=f"model asks: {exc.question}",
                            call=call,
                        )
                    )
                self._interrupted = True
                raise

        # Auto-repair loop for edit_file
        last_error: str | None = None
        for attempt in range(self.max_edit_retries + 1):
            try:
                result = self.registry.execute(call.name, call.arguments)
                if attempt > 0 and on_event is not None:
                    on_event(
                        AgentEvent(
                            kind="tool_result",
                            call=call,
                            result=f"edit succeeded on retry {attempt}: {result}",
                        )
                    )
                return result
            except (NoMatchError, AmbiguousMatchError) as exc:
                last_error = str(exc)
                if attempt < self.max_edit_retries:
                    if on_event is not None:
                        on_event(
                            AgentEvent(
                                kind="tool_error",
                                call=call,
                                result=(
                                    f"edit failed (attempt {attempt + 1}"
                                    f"/{self.max_edit_retries + 1}): {last_error}"
                                ),
                            )
                        )
                    # Feed error back to model to generate corrected edit
                    error_msg = (
                        f"The edit failed: {last_error}\n"
                        f"Please provide a corrected edit_file call with more context "
                        f"to uniquely match the target text."
                    )
                    messages.append(
                        ChatMessage(role="tool", content=error_msg, tool_call_id=call.id)
                    )
                    # Ask model for a corrected tool call
                    corrected = await self._request_corrected_edit(
                        call, last_error, messages, on_event
                    )
                    if corrected is None:
                        return f"error: {last_error}"
                    call = corrected
                    continue
                # Max retries exceeded
                if on_event is not None:
                    on_event(
                        AgentEvent(
                            kind="tool_error",
                            call=call,
                            result=(
                                f"edit failed after {self.max_edit_retries + 1}"
                                f" attempts: {last_error}"
                            ),
                        )
                    )
                return f"error: {last_error}"
            except AskUser as exc:
                if on_event is not None:
                    on_event(
                        AgentEvent(
                            kind="ask",
                            text=f"model asks: {exc.question}",
                            call=call,
                        )
                    )
                self._interrupted = True
                return exc.question
            except Exception as exc:
                last_error = str(exc)
                if on_event is not None:
                    on_event(
                        AgentEvent(
                            kind="tool_error",
                            call=call,
                            result=f"edit failed: {last_error}",
                        )
                    )
                return f"error: {last_error}"

        return f"error: {last_error}"

    async def _request_corrected_edit(
        self,
        original_call: ToolCall,
        error: str,
        messages: list[ChatMessage],
        on_event: Callable[[AgentEvent], None] | None,
    ) -> ToolCall | None:
        """Ask the model to provide a corrected edit_file call."""
        provider = await self._get_provider()
        tools = self.registry.describe()

        # Add a system message guiding the correction
        messages.append(
            ChatMessage(
                role="system",
                content=(
                    "The previous edit_file call failed. You must provide a corrected "
                    "edit_file call with more surrounding context in old_string to "
                    "uniquely identify the target location. Do not explain, just call the tool."
                ),
            )
        )

        try:
            async for event in provider.stream_chat(
                messages,
                temperature=self.config.api.temperature,
                max_tokens=self.config.api.max_tokens,
                tools=tools,
            ):
                if event.kind == "tool_call" and event.tool_calls:
                    return event.tool_calls[0]
                elif event.kind == "delta" and on_event is not None:
                    on_event(AgentEvent(kind="delta", text=event.text))
        except Exception as exc:
            logger.warning("Failed to get corrected edit: %s", exc)
        return None

    @staticmethod
    def _api_calls(calls: list[ToolCall]) -> list[dict[str, object]]:
        """Serialize ToolCalls to the OpenAI wire format for echo-back."""
        return [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in calls
        ]


def run_agent(
    config: Config,
    registry: ToolRegistry,
    prompt: str,
    *,
    on_event: Callable[[AgentEvent], None] | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_edit_retries: int = DEFAULT_MAX_EDIT_RETRIES,
) -> str:
    """Convenience sync entrypoint that spins its own event loop (for tests/CLI)."""
    loop = AgentLoop(config, registry, max_turns=max_turns, max_edit_retries=max_edit_retries)
    try:
        return asyncio.run(loop.run(prompt, on_event=on_event))
    finally:
        asyncio.run(loop.aclose())


__all__ = ["AgentEvent", "AgentLoop", "run_agent"]
