"""Modal screens for aide."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class PermissionScreen(ModalScreen[str]):
    """Asks the user to approve a command the agent wants to run."""

    def __init__(self, command: str) -> None:
        self.command = command
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="perm-dialog"):
            yield Label("Allow this command?", id="perm-title")
            yield Label(f"[dim]{self.command}[/dim]", id="perm-command")
            with Horizontal(id="perm-buttons"):
                yield Button("Allow once", variant="success", id="perm-allow")
                yield Button("Always allow", variant="primary", id="perm-always")
                yield Button("Deny once", variant="error", id="perm-deny")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "perm-allow": "allow",
            "perm-always": "always",
            "perm-deny": "deny",
        }
        self.dismiss(mapping.get(event.button.id, "deny"))  # type: ignore[arg-type]
