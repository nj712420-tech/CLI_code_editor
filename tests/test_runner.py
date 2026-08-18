from aide.core.runner import run_command
from aide.core.workspace import workspace_from


def test_run_command_success(tmp_path):
    ws = workspace_from(str(tmp_path))
    (tmp_path / "a.py").write_text("print('hello')\n")
    out = run_command("python a.py", cwd=ws.root)
    assert "hello" in out


def test_run_command_nonzero_exit(tmp_path):
    ws = workspace_from(str(tmp_path))
    out = run_command("exit 3", cwd=ws.root)
    assert "error: exit code 3" in out


def test_run_command_timeout(tmp_path):
    ws = workspace_from(str(tmp_path))
    out = run_command("sleep 5", cwd=ws.root, timeout=0.2)
    assert "timed out" in out


def test_run_command_no_output(tmp_path):
    ws = workspace_from(str(tmp_path))
    out = run_command("true", cwd=ws.root)
    assert "(no output)" in out
