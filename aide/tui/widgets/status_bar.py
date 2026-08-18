"""Status bar: model, connection state, session id."""

from __future__ import annotations

from textual.widgets import Static

from aide import __version__


class StatusBar(Static):
    def update_state(self, *, model: str, status: str, session: str) -> None:
        self.update(
            f"[bold cyan] truecode[/bold cyan] v{__version__}  "
            f"[dim]model[/dim] {model}  "
            f"{state_colour(status)}  "
            f"[dim]session[/dim] {session}"
        )


def state_colour(status: str) -> str:
    colour = {
        "idle": "green",
        "streaming": "yellow",
        "working": "yellow",
        "error": "red",
    }.get(status, "green")
    return f"[{colour}]{status}[/{colour}]"
