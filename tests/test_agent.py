import asyncio

from truecode.config import ApiConfig, Config, LogConfig, UiConfig
from truecode.core.agent import AgentLoop
from truecode.core.tool_registry import default_registry
from truecode.core.workspace import workspace_from
from truecode.providers.base import StreamEvent, ToolCall, Usage


def _config() -> Config:
    return Config(
        api=ApiConfig(
            base_url="http://fake/v1",
            model="fake",
            api_key="ollama",
            temperature=0.7,
            max_tokens=128,
            timeout=10.0,
        ),
        ui=UiConfig(theme="dark"),
        log=LogConfig(level="INFO"),
    )


class FakeProvider:
    """Scripted provider: returns one stream per call."""

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self.calls = 0

    async def stream_chat(self, messages, *, temperature=None, max_tokens=None, tools=None):
        self.calls += 1
        script = self._scripts.pop(0)
        for ev in script:
            yield ev

    async def close(self):
        return None


def _stream(text, calls=None, usage=None):
    events = [StreamEvent(kind="delta", text=text)]
    if calls:
        events.append(StreamEvent(kind="tool_call", tool_calls=calls))
    events.append(
        StreamEvent(kind="usage", usage=usage or Usage(prompt_tokens=5, completion_tokens=3))
    )
    events.append(StreamEvent(kind="end"))
    return events


async def test_agent_answers_without_tools(tmp_path):
    provider = FakeProvider([_stream("done!")])
    loop = AgentLoop(_config(), default_registry(workspace_from(str(tmp_path))), max_turns=3)
    loop.provider = provider
    events = []
    result = await loop.run("hi", on_event=events.append)

    assert result == "done!"
    assert provider.calls == 1
    assert loop.ledger.records[0].prompt_tokens == 5
    assert loop.ledger.summary() != ""
    kinds = [e.kind for e in events]
    assert "delta" in kinds and "done" in kinds


async def test_agent_read_edit_loop(tmp_path):
    (tmp_path / "a.py").write_text("def foo(): ...\n")
    ws = workspace_from(str(tmp_path))
    provider = FakeProvider(
        [
            _stream(
                "reading",
                calls=[ToolCall(id="1", name="read_file", arguments={"path": "a.py"})],
            ),
            _stream(
                "editing",
                calls=[ToolCall(id="2", name="edit_file", arguments={
                    "path": "a.py", "old_string": "foo", "new_string": "bar"
                })],
            ),
            _stream("renamed foo to bar"),
        ]
    )
    loop = AgentLoop(_config(), default_registry(ws), max_turns=5)
    loop.provider = provider
    result = await loop.run("rename foo to bar")

    assert result == "renamed foo to bar"
    assert provider.calls == 3
    assert "def bar(): ..." in (tmp_path / "a.py").read_text()
    assert len(loop.ledger.records) == 3


async def test_agent_respects_max_turns(tmp_path):
    async def forever(messages, *, temperature=None, max_tokens=None, tools=None):
        yield StreamEvent(kind="delta", text="x")
        yield StreamEvent(
            kind="tool_call",
            tool_calls=[ToolCall(id="loop", name="read_file", arguments={"path": "nope.py"})],
        )
        yield StreamEvent(kind="usage", usage=Usage(prompt_tokens=1, completion_tokens=1))
        yield StreamEvent(kind="end")

    class LoopProvider:
        def __init__(self):
            self.calls = 0

        async def stream_chat(self, messages, *, temperature=None, max_tokens=None, tools=None):
            self.calls += 1
            async for ev in forever(
                messages, temperature=temperature, max_tokens=max_tokens, tools=tools
            ):
                yield ev

        async def close(self):
            return None

    provider = LoopProvider()
    loop = AgentLoop(_config(), default_registry(workspace_from(str(tmp_path))), max_turns=2)
    loop.provider = provider
    events = []
    result = await loop.run("loop", on_event=events.append)

    assert "max turns" in result
    assert provider.calls == 2
    assert any(e.kind == "error" for e in events)


async def test_agent_interrupt_mid_turn(tmp_path):
    async def slow_stream(messages, *, temperature=None, max_tokens=None, tools=None):
        yield StreamEvent(kind="delta", text="par")
        await asyncio.sleep(0.1)
        yield StreamEvent(kind="delta", text="tial")
        yield StreamEvent(kind="usage", usage=Usage(prompt_tokens=3, completion_tokens=2))
        yield StreamEvent(kind="end")

    class SlowProvider:
        async def stream_chat(self, messages, *, temperature=None, max_tokens=None, tools=None):
            async for ev in slow_stream(
                messages, temperature=temperature, max_tokens=max_tokens, tools=tools
            ):
                yield ev

        async def close(self):
            return None

    loop = AgentLoop(_config(), default_registry(workspace_from(str(tmp_path))), max_turns=5)
    loop.provider = SlowProvider()

    async def run_and_interrupt():
        task = asyncio.create_task(loop.run("hi"))
        await asyncio.sleep(0.02)
        loop.interrupt()
        return await task

    result = await run_and_interrupt()
    assert result == "par"  # interrupted mid-turn: partial text only
    assert loop._interrupted is True


async def test_agent_forward_thinking_events(tmp_path):
    async def thinking_stream(messages, *, temperature=None, max_tokens=None, tools=None):
        yield StreamEvent(kind="thinking", text="let me")
        yield StreamEvent(kind="thinking", text=" think")
        yield StreamEvent(kind="delta", text="answer")
        yield StreamEvent(kind="usage", usage=Usage(prompt_tokens=2, completion_tokens=2))
        yield StreamEvent(kind="end")

    class ThinkProvider:
        async def stream_chat(self, messages, *, temperature=None, max_tokens=None, tools=None):
            async for ev in thinking_stream(
                messages, temperature=temperature, max_tokens=max_tokens, tools=tools
            ):
                yield ev

        async def close(self):
            return None

    loop = AgentLoop(_config(), default_registry(workspace_from(str(tmp_path))), max_turns=2)
    loop.provider = ThinkProvider()
    events = []
    result = await loop.run("hi", on_event=events.append)

    assert result == "answer"
    thinking = [e.text for e in events if e.kind == "thinking"]
    assert "".join(thinking) == "let me think"


async def test_agent_ask_user_escape_hatch(tmp_path):
    provider = FakeProvider(
        [
            _stream(
                "asking",
                calls=[ToolCall(id="3", name="ask_user", arguments={"question": "which file?"})],
            ),
        ]
    )
    loop = AgentLoop(_config(), default_registry(workspace_from(str(tmp_path))), max_turns=3)
    loop.provider = provider
    events = []
    result = await loop.run("confused", on_event=events.append)

    assert result == "which file?"
    assert any(e.kind == "ask" and "which file?" in e.text for e in events)


async def _perm_agent(tmp_path, decisions):
    """Loop that asks the model to run a command, scripted permission handler."""
    provider = FakeProvider(
        [
            _stream(
                "running",
                calls=[ToolCall(id="4", name="run_command", arguments={"command": "echo hi"})],
            ),
            _stream("done running"),
        ]
    )

    async def handler(command, tool):
        assert command == "echo hi"
        assert tool == "run_command"
        return decisions.pop(0)

    loop = AgentLoop(
        _config(),
        default_registry(workspace_from(str(tmp_path))),
        max_turns=3,
        permission_handler=handler,
    )
    loop.provider = provider
    return loop


async def test_agent_permission_allow_once(tmp_path):
    loop = await _perm_agent(tmp_path, ["allow"])
    result = await loop.run("run it")
    assert result == "done running"


async def test_agent_permission_always_allow_remembers(tmp_path):
    # Two identical run_command calls in one run → only first needs a decision.
    provider = FakeProvider(
        [
            _stream(
                "run1",
                calls=[ToolCall(id="1", name="run_command", arguments={"command": "echo hi"})],
            ),
            _stream(
                "run2",
                calls=[ToolCall(id="2", name="run_command", arguments={"command": "echo hi"})],
            ),
            _stream("finished"),
        ]
    )
    decisions = []

    async def handler(command, tool):
        decisions.append((command, tool))
        return "always"

    loop = AgentLoop(
        _config(),
        default_registry(workspace_from(str(tmp_path))),
        max_turns=4,
        permission_handler=handler,
    )
    loop.provider = provider
    result = await loop.run("run twice")
    assert result == "finished"
    assert decisions == [("echo hi", "run_command")]  # remembered the second time


async def test_agent_permission_deny_stops(tmp_path):
    loop = await _perm_agent(tmp_path, ["deny"])
    events = []
    result = await loop.run("run it", on_event=events.append)

    assert "denied" in result
    assert any(e.kind == "permission_denied" for e in events)
    assert loop._interrupted is True
