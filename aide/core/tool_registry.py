"""Tool registry — declares file tools to the model and executes calls (F3.3)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aide.core import file_tools
from aide.core.errors import AideError
from aide.core.runner import run_command
from aide.core.workspace import Workspace

JSONSchema = dict[str, Any]


def _format_edit_result(result: file_tools.EditResult) -> str:
    """Format an EditResult including the diff for the model to see."""
    parts = [result.render()]
    if result.diff is not None and result.diff.has_changes():
        parts.append("\n[Diff preview]")
        parts.append(result.diff.to_unified_diff())
    return "\n".join(parts)


class AskUser(AideError):
    """Raised when the model asks the user a question via `ask_user`."""

    def __init__(self, question: str) -> None:
        self.question = question
        super().__init__(question)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: JSONSchema
    handler: Callable[..., Any]
    requires_permission: bool = False


class ToolRegistry:
    """Holds ToolSpecs, exposes OpenAI tool schemas, and dispatches calls."""

    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def requires_permission(self, name: str) -> bool:
        spec = self._tools.get(name)
        return bool(spec and spec.requires_permission)

    def describe(self) -> list[JSONSchema]:
        """OpenAI `tools` request payloads for the registered tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Run a tool, returning a serializable result or error string."""
        spec = self._tools.get(name)
        if spec is None:
            return f"error: unknown tool {name!r}"
        try:
            result = spec.handler(**arguments)
        except AskUser:
            raise
        except AideError as exc:
            return f"error: {exc}"
        except TypeError as exc:
            return f"error: bad arguments for {name}: {exc}"
        if isinstance(result, str):
            return result
        return str(result)


def _ask_user(question: str) -> str:
    raise AskUser(question)


def _run_command(command: str, cwd: Path) -> str:
    return run_command(command, cwd=cwd)


def default_registry(workspace: Workspace) -> ToolRegistry:
    """The standard file-tools registry bound to a workspace."""
    return ToolRegistry(
        [
            ToolSpec(
                name="read_file",
                description=(
                    "Read a text file inside the workspace. `path` is relative to the "
                    "workspace root. `offset` (1-indexed line) and `limit` (max lines) "
                    "paginate large files."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {"type": "integer", "minimum": 1},
                        "limit": {"type": "integer", "minimum": 1},
                    },
                    "required": ["path"],
                },
                handler=lambda path, offset=1, limit=None: file_tools.read_file(
                    workspace, path, offset=offset, limit=limit
                ).render(),
            ),
            ToolSpec(
                name="edit_file",
                description=(
                    "Replace the single exact occurrence of `old_string` with "
                    "`new_string` in a file. Fails loudly if old_string is absent or "
                    "matches more than once (include more surrounding context). "
                    "Backs up the file before editing. Returns a preview diff."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
                handler=lambda path, old_string, new_string: _format_edit_result(
                    file_tools.edit_file(workspace, path, old_string, new_string)
                ),
            ),
            ToolSpec(
                name="write_file",
                description=(
                    "Create a new file (or overwrite an existing one, backing up the "
                    "old contents) with the given content. Path is relative to the "
                    "workspace root."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
                handler=lambda path, content: file_tools.write_file(
                    workspace, path, content
                ).render(),
            ),
            ToolSpec(
                name="list_files",
                description=(
                    "List files and directories inside the workspace as a small tree. "
                    "`path` limits to a subdirectory; `depth` controls nesting."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "."},
                        "depth": {"type": "integer", "minimum": 0, "maximum": 5},
                    },
                },
                handler=lambda path=".", depth=2: file_tools.ls_tree(workspace, path, depth=depth),
            ),
            ToolSpec(
                name="glob_files",
                description=(
                    "Find files by glob pattern (e.g. '**/*.py'). Returns relative paths."
                ),
                parameters={
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}},
                    "required": ["pattern"],
                },
                handler=lambda pattern: "\n".join(file_tools.glob_files(workspace, pattern)),
            ),
            ToolSpec(
                name="search_files",
                description=(
                    "Search file contents for a literal string. Returns "
                    "'path:line: text' matches. Uses ripgrep when available."
                ),
                parameters={
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}},
                    "required": ["pattern"],
                },
                handler=lambda pattern: "\n".join(
                    h.render() for h in file_tools.search_files(workspace, pattern)
                ),
            ),
            ToolSpec(
                name="ask_user",
                description=(
                    "Ask the user a clarifying question. Use this when you need "
                    "information that cannot be found in the workspace. The loop "
                    "pauses until the user replies; their answer is returned here."
                ),
                parameters={
                    "type": "object",
                    "properties": {"question": {"type": "string"}},
                    "required": ["question"],
                },
                handler=_ask_user,
            ),
            ToolSpec(
                name="run_command",
                description=(
                    "Run a shell command in the workspace root (e.g. running or "
                    "testing a file, like `python hsv.py` or `pytest tests/`). "
                    "The user is asked to approve this command before it runs; "
                    "if they deny it, the run is cancelled."
                ),
                parameters={
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
                handler=lambda command: _run_command(command, workspace.root),
                requires_permission=True,
            ),
        ]
    )
