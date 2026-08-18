import pytest

from aide.core.tool_registry import AskUser, ToolRegistry, ToolSpec, default_registry
from aide.core.workspace import workspace_from


@pytest.fixture
def ws(tmp_path):
    return workspace_from(str(tmp_path))


def test_describe_has_openai_shape(ws):
    tools = default_registry(ws).describe()
    assert all(t["type"] == "function" for t in tools)
    names = {t["function"]["name"] for t in tools}
    assert {
        "read_file", "edit_file", "write_file", "list_files",
        "glob_files", "search_files", "ask_user",
    } <= names


def test_read_file_tool(ws, tmp_path):
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n")
    result = default_registry(ws).execute("read_file", {"path": "a.py"})
    assert "line1" in result


def test_write_and_edit_roundtrip(ws, tmp_path):
    reg = default_registry(ws)
    reg.execute("write_file", {"path": "b.py", "content": "def foo(): ...\n"})
    res = reg.execute("edit_file", {"path": "b.py", "old_string": "foo", "new_string": "bar"})
    assert "bar" in res
    assert "def bar(): ..." in (tmp_path / "b.py").read_text()


def test_unknown_tool_returns_error(ws):
    result = default_registry(ws).execute("nope", {})
    assert result.startswith("error")


def test_bad_arguments_return_error(ws):
    result = default_registry(ws).execute("read_file", {"path": "a.py", "limit": -5})
    assert result.startswith("error")


def test_edit_no_match_is_error(ws, tmp_path):
    (tmp_path / "c.py").write_text("hello world\n")
    result = default_registry(ws).execute(
        "edit_file", {"path": "c.py", "old_string": "absent", "new_string": "x"}
    )
    assert result.startswith("error")


def test_ask_user_raises_signal(ws):
    with pytest.raises(AskUser) as exc:
        default_registry(ws).execute("ask_user", {"question": "which dir?"})
    assert exc.value.question == "which dir?"


def test_custom_registry(ws):
    spec = ToolSpec(
        name="echo", description="d", parameters={"type": "object"}, handler=lambda x: x
    )
    reg = ToolRegistry([spec])
    assert "echo" in reg
    assert reg.execute("echo", {"x": 1}) == "1"


def test_run_command_requires_permission(ws, tmp_path):
    (tmp_path / "x.py").write_text("print('ok')\n")
    reg = default_registry(ws)
    assert reg.requires_permission("run_command")
    assert not reg.requires_permission("read_file")
    out = reg.execute("run_command", {"command": "python x.py"})
    assert "ok" in out
