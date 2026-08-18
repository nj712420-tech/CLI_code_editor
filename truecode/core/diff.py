"""Unified diff generation and application (F4.1, F4.3)."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class FileDiff:
    """A unified diff for a single file."""

    path: str
    old_content: str
    new_content: str
    hunks: list[DiffHunk] = field(default_factory=list)

    @classmethod
    def from_strings(cls, path: str, old: str, new: str) -> FileDiff:
        """Create a FileDiff from old and new content strings."""
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        hunks = list(_compute_hunks(old_lines, new_lines))
        return cls(path=path, old_content=old, new_content=new, hunks=hunks)

    def to_unified_diff(self, context_lines: int = 3) -> str:
        """Render as a unified diff string (git diff --no-index style)."""
        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{self.path}",
            tofile=f"b/{self.path}",
            lineterm="",
            n=context_lines,
        )
        return "\n".join(diff)

    def has_changes(self) -> bool:
        """Return True if there are any actual changes."""
        return len(self.hunks) > 0


@dataclass
class DiffHunk:
    """A single hunk in a unified diff."""

    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list[tuple[Literal[" ", "-", "+"], str]] = field(default_factory=list)


def _compute_hunks(old_lines: list[str], new_lines: list[str]) -> list[DiffHunk]:
    """Compute unified diff hunks using difflib.SequenceMatcher."""
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    hunks: list[DiffHunk] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        old_start = i1 + 1
        old_len = i2 - i1
        new_start = j1 + 1
        new_len = j2 - j1

        hunk_lines: list[tuple[Literal[" ", "-", "+"], str]] = []

        if tag in ("delete", "replace"):
            for k in range(i1, i2):
                hunk_lines.append(("-", old_lines[k].rstrip("\n")))
        if tag in ("insert", "replace"):
            for k in range(j1, j2):
                hunk_lines.append(("+", new_lines[k].rstrip("\n")))

        if tag == "replace":
            # Need to also include context lines from both sides
            # For simplicity, we handle replace as delete + insert
            pass

        hunks.append(
            DiffHunk(
                old_start=old_start,
                old_len=old_len,
                new_start=new_start,
                new_len=new_len,
                lines=hunk_lines,
            )
        )

    return hunks


@dataclass
class MultiFileDiff:
    """A collection of file diffs for a single change set."""

    diffs: list[FileDiff] = field(default_factory=list)

    def add(self, diff: FileDiff) -> None:
        self.diffs.append(diff)

    def to_unified_diff(self, context_lines: int = 3) -> str:
        """Render all diffs as a single unified diff."""
        parts = []
        for diff in self.diffs:
            if diff.has_changes():
                parts.append(diff.to_unified_diff(context_lines))
        return "\n".join(parts)

    def affected_files(self) -> list[str]:
        return [d.path for d in self.diffs if d.has_changes()]


class EditConflictError(Exception):
    """Raised when two edits conflict (overlapping regions)."""

    def __init__(self, path: str, conflicting_ranges: list[tuple[int, int]]) -> None:
        self.path = path
        self.conflicting_ranges = conflicting_ranges
        ranges_str = ", ".join(f"{s}-{e}" for s, e in conflicting_ranges)
        super().__init__(f"conflicting edits in {path}: ranges {ranges_str} overlap")


def detect_conflicts(diffs: list[FileDiff]) -> list[EditConflictError]:
    """Detect overlapping edits in the same file."""
    conflicts: list[EditConflictError] = []
    by_path: dict[str, list[FileDiff]] = {}

    for diff in diffs:
        by_path.setdefault(diff.path, []).append(diff)

    for path, file_diffs in by_path.items():
        if len(file_diffs) <= 1:
            continue

        # Check for overlapping hunks
        all_ranges: list[tuple[int, int, FileDiff]] = []
        for diff in file_diffs:
            for hunk in diff.hunks:
                if hunk.lines:  # Only check modified hunks
                    start = hunk.old_start
                    end = hunk.old_start + hunk.old_len
                    all_ranges.append((start, end, diff))

        all_ranges.sort(key=lambda x: x[0])
        for i in range(len(all_ranges)):
            for j in range(i + 1, len(all_ranges)):
                s1, e1, _ = all_ranges[i]
                s2, e2, _ = all_ranges[j]
                if s2 < e1:  # Overlap
                    conflicts.append(EditConflictError(path, [(s1, e1), (s2, e2)]))

    return conflicts


async def apply_diffs(
    workspace_root: Path,
    diffs: list[FileDiff],
    *,
    backup: bool = True,
    allow_conflicts: bool = False,
) -> list[tuple[Path, bool, str]]:
    """Apply a list of diffs to the workspace.

    Returns list of (path, success, message).
    """
    conflicts = detect_conflicts(diffs)
    if conflicts and not allow_conflicts:
        raise conflicts[0]

    results: list[tuple[Path, bool, str]] = []

    for diff in diffs:
        if not diff.has_changes():
            results.append((Path(diff.path), True, "no changes"))
            continue

        path = workspace_root / diff.path
        try:
            if backup and path.exists():
                # Create backup in .aide-backup/
                backup_dir = workspace_root / ".aide-backup"
                backup_path = backup_dir / diff.path
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                path.replace(backup_path)

            # Write new content
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(diff.new_content, encoding="utf-8")
            results.append((path, True, "applied"))
        except OSError as exc:
            results.append((path, False, str(exc)))

    return results
