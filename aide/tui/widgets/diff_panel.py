"""TUI diff view panel with apply/abort (F4.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


@dataclass
class DiffHunkView:
    """A renderable diff hunk with line numbers."""

    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list[tuple[Literal[" ", "-", "+"], str]]


class DiffView(Static):
    """Widget that renders a unified diff with syntax highlighting."""

    def __init__(self, diff_text: str, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.diff_text = diff_text

    def render(self) -> str:
        return self.diff_text


class DiffScreen(ModalScreen[bool]):
    """Modal screen showing a diff with Apply/Abort buttons."""

    BINDINGS = [
        Binding("escape", "abort", "Abort"),
        Binding("a", "apply", "Apply"),
    ]

    def __init__(
        self,
        diff_text: str,
        file_path: str,
        *,
        title: str = "Review Changes",
    ):
        super().__init__()
        self.diff_text = diff_text
        self.file_path = file_path
        self._title = title

    def compose(self) -> ComposeResult:
        with Container(id="diff-dialog"):
            yield Label(f"[bold]{self._title}[/bold]")
            yield Label(f"[dim]{self.file_path}[/dim]", id="diff-path")
            yield DiffView(self.diff_text, id="diff-content")
            with Horizontal(id="diff-buttons"):
                yield Button("Apply", variant="success", id="btn-apply")
                yield Button("Abort", variant="error", id="btn-abort")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply":
            self.dismiss(True)
        elif event.button.id == "btn-abort":
            self.dismiss(False)

    def action_apply(self) -> None:
        self.dismiss(True)

    def action_abort(self) -> None:
        self.dismiss(False)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(False)


class MultiFileDiffScreen(ModalScreen[dict[str, bool]]):
    """Modal screen showing multiple file diffs with per-file Apply/Abort."""

    BINDINGS = [
        Binding("escape", "abort_all", "Abort All"),
        Binding("a", "apply_all", "Apply All"),
    ]

    def __init__(
        self,
        diffs: list[tuple[str, str]],
        *,
        title: str = "Review Changes",
    ):
        super().__init__()
        self.diffs = diffs  # list of (file_path, diff_text)
        self._title = title
        self._results: dict[str, bool] = {}

    def compose(self) -> ComposeResult:
        with Container(id="diff-dialog"):
            yield Label(f"[bold]{self._title}[/bold]")
            yield Label(
                f"[dim]{len(self.diffs)} file(s) to review[/dim]",
                id="diff-count",
            )
            with Vertical(id="diff-list"):
                for i, (file_path, diff_text) in enumerate(self.diffs):
                    with Horizontal(classes="diff-item"):
                        yield Label(f"[bold]{file_path}[/bold]", classes="diff-file")
                        yield DiffView(diff_text, classes="diff-content", id=f"diff-{i}")
            with Horizontal(id="diff-buttons"):
                yield Button("Apply All", variant="success", id="btn-apply-all")
                yield Button("Abort All", variant="error", id="btn-abort-all")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply-all":
            self._results = {path: True for path, _ in self.diffs}
            self.dismiss(self._results)
        elif event.button.id == "btn-abort-all":
            self._results = {path: False for path, _ in self.diffs}
            self.dismiss(self._results)

    def action_apply_all(self) -> None:
        self._results = {path: True for path, _ in self.diffs}
        self.dismiss(self._results)

    def action_abort_all(self) -> None:
        self._results = {path: False for path, _ in self.diffs}
        self.dismiss(self._results)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self._results = {path: False for path, _ in self.diffs}
            self.dismiss(self._results)


class DiffApplied(Message):
    """Posted when a diff is applied."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path


class DiffAborted(Message):
    """Posted when a diff is aborted."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
