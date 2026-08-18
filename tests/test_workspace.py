from truecode.core.errors import FileNotFound_, WorkspaceError
from truecode.core.workspace import Workspace, workspace_from


def make_tree(root, spec: dict[str, str]) -> None:
    for rel, content in spec.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_resolve_normalizes_inside_root(tmp_path):
    ws = Workspace(tmp_path)
    assert ws.resolve("a/b.txt") == (tmp_path / "a/b.txt").resolve()


def test_resolve_rejects_escape(tmp_path):
    ws = Workspace(tmp_path)
    try:
        ws.resolve("../outside.txt")
    except WorkspaceError:
        return
    raise AssertionError("expected WorkspaceError for escaping path")


def test_resolve_rejects_absolute_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "x.txt"
    outside.write_text("data")
    ws = Workspace(root)
    try:
        ws.resolve(str(outside))
    except WorkspaceError:
        return
    raise AssertionError("expected WorkspaceError for absolute out-of-root path")


def test_resolve_rejects_deny_listed(tmp_path):
    ws = Workspace(tmp_path)
    for denied in (".git", "node_modules"):
        try:
            ws.resolve(denied)
        except WorkspaceError:
            continue
        raise AssertionError(f"expected WorkspaceError for deny-listed {denied}")


def test_require_file_missing(tmp_path):
    ws = Workspace(tmp_path)
    try:
        ws.require_file("nope.txt")
    except FileNotFound_:
        return
    raise AssertionError("expected FileNotFound_")


def test_safe_write_backs_up_existing(tmp_path):
    make_tree(tmp_path, {"f.txt": "old"})
    ws = Workspace(tmp_path)
    ws.safe_write("f.txt", "new")
    backup = tmp_path / ".aide-backup" / "f.txt"
    assert backup.read_text() == "old"
    assert (tmp_path / "f.txt").read_text() == "new"


def test_backup_restores_relative_structure(tmp_path):
    make_tree(tmp_path, {"src/a.py": "code"})
    ws = Workspace(tmp_path)
    target = ws.backup("src/a.py")
    assert target == tmp_path / ".aide-backup" / "src" / "a.py"
    assert target.read_text() == "code"


def test_workspace_from(tmp_path):
    ws = workspace_from(tmp_path)
    assert ws.root == tmp_path.resolve()


def test_workspace_from_missing(tmp_path):
    try:
        workspace_from(tmp_path / "missing")
    except WorkspaceError:
        return
    raise AssertionError("expected WorkspaceError for missing dir")


def test_mark_touched(tmp_path):
    ws = Workspace(tmp_path)
    ws.mark_touched("src/a.py")
    assert "src/a.py" in ws.touched
