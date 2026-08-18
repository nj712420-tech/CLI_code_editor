from aide.core.errors import AmbiguousMatchError, NoMatchError
from aide.core.file_tools import (
    edit_file,
    glob_files,
    ls_tree,
    read_file,
    search_files,
    write_file,
)
from aide.core.workspace import Workspace


def make_tree(root, spec: dict[str, str]) -> None:
    for rel, content in spec.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_read_file_slices(tmp_path):
    make_tree(tmp_path, {"f.txt": "a\nb\nc\nd\ne\n"})
    ws = Workspace(tmp_path)
    res = read_file(ws, "f.txt")
    assert res.total_lines == 5
    assert res.lines == ["a", "b", "c", "d", "e"]
    res = read_file(ws, "f.txt", offset=2, limit=2)
    assert res.lines == ["b", "c"]


def test_read_file_clamps_large_offset(tmp_path):
    make_tree(tmp_path, {"f.txt": "a\nb\n"})
    ws = Workspace(tmp_path)
    res = read_file(ws, "f.txt", offset=99, limit=10)
    assert res.lines == []


def test_edit_file_exact_match(tmp_path):
    make_tree(tmp_path, {"a.py": "def foo():\n    pass\n"})
    ws = Workspace(tmp_path)
    res = edit_file(ws, "a.py", "def foo():", "def bar():")
    assert res.applied is True
    assert (tmp_path / "a.py").read_text() == "def bar():\n    pass\n"
    assert "a.py" in ws.touched
    assert (tmp_path / ".aide-backup" / "a.py").exists()


def test_edit_file_dry_run_does_not_modify(tmp_path):
    make_tree(tmp_path, {"a.py": "def foo():\n"})
    ws = Workspace(tmp_path)
    res = edit_file(ws, "a.py", "foo", "bar", dry_run=True)
    assert res.applied is False
    assert res.preview
    assert (tmp_path / "a.py").read_text() == "def foo():\n"


def test_edit_file_ambiguous_fails_loudly(tmp_path):
    make_tree(tmp_path, {"a.py": "foo\nx foo\nfoo\n"})
    ws = Workspace(tmp_path)
    try:
        edit_file(ws, "a.py", "foo", "bar")
    except AmbiguousMatchError:
        return
    raise AssertionError("expected AmbiguousMatchError")


def test_edit_file_no_match_fails_loudly(tmp_path):
    make_tree(tmp_path, {"a.py": "nothing here\n"})
    ws = Workspace(tmp_path)
    try:
        edit_file(ws, "a.py", "zzz", "bar")
    except NoMatchError:
        return
    raise AssertionError("expected NoMatchError")


def test_write_file_creates(tmp_path):
    ws = Workspace(tmp_path)
    res = write_file(ws, "new.txt", "content")
    assert res.created is True
    assert (tmp_path / "new.txt").read_text() == "content"
    assert "new.txt" in ws.touched


def test_write_file_overwrites_with_backup(tmp_path):
    make_tree(tmp_path, {"f.txt": "old"})
    ws = Workspace(tmp_path)
    res = write_file(ws, "f.txt", "new")
    assert res.created is False
    assert res.backup is not None
    assert (tmp_path / "f.txt").read_text() == "new"


def test_glob_files(tmp_path):
    make_tree(tmp_path, {"src/a.py": "", "src/b.py": "", "docs/c.md": ""})
    ws = Workspace(tmp_path)
    assert glob_files(ws, "**/*.py") == ["src/a.py", "src/b.py"]


def test_glob_excludes_deny_list(tmp_path):
    make_tree(tmp_path, {"node_modules/x.js": "", "app.js": ""})
    ws = Workspace(tmp_path)
    assert glob_files(ws, "**/*.js") == ["app.js"]


def test_ls_tree(tmp_path):
    make_tree(tmp_path, {"src/a.py": "", "src/sub/b.py": "", "root.txt": ""})
    ws = Workspace(tmp_path)
    tree = ls_tree(ws, depth=3)
    assert "src/" in tree
    assert "a.py" in tree
    assert "sub/" in tree
    assert "b.py" in tree


def test_search_files_finds_match(tmp_path):
    make_tree(tmp_path, {"src/a.py": "def hello():\n    pass\n"})
    ws = Workspace(tmp_path)
    hits = search_files(ws, "hello")
    assert len(hits) == 1
    assert hits[0].line_no == 1
    assert hits[0].path == "src/a.py"


def test_search_files_excludes_deny_list(tmp_path):
    make_tree(tmp_path, {"node_modules/x.py": "secret\n", "a.py": "secret\n"})
    ws = Workspace(tmp_path)
    hits = search_files(ws, "secret")
    assert all(h.path != "node_modules/x.py" for h in hits)
    assert any(h.path == "a.py" for h in hits)
