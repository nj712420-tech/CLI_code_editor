"""Pure file-tool functions bound to a Workspace (F2.2, F2.3)."""

from __future__ import annotations

import difflib
import glob as stdlib_glob
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from aide.core.diff import FileDiff
from aide.core.errors import AmbiguousMatchError, FileNotFound_, NoMatchError
from aide.core.workspace import Workspace


@dataclass
class ReadResult:
    """A file read with optional offset/limit slicing (1-indexed lines)."""

    path: Path
    total_lines: int
    offset: int
    limit: int | None
    lines: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Render with `N|` line-number prefixes."""
        width = len(str(self.total_lines))
        body = "\n".join(
            f"{self.offset + i:>{width}}| {line}" for i, line in enumerate(self.lines, start=0)
        )
        return f"{self.path}\n{body}"


@dataclass
class EditResult:
    """Outcome of an edit_file call (dry-run or applied)."""

    path: Path
    applied: bool
    preview: str = ""
    backup: Path | None = None
    diff: FileDiff | None = None

    def render(self) -> str:
        status = "applied" if self.applied else "preview (dry-run)"
        return f"{self.path} [{status}]\n{self.preview}"


@dataclass
class WriteResult:
    """Outcome of a write_file call."""

    path: Path
    created: bool
    backup: Path | None = None

    def render(self) -> str:
        status = "created" if self.created else "overwritten"
        backup = f" (backup: {self.backup})" if self.backup else ""
        return f"{self.path} [{status}]{backup}"


@dataclass
class SearchHit:
    """A single ripgrep-style match."""

    path: str
    line_no: int
    text: str

    def render(self) -> str:
        return f"{self.path}:{self.line_no}: {self.text}"


# --- read --------------------------------------------------------------------


def read_file(
    ws: Workspace,
    rel_path: str | Path,
    offset: int = 1,
    limit: int | None = None,
) -> ReadResult:
    """Return a slice of a file. offset/limit are 1-indexed line numbers."""
    path = ws.require_file(rel_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    total = len(lines)
    if offset < 1:
        offset = 1
    start = offset - 1
    end: int | None = None
    if limit is not None:
        if limit < 1:
            return ReadResult(path, total, offset, limit, [])
        end = min(start + limit, total)
    return ReadResult(path, total, offset, limit, lines[start:end])


# --- edit --------------------------------------------------------------------


def _exact_match_indices(content: str, old_string: str) -> list[int]:
    """All 0-based offsets where old_string appears verbatim."""
    indices: list[int] = []
    start = 0
    while True:
        idx = content.find(old_string, start)
        if idx == -1:
            break
        indices.append(idx)
        start = idx + len(old_string)
    return indices


def build_edit_preview(old_string: str, new_string: str) -> str:
    """A small unified-diff style preview of one edit."""
    old_lines = old_string.splitlines() or [""]
    new_lines = new_string.splitlines() or [""]
    diff = difflib.unified_diff(old_lines, new_lines, lineterm="")
    return "\n".join(diff)


def edit_file(
    ws: Workspace,
    rel_path: str | Path,
    old_string: str,
    new_string: str,
    *,
    dry_run: bool = False,
) -> EditResult:
    """Replace the single exact occurrence of old_string.

    Fails loudly when there is no match (NoMatchError) or more than one
    (AmbiguousMatchError). Applies only when dry_run=False, backing up
    the pre-edit file to .aide-backup/.
    """
    from aide.core.diff import FileDiff

    path = ws.require_file(rel_path)
    content = path.read_text(encoding="utf-8")
    matches = _exact_match_indices(content, old_string)
    if not matches:
        raise NoMatchError(f"no exact match for {old_string!r} in {rel_path}")
    if len(matches) > 1:
        raise AmbiguousMatchError(
            f"{old_string!r} matches {len(matches)} times in {rel_path}; "
            "include more context to disambiguate"
        )

    preview = build_edit_preview(old_string, new_string)
    if dry_run:
        return EditResult(path, applied=False, preview=preview)

    # Build the diff for the change
    updated = content.replace(old_string, new_string, 1)
    diff = FileDiff.from_strings(str(rel_path), content, updated)

    backup = ws.backup(rel_path)
    path.write_text(updated, encoding="utf-8")
    ws.mark_touched(rel_path)
    return EditResult(path, applied=True, preview=preview, backup=backup, diff=diff)


# --- write -------------------------------------------------------------------


def write_file(ws: Workspace, rel_path: str | Path, content: str) -> WriteResult:
    """Create or overwrite a file inside the workspace (with backup)."""
    path = ws.resolve(rel_path)
    existed = path.exists()
    backup = ws.backup(rel_path) if existed else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    ws.mark_touched(rel_path)
    return WriteResult(path, created=not existed, backup=backup)


# --- listing -----------------------------------------------------------------


def glob_files(ws: Workspace, pattern: str) -> list[str]:
    """Glob relative to the workspace root; returns relative paths."""
    base = str(ws.root)
    matches = stdlib_glob.glob(f"{base}/{pattern}", recursive=True)
    result: list[str] = []
    for m in matches:
        rel = Path(m).resolve()
        try:
            rel.relative_to(ws.root)
        except ValueError:
            continue
        if any(part in ws.deny_list for part in rel.parts):
            continue
        result.append(rel.relative_to(ws.root).as_posix())
    return sorted(result)


def ls_tree(ws: Workspace, rel_path: str | Path = ".", depth: int = 2) -> str:
    """Render a small indented tree of the workspace up to `depth` levels."""
    root = ws.resolve(rel_path)
    if not root.is_dir():
        raise FileNotFound_(f"not a directory: {rel_path}")

    lines: list[str] = []
    for path in sorted(root.iterdir()):
        if path.name in ws.deny_list:
            continue
        rel = path.relative_to(ws.root)
        depth_here = len(rel.parts) - 1
        indent = "  " * depth_here
        suffix = "/" if path.is_dir() else ""
        lines.append(f"{indent}{path.name}{suffix}")
        if path.is_dir() and depth_here < depth:
            lines.extend(_walk(path, ws, depth_here + 1, depth))
    return "\n".join(lines) or "(empty)"


def _walk(directory: Path, ws: Workspace, level: int, max_depth: int) -> list[str]:
    lines: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.name in ws.deny_list:
            continue
        rel = path.relative_to(ws.root)
        indent = "  " * (len(rel.parts) - 1)
        suffix = "/" if path.is_dir() else ""
        lines.append(f"{indent}{path.name}{suffix}")
        if path.is_dir() and level < max_depth:
            lines.extend(_walk(path, ws, level + 1, max_depth))
    return lines


# --- search ------------------------------------------------------------------


def search_files(ws: Workspace, pattern: str) -> list[SearchHit]:
    """Search the workspace with ripgrep when available, else a python fallback."""
    if shutil.which("rg"):
        return _search_with_rg(ws, pattern)
    return _search_python(ws, pattern)


def _search_with_rg(ws: Workspace, pattern: str) -> list[SearchHit]:
    try:
        proc = subprocess.run(
            ["rg", "--line-number", "--no-heading", "--hidden", "--", pattern, str(ws.root)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    hits: list[SearchHit] = []
    for line in proc.stdout.splitlines():
        # rg output: <path>:<line>:<text> (paths can contain colons on Windows; use rsplit)
        path_part, line_no, text = line.split(":", 2)
        try:
            rel = Path(path_part).resolve().relative_to(ws.root)
        except ValueError:
            continue
        hits.append(SearchHit(rel.as_posix(), int(line_no), text))
    return hits


def _search_python(ws: Workspace, pattern: str) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for path in ws.root.rglob("*"):
        if any(part in ws.deny_list for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern in line:
                hits.append(SearchHit(path.relative_to(ws.root).as_posix(), i, line))
    return hits
