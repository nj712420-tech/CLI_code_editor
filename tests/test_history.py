from pathlib import Path

from truecode.config import state_dir
from truecode.core.history import SessionHistory
from truecode.providers.base import Usage


def test_messages_round_trip(tmp_path: Path):
    base = tmp_path / "sessions"
    h = SessionHistory(session_id="abc123", base=base)
    h.record_message("user", "hello")
    h.record_message("assistant", "hi there")
    h.record_usage(Usage(prompt_tokens=5, completion_tokens=3))

    assert h.path.exists()
    assert [m.content for m in h.messages] == ["hello", "hi there"]

    reopened = SessionHistory.open("abc123", base=base)
    assert [m.role for m in reopened.messages] == ["user", "assistant"]


def test_state_dir_honours_xdg(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert state_dir() == tmp_path / "aide"
