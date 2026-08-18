import json

import httpx
import pytest

from truecode.config import ApiConfig
from truecode.core.errors import AuthenticationError, RateLimitError
from truecode.providers.base import ChatMessage
from truecode.providers.openai_compat import OpenAICompatibleProvider


def _cfg(**kw) -> ApiConfig:
    defaults = dict(
        base_url="http://ollama.test/v1",
        model="gpt-oss:120b-cloud",
        api_key="ollama",
        temperature=0.7,
        max_tokens=128,
        timeout=10.0,
    )
    defaults.update(kw)
    return ApiConfig(**defaults)  # type: ignore[arg-type]


def _sse_chunks():
    payloads = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}]},
        {"usage": {"prompt_tokens": 7, "completion_tokens": 2}},
    ]
    for p in payloads:
        yield f"data: {json.dumps(p)}\n\n"
    yield "data: [DONE]\n\n"


async def test_stream_ok(respx_mock):
    route = respx_mock.post("http://ollama.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content="".join(_sse_chunks()), headers={"content-type": "text/event-stream"}
        )
    )
    provider = OpenAICompatibleProvider(_cfg())
    deltas = []
    usage = None
    async for ev in provider.stream_chat([ChatMessage(role="user", content="hi")]):
        if ev.kind == "delta":
            deltas.append(ev.text)
        elif ev.kind == "usage":
            usage = ev
    await provider.close()

    assert "".join(deltas) == "Hello"
    assert usage is not None and usage.usage.completion_tokens == 2
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "gpt-oss:120b-cloud"
    assert sent["stream"] is True


async def test_stream_parses_reasoning(respx_mock):
    respx_mock.post("http://ollama.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content="".join(_reasoning_sse_chunks()),
            headers={"content-type": "text/event-stream"},
        )
    )
    provider = OpenAICompatibleProvider(_cfg())
    thinking = []
    deltas = []
    async for ev in provider.stream_chat([ChatMessage(role="user", content="hi")]):
        if ev.kind == "thinking":
            thinking.append(ev.text)
        elif ev.kind == "delta":
            deltas.append(ev.text)
    await provider.close()

    assert "".join(thinking) == "First I check"
    assert "".join(deltas) == "answer"


async def test_auth_error_maps(respx_mock):
    respx_mock.post("http://ollama.test/v1/chat/completions").mock(
        return_value=httpx.Response(401, text="nope")
    )
    provider = OpenAICompatibleProvider(_cfg())
    with pytest.raises(AuthenticationError):
        async for _ in provider.stream_chat([ChatMessage(role="user", content="hi")]):
            pass  # pragma: no cover
    await provider.close()


async def test_rate_limit_maps(respx_mock):
    respx_mock.post("http://ollama.test/v1/chat/completions").mock(
        return_value=httpx.Response(429, text="slow down")
    )
    provider = OpenAICompatibleProvider(_cfg())
    with pytest.raises(RateLimitError):
        async for _ in provider.stream_chat([ChatMessage(role="user", content="hi")]):
            pass  # pragma: no cover
    await provider.close()


def _tool_sse_chunks():
    payloads = [
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function",
             "function": {"name": "read_file", "arguments": ""}},
        ]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"path": '}},
        ]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"a.py"}'}},
        ]}}]},
        {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]},
        {"usage": {"prompt_tokens": 9, "completion_tokens": 4}},
    ]
    for p in payloads:
        yield f"data: {json.dumps(p)}\n\n"
    yield "data: [DONE]\n\n"


def _reasoning_sse_chunks():
    payloads = [
        {"choices": [{"delta": {"reasoning": "First I"}}]},
        {"choices": [{"delta": {"reasoning": " check"}}]},
        {"choices": [{"delta": {"content": "answer"}}]},
        {"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}]},
        {"usage": {"prompt_tokens": 5, "completion_tokens": 3}},
    ]
    for p in payloads:
        yield f"data: {json.dumps(p)}\n\n"
    yield "data: [DONE]\n\n"


async def test_stream_parses_tool_calls(respx_mock):
    route = respx_mock.post("http://ollama.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content="".join(_tool_sse_chunks()), headers={"content-type": "text/event-stream"}
        )
    )
    provider = OpenAICompatibleProvider(_cfg())
    tool_calls = None
    usage = None
    async for ev in provider.stream_chat(
        [ChatMessage(role="user", content="read a.py")], tools=[{"type": "function"}]
    ):
        if ev.kind == "tool_call":
            tool_calls = ev.tool_calls
        elif ev.kind == "usage":
            usage = ev.usage
    await provider.close()

    assert tool_calls is not None and len(tool_calls) == 1
    assert tool_calls[0].name == "read_file"
    assert tool_calls[0].id == "call_1"
    assert tool_calls[0].arguments == {"path": "a.py"}
    assert tool_calls[0].summary == "read_file(path='a.py')"
    assert usage is not None and usage.prompt_tokens == 9
    sent = json.loads(route.calls.last.request.content)
    assert "tools" in sent
