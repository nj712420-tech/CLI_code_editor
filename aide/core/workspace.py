"""Workspace root resolution, path guards, and safe writes (F2.1, F2.3)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from aide.core.errors import FileNotFound_, WorkspaceError

DENY_LIST: frozenset[str] = frozenset({".git", "node_modules", ".aide-backup", "__pycache__"})

BACKUP_DIRNAME = ".aide-backup"


@dataclass
class Workspace:
    """Bounds every file operation to a single root, with deny-listed paths."""

    root: Path
    deny_list: frozenset[str] = field(default_factory=lambda: DENY_LIST)
    touched: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()

    def mark_touched(self, rel_path: str | Path) -> None:
        """Record a file as modified/created for later diff reporting (F2.5)."""
        self.touched.add(Path(rel_path).as_posix())

    @property
    def backup_dir(self) -> Path:
        return self.root / BACKUP_DIRNAME

    # --- path resolution & guards ------------------------------------------

    def resolve(self, rel_path: str | Path) -> Path:
        """Resolve a workspace-relative path to an absolute, guarded path."""
        candidate = (self.root / Path(rel_path)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError(f"path escapes workspace root: {rel_path}") from exc
        if any(part in self.deny_list for part in candidate.parts):
            raise WorkspaceError(f"path is deny-listed: {rel_path}")
        return candidate

    def require_file(self, rel_path: str | Path) -> Path:
        """Like resolve(), but also asserts the target is an existing file."""
        path = self.resolve(rel_path)
        if not path.is_file():
            raise FileNotFound_(f"file does not exist: {rel_path}")
        return path

    # --- safe writes ---------------------------------------------------------

    def safe_write(self, rel_path: str | Path, content: str) -> Path:
        """Write content inside the workspace, backing up any pre-existing file."""
        path = self.resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.backup(path)
        path.write_text(content, encoding="utf-8")
        return path

    def backup(self, rel_path: str | Path) -> Path:
        """Copy a file into `.aide-backup/` preserving its relative structure."""
        path = self.resolve(rel_path)
        if not path.is_file():
            raise FileNotFound_(f"cannot back up a non-file: {rel_path}")
        target = self.backup_dir / path.relative_to(self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        return target

    def restore(self, rel_path: str | Path) -> Path:
        """Restore a file from `.aide-backup/` to its original location."""
        path = self.resolve(rel_path)
        backup_path = self.backup_dir / path.relative_to(self.root)
        if not backup_path.is_file():
            raise FileNotFound_(f"no backup found for: {rel_path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, path)
        return path

    def list_backups(self) -> list[str]:
        """List all files that have backups available for restore."""
        if not self.backup_dir.exists():
            return []
        backups: list[str] = []
        for path in self.backup_dir.rglob("*"):
            if path.is_file():
                rel = path.relative_to(self.backup_dir)
                backups.append(rel.as_posix())
        return sorted(backups)

    def clear_backups(self) -> int:
        """Remove all backup files. Returns count of removed files."""
        if not self.backup_dir.exists():
            return 0
        count = 0
        for path in self.backup_dir.rglob("*"):
            if path.is_file():
                path.unlink()
                count += 1
        # Clean up empty directories
        for path in sorted(self.backup_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        return count


def workspace_from(project_dir: str | Path = ".") -> Workspace:
    """Build a Workspace from a directory path (defaults to cwd)."""
    root = Path(project_dir).expanduser()
    if not root.exists():
        raise WorkspaceError(f"workspace directory does not exist: {root}")
    if not root.is_dir():
        raise WorkspaceError(f"workspace path is not a directory: {root}")
    return Workspace(root)
