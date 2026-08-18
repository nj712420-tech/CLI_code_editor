"""Prompt area: a multiline TextArea with Enter-to-send, Shift+Enter newline."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static, TextArea


class InputBar(Horizontal):
    """Bottom input: a "»" marker plus a focused multiline TextArea."""

    class Submitted(Message):
        """Posted when the user presses Enter with text present."""

        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    BINDINGS = [
        Binding("enter", "submit", "Send", priority=True),
        Binding("shift+enter", "newline", "New line"),
        Binding("escape", "clear_input", "Clear input"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.input = TextArea(
            "",
            id="prompt-input",
            placeholder="Type your query here — Enter sends, Shift+Enter new line",
            soft_wrap=True,
            show_line_numbers=False,
        )

    def compose(self) -> ComposeResult:
        yield Static("»", classes="prompt-chevron")
        yield self.input

    async def on_mount(self) -> None:
        self.input.focus()

    # actions -----------------------------------------------------------------

    def action_submit(self) -> None:
        text = self.input.text.strip()
        if not text:
            self.input.focus()
            return
        self.input.clear()
        self.input.focus()
        self.post_message(self.Submitted(text))

    def action_newline(self) -> None:
        self.input.insert("\n")

    def action_clear_input(self) -> None:
        self.input.clear()
        self.input.focus()

    def clear(self) -> None:
        self.input.clear()
        self.input.focus()
