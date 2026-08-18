from aide.config import ApiConfig, Config, LogConfig, UiConfig
from aide.core.request_handler import RequestHandler
from aide.providers.base import ChatMessage, Provider, StreamEvent, Usage


class FakeProvider(Provider):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(
            config=ApiConfig(
                base_url="", model="fake", api_key="", temperature=0.7, max_tokens=32, timeout=5.0
            )
        )
        self.responses = responses
        self.calls: list[list[ChatMessage]] = []

    async def stream_chat(self, messages, *, temperature=None, max_tokens=None):
        self.calls.append(messages)
        for word in self.responses[-1].split():
            yield StreamEvent(kind="delta", text=word + " ")
        yield StreamEvent(kind="usage", usage=Usage(prompt_tokens=10, completion_tokens=4))
        yield StreamEvent(kind="end")


def _cfg(tmp_path):
    return Config(
        api=ApiConfig(
            base_url="ignored",
            model="fake",
            api_key="k",
            temperature=0.0,
            max_tokens=16,
            timeout=5.0,
        ),
        ui=UiConfig(theme="default"),
        log=LogConfig(level="WARNING"),
        path=None,
    )


async def test_ask_records_and_returns(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "aide.core.request_handler.factory", lambda cfg: FakeProvider(["hello world"])
    )
    handler = RequestHandler(_cfg(tmp_path))
    out = await handler.ask("say hi")
    await handler.aclose()

    assert out == "hello world "
    history = handler.history.messages
    assert history[0].role == "user" and history[0].content == "say hi"
    assert history[-1].role == "assistant" and history[-1].content == "hello world "
    assert handler.history.path.exists()


async def test_system_preamble_prepended(tmp_path, monkeypatch):
    fake = FakeProvider(["done"])
    monkeypatch.setattr("aide.core.request_handler.factory", lambda cfg: fake)
    handler = RequestHandler(_cfg(tmp_path))
    await handler.ask("go")
    await handler.aclose()
    sent = fake.calls[0]
    assert sent[0].role == "system"
    assert "aide" in sent[0].content
    assert sent[-1].content == "go"
