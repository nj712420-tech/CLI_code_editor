"""Scrollable conversation log with role-coloured blocks."""

from __future__ import annotations

from textual import events
from textual.containers import VerticalScroll
from textual.message import Message
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Collapsible, Static

try:
    from pygments import highlight
    from pygments.formatters import Terminal256Formatter
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound

    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False


class ChatLog(VerticalScroll):
    """Hosts a list of message blocks; auto-scrolls when new content arrives."""

    ALLOW_SELECT = False

    SELECT_AUTO_SCROLL_LINES: int = 3
    SELECT_AUTO_SCROLL_SPEED: float = 60.0

    BINDINGS = [("g,home", "scroll_home", "Top"), ("G,end", "scroll_end", "Bottom")]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._messages: list[str] = []
        self._selection_start: tuple[int, int] | None = None
        self._selection_end: tuple[int, int] | None = None
        self._auto_scroll_timer: Timer | None = None
        self._thinking_timer: Timer | None = None
        self._thinking_box: Collapsible | None = None
        self._thinking_frame: int = 0

    # ------------------------------------------------------------------
    # Message append methods (also maintain internal model)
    # ------------------------------------------------------------------

    def append_separator(self) -> None:
        self.mount(Static("[dim]────────────────────────────────[/dim]", classes="pair-sep"))
        self._messages.append("")

    def append_user(self, text: str) -> None:
        idx = len(self._messages)
        self.mount(Static(f"[dim cyan]{text}[/dim cyan]", classes="msg-body", id=f"msg-{idx}"))
        self._messages.append(text)
        self.scroll_end(animate=False)

    def start_assistant(self) -> Static:
        self.mount(Static("<<< ", id="ai-stream", classes="msg-body"))
        self.scroll_end(animate=False)
        return self.query_one("#ai-stream", Static)

    def _render_markdown(self, text: str) -> str:
        """Render markdown with syntax highlighting for code blocks."""
        if not PYGMENTS_AVAILABLE:
            return text

        lines = text.splitlines()
        result: list[str] = []
        in_code_block = False
        code_lang = ""
        code_lines: list[str] = []

        for line in lines:
            if line.startswith("```") and not in_code_block:
                in_code_block = True
                code_lang = line[3:].strip() or "text"
                code_lines = []
            elif line.startswith("```") and in_code_block:
                in_code_block = False
                code_text = "\n".join(code_lines)
                try:
                    lexer = get_lexer_by_name(code_lang, stripall=True)
                    formatter = Terminal256Formatter(style="monokai")
                    highlighted = highlight(code_text, lexer, formatter)
                    result.append(highlighted.rstrip())
                except ClassNotFound:
                    result.append(code_text)
            elif in_code_block:
                code_lines.append(line)
            else:
                result.append(line)

        return "\n".join(result)

    def append_assistant(self, text: str) -> None:
        idx = len(self._messages)
        rendered = self._render_markdown(text)
        self.mount(Static(f"<<< {rendered} >>>", classes="msg-body", id=f"msg-{idx}"))
        self._messages.append(text)
        self.scroll_end(animate=False)

    def append_info(self, text: str) -> None:
        idx = len(self._messages)
        self.mount(Static(f"[dim]— {text}[/dim]", classes="info", id=f"msg-{idx}"))
        self._messages.append(text)
        self.scroll_end(animate=False)

    def start_thinking(self) -> Static:
        """Open (collapsed) the collapsible 'thinking' block with animated spinner."""
        body = Static("", id="think-body", classes="think-body")
        box = Collapsible(body, title="[dim]🧠 thinking[/dim]", collapsed=True)
        box.add_class("think-box")
        self.mount(box)
        self._thinking_box = box
        self._thinking_frame = 0
        self._start_thinking_animation()
        self.scroll_end(animate=False)
        return body

    def _start_thinking_animation(self) -> None:
        """Start the snake-like thinking animation."""
        if self._thinking_timer is not None:
            self._thinking_timer.stop()
        self._thinking_timer = self.set_interval(
            0.12,
            self._animate_thinking,
            name="thinking-animation",
            repeat=-1,
        )

    def _animate_thinking(self) -> None:
        """Animate the thinking title with a snake-like floating circle."""
        if self._thinking_box is None:
            return
        frames = ["◐", "◓", "◑", "◒"]
        self._thinking_frame = (self._thinking_frame + 1) % len(frames)
        frame = frames[self._thinking_frame]
        self._thinking_box.title = f"[dim]🧠 thinking {frame}[/dim]"

    def stop_thinking_animation(self) -> None:
        """Stop the thinking animation and clean up."""
        if self._thinking_timer is not None:
            self._thinking_timer.stop()
            self._thinking_timer = None
        if self._thinking_box is not None:
            self._thinking_box.title = "[dim]🧠 thinking[/dim]"
            self._thinking_box = None

    def append_tool(self, call: str, result: str | None = None) -> None:
        """Render an agent tool invocation and its result, if any."""
        if result is None:
            self.mount(Static(f"[yellow]⏳ {call}[/yellow]", classes="info"))
        else:
            colour = "green" if not result.startswith("error") else "red"
            body = result.replace("\n", "\n  ") if len(result) < 400 else result[:400] + "…"
            self.mount(
                Static(f"[dim]  └ {call}[/dim]\n[{colour}]  {body}[/{colour}]", classes="info")
            )
        self._messages.append(f"[tool-{call}]")
        self.scroll_end(animate=False)

    # ------------------------------------------------------------------
    # Widget-to-model index mapping
    # ------------------------------------------------------------------

    def _widget_to_model_index(self, widget: Widget) -> int | None:
        """Convert a mounted widget to its index in the internal messages model."""
        # Check if widget itself has msg- id
        if widget.id and widget.id.startswith("msg-"):
            try:
                return int(widget.id.split("-", 1)[1])
            except ValueError:
                pass

        # Check parent chain for msg- id (e.g., Collapsible children)
        current = widget.parent
        while current is not None:
            if current.id and current.id.startswith("msg-"):
                try:
                    return int(current.id.split("-", 1)[1])
                except ValueError:
                    pass
            current = current.parent

        # Fallback: find by position in children
        for i, child in enumerate(self.children):
            if child is widget:
                return i
            # Check nested children
            for descendant in child.walk_children():
                if descendant is widget:
                    return i
        return None

    # ------------------------------------------------------------------
    # Selection highlight management
    # ------------------------------------------------------------------

    def _clear_selection_highlights(self) -> None:
        """Remove custom selection highlights from all children."""
        for child in self.children:
            child.remove_class("has-custom-selection")

    def _apply_selection_highlights(self) -> None:
        """Apply CSS class to blocks between selection start and end."""
        if self._selection_start is None or self._selection_end is None:
            return

        start_idx = min(self._selection_start[0], self._selection_end[0])
        end_idx = max(self._selection_start[0], self._selection_end[0])

        for i, child in enumerate(self.children):
            if hasattr(child, "classes"):
                if i < len(self._messages) and start_idx <= i <= end_idx:
                    child.add_class("has-custom-selection")
                else:
                    child.remove_class("has-custom-selection")
            # Also highlight nested children (e.g., Collapsible contents)
            for descendant in child.walk_children():
                if hasattr(descendant, "classes"):
                    if i < len(self._messages) and start_idx <= i <= end_idx:
                        descendant.add_class("has-custom-selection")
                    else:
                        descendant.remove_class("has-custom-selection")

    # ------------------------------------------------------------------
    # Mouse event handlers
    # ------------------------------------------------------------------

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """Start selection at mouse down position."""
        self._selection_start = None
        self._selection_end = None

        widget, offset = self.screen.get_widget_and_offset_at(event.x, event.y)

        if widget is not None:
            index = self._widget_to_model_index(widget)
            if index is not None:
                self._selection_start = (index, offset.y if offset else 0)

        self._clear_selection_highlights()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        """Handle mouse movement during selection drag."""
        if self._selection_start is None:
            return

        widget, offset = self.screen.get_widget_and_offset_at(event.x, event.y)

        if widget is not None:
            index = self._widget_to_model_index(widget)
            if index is not None:
                self._selection_end = (index, offset.y if offset else 0)
                self._apply_selection_highlights()

        self._check_auto_scroll(event)

    def _check_auto_scroll(self, event: events.MouseMove) -> None:
        """Check if mouse is near boundaries and start auto-scroll."""
        # Convert screen coordinates to widget-local coordinates
        local_y = event.y - self.region.y
        region = self.region

        scroll_amount = 0

        if local_y < self.SELECT_AUTO_SCROLL_LINES:
            scroll_amount = -1
        elif local_y > region.height - self.SELECT_AUTO_SCROLL_LINES:
            scroll_amount = 1

        if scroll_amount != 0:
            if self._auto_scroll_timer is None or not self._auto_scroll_timer._active:
                self._auto_scroll_timer = self.set_interval(
                    self.SELECT_AUTO_SCROLL_SPEED / 60.0,
                    lambda amt=scroll_amount: self.scroll_relative(y=amt, animate=False),
                    name="chatlog-auto-scroll",
                    repeat=-1,
                )
        else:
            if self._auto_scroll_timer is not None:
                self._auto_scroll_timer.stop()
                self._auto_scroll_timer = None

    def on_mouse_up(self, event: events.MouseUp) -> None:
        """Finalize selection and copy text from the data model."""
        if self._auto_scroll_timer is not None:
            self._auto_scroll_timer.stop()
            self._auto_scroll_timer = None

        self._clear_selection_highlights()

        if self._selection_start is None or self._selection_end is None:
            return

        start_idx = self._selection_start[0]
        end_idx = self._selection_end[0]

        if start_idx > end_idx:
            start_idx, end_idx = end_idx, start_idx

        # Slice text directly from the Python data model (includes scrolled-away blocks)
        selected_texts = self._messages[start_idx : end_idx + 1]
        text = "\n".join(selected_texts)

        self.post_message(CustomSelectionCopied(text))


# ----------------------------------------------------------------------
# Custom message dispatched by ChatLog when selection is copied
# ----------------------------------------------------------------------


class CustomSelectionCopied(Message):
    """Sent when text is selected and copied from the ChatLog."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
