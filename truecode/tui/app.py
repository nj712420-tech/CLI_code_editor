"""The Textual application: chat log + input bar + status bar."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import events
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Static

from truecode.config import load_config
from truecode.core import file_tools
from truecode.core.agent import AgentEvent, AgentLoop
from truecode.core.errors import AideError
from truecode.core.request_handler import RequestHandler
from truecode.core.tool_registry import default_registry
from truecode.core.workspace import workspace_from
from truecode.providers import ToolCall
from truecode.tui.screens import PermissionScreen
from truecode.tui.widgets.chat_log import ChatLog, CustomSelectionCopied
from truecode.tui.widgets.diff_panel import DiffScreen
from truecode.tui.widgets.input_bar import InputBar
from truecode.tui.widgets.status_bar import StatusBar


class AideApp(App[None]):
    TITLE = "truecode"
    ENABLE_SELECT_AUTO_SCROLL = True
    CSS = """
    Screen { layout: vertical; }
    #chat { height: 1fr; border: round $primary; }
    #input-bar { height: 5; padding: 0 1; border: round $accent; }
    #prompt-input { width: 1fr; border: none; background: $surface; }
    .prompt-chevron { color: $accent; width: 2; height: 3; content-align: center middle; }
    .info { color: $text-muted; text-style: italic; }
    .pair-sep { height: 1; text-style: dim; }
    .msg-body { padding: 0 0 0 0; }
    .has-custom-selection { background: $accent 30%; }
    StatusBar { background: $surface; padding: 0 1; height: 1; }
    ToastRack { align: center bottom; }
    ToastHolder { align-horizontal: center; }
    Toast {
        border: round $success;
        background: $panel-lighten-1;
        color: $text;
        width: auto;
        max-width: 70%;
        height: auto;
        padding: 0 2;
    }
    .think-box {
        margin: 0 0 1 1;
        padding: 0 1;
        border: round $surface-lighten-1;
    }
    .think-box > .collapsible--title {
        color: $text-muted;
    }
    #think-body {
        color: $text-muted;
        text-style: italic;
    }
    #perm-dialog {
        width: 70;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
        align: center middle;
    }
    #perm-title {
        content-align: center middle;
        text-style: bold;
        margin-bottom: 1;
    }
    #perm-command {
        content-align: center middle;
        margin-bottom: 1;
    }
    #perm-buttons {
        height: auto;
        align: center middle;
        padding: 0 1;
    }
    #perm-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+d", "quit", "Quit"),
        Binding("ctrl+l", "clear_log", "Clear"),
        Binding("ctrl+shift+c", "copy", "Copy"),
        Binding("escape", "interrupt", "Stop", priority=True),
    ]

    def __init__(
        self, project_dir: str = ".", resume_session: str | None = None, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.project_dir = Path(project_dir)
        self.config = load_config(self.project_dir)
        self.workspace = workspace_from(self.project_dir)

        if resume_session:
            from truecode.core.history import SessionManager

            mgr = SessionManager()
            self.handler = RequestHandler(self.config)
            self.handler.history = mgr.get_session(resume_session)
            # Replay history to rebuild handler state
            for msg in self.handler.history.messages:
                if msg.role == "user":
                    self.handler.history.record_message("user", msg.content)
                elif msg.role == "assistant":
                    tool_calls = getattr(msg, "tool_calls", None)
                    self.handler.history.record_assistant_message(
                        msg.content, tool_calls=tool_calls
                    )
                elif msg.role == "tool":
                    self.handler.history.record_tool_result(msg.tool_call_id or "", msg.content)
        else:
            self.handler = RequestHandler(self.config)

        self._busy = False
        self._stream: Static | None = None
        self._pieces: list[str] = []
        self._thinking: Static | None = None
        self._thinking_pieces: list[str] = []
        self._agent: AgentLoop | None = None
        self._selecting = False

    def compose(self) -> ComposeResult:
        yield Vertical(
            ChatLog(id="chat"),
            InputBar(id="input-bar"),
            StatusBar(id="status"),
        )
        yield Footer()

    async def on_mount(self) -> None:
        self._set_status("idle")
        self.chat_log().append_info(f"workspace: {self.project_dir.resolve()} · /help")
        if self.config.api.api_key == "ollama":
            self.chat_log().append_info("using local endpoint (Ollama)")

    async def on_unmount(self) -> None:
        if self._agent is not None:
            await self._agent.aclose()
        await self.handler.aclose()

    # helpers -----------------------------------------------------------------

    def chat_log(self) -> ChatLog:
        return self.query_one("#chat", ChatLog)

    def _set_status(self, state: str) -> None:
        self.query_one(StatusBar).update_state(
            model=self.config.api.model,
            status=state,
            session=self.handler.history.session_id,
        )

    # input -------------------------------------------------------------------

    def on_input_bar_submitted(self, message: InputBar.Submitted) -> None:
        prompt = message.text
        if prompt.startswith("/"):
            self.run_worker(self._run_command(prompt))
        else:
            self.run_worker(self._run_user_prompt(prompt))

    async def _run_user_prompt(self, prompt: str) -> None:
        if self._busy:
            self.chat_log().append_info("still working — wait for the stream to end")
            return
        self._busy = True
        self.chat_log().append_user(prompt)
        self._pieces = []
        self._stream = None
        self._thinking = None
        self._thinking_pieces = []
        self._agent = AgentLoop(
            self.config,
            default_registry(self.workspace),
            permission_handler=self._request_permission,
        )
        self._set_status("working")
        try:
            await self._agent.run(prompt, on_event=self._handle_agent_event)
        except AideError as exc:
            self.chat_log().append_info(f"error: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.chat_log().append_info(f"unexpected error: {type(exc).__name__}: {exc}")
        finally:
            await self._agent.aclose()
            self._finish_stream()
            self._busy = False
            self._set_status("idle")

    async def _request_permission(self, command: str, tool: str) -> str:
        """Show the permission dialog; returns allow/always/deny."""
        screen = PermissionScreen(command)
        result = await self.push_screen_wait(screen)
        return result if isinstance(result, str) else "deny"

    async def _handle_agent_event(self, event: AgentEvent) -> None:
        if event.kind == "delta":
            if self._stream is None:
                self.chat_log().stop_thinking_animation()
                self._stream = self.chat_log().start_assistant()
            self._pieces.append(event.text)
            self._stream.update("".join(self._pieces))
            self.chat_log().scroll_end(animate=False)
        elif event.kind == "thinking":
            if self._thinking is None:
                self._thinking = self.chat_log().start_thinking()
            self._thinking_pieces.append(event.text)
            self._thinking.update("".join(self._thinking_pieces))
            self.chat_log().scroll_end(animate=False)
        elif event.kind == "tool_start":
            self._finish_stream()
            if event.call is not None and event.call.name == "edit_file":
                # Show diff preview for edit_file
                await self._show_diff_preview(event.call)
        elif event.kind in ("tool_result", "tool_error"):
            pass
        elif event.kind == "ask":
            self._finish_stream()
            self.chat_log().append_info(f"[bold yellow]{event.text}[/bold yellow]")
        elif event.kind == "permission":
            self.chat_log().append_info(f"[bold]🔐 {event.text}[/bold]")
        elif event.kind == "permission_denied":
            self.chat_log().append_info(f"[bold red]✋ {event.text}[/bold red]")

    async def _show_diff_preview(self, call: ToolCall) -> None:
        """Show a diff preview screen for edit_file calls."""
        path = str(call.arguments.get("path", ""))
        old_string = str(call.arguments.get("old_string", ""))
        new_string = str(call.arguments.get("new_string", ""))

        if not path:
            return

        from truecode.core.diff import FileDiff
        from truecode.core.workspace import workspace_from

        ws = workspace_from(self.project_dir)
        try:
            file_path = ws.require_file(path)
            old_content = file_path.read_text(encoding="utf-8")
            matches = old_content.count(old_string)
            if matches == 1:
                new_content = old_content.replace(old_string, new_string, 1)
                diff = FileDiff.from_strings(path, old_content, new_content)
                if diff.has_changes():
                    applied = await self.app.push_screen_wait(
                        DiffScreen(diff.to_unified_diff(), path)
                    )
                    if not applied:
                        # User aborted - signal back to agent
                        self.chat_log().append_info(
                            f"[yellow]Edit aborted by user: {path}[/yellow]"
                        )
        except Exception:
            pass  # Silently fail, let the agent handle the error

    def _finish_stream(self) -> None:
        if self._stream is not None and self._pieces:
            self.chat_log().append_assistant("".join(self._pieces))
            self._stream.remove()
            self.chat_log().append_separator()
        self._stream = None
        self._pieces = []
        self._thinking = None
        self._thinking_pieces = []

    # commands -----------------------------------------------------------------

    def action_interrupt(self) -> None:
        if self._agent is not None:
            self._agent.interrupt()
            self.chat_log().append_info("stopping…")
        else:
            self.query_one(InputBar).clear()

    def action_clear_log(self) -> None:
        self.run_worker(self._clear_log())

    async def _clear_log(self) -> None:
        await self.chat_log().remove_children()

    def action_copy(self) -> None:
        try:
            self.screen.action_copy_text()
            self.notify("Copied to clipboard", timeout=2)
        except SkipAction:
            self.chat_log().append_info("no text selected — drag to select, then ctrl+shift+c")

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 0:
            self._selecting = True

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._selecting and event.button == 0:
            self._selecting = False

    def on_custom_selection_copied(self, message: CustomSelectionCopied) -> None:
        self.copy_to_clipboard(message.text)
        self.notify("Copied to clipboard", timeout=2)

    async def _run_command(self, raw: str) -> None:
        cmd = raw.split()[0].lower()
        log = self.chat_log()
        parts = raw.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""
        if cmd in ("/quit", "/q"):
            self.exit()
        elif cmd == "/clear":
            await log.remove_children()
        elif cmd == "/model":
            if not arg:
                # Show current model and available presets
                provider = self.config.api.provider
                from truecode.config import get_model_presets

                models = get_model_presets(provider)
                presets = models.get("presets", {})
                lines = [
                    f"[bold]Current model:[/bold] {self.config.api.model} ({provider})",
                    f"[bold]Provider:[/bold] {provider}",
                    "",
                    "[bold]Available presets:[/bold]",
                ]
                for name, preset in presets.items():
                    marker = " *" if name == self.config.api.model else ""
                    lines.append(
                        f"  {name}{marker}  "
                        f"(temp={preset.get('temperature')}, "
                        f"max_tokens={preset.get('max_tokens')})"
                    )
                lines.append("")
                lines.append(
                    "[dim]Usage: /model <preset_name> or /model <provider> <model_name>[/dim]"
                )
                log.append_info("\n".join(lines))
            else:
                # Switch model
                await self._switch_model(arg, log)
        elif cmd == "/workspace":
            log.append_info(f"workspace root: {self.project_dir.resolve()}")
        elif cmd == "/copy":
            self.action_copy()
        elif cmd == "/stop":
            self.action_interrupt()
        elif cmd == "/open":
            self._file_error(log, "open") if not arg else log.append_info(self._render_read(arg))
        elif cmd == "/read":
            self._file_error(log, "read") if not arg else log.append_info(self._render_read(arg))
        elif cmd == "/ls":
            log.append_info(self._render_ls(arg or "."))
        elif cmd == "/edit":
            if not arg:
                self._file_error(log, "edit <path> <old> => <new>")
            else:
                self._render_edit(log, arg)
        elif cmd == "/write":
            if not arg:
                self._file_error(log, "write <path> <content>")
            else:
                self._render_write(log, arg)
        elif cmd == "/search":
            self._file_error(log, "search <pattern>") if not arg else self._render_search(log, arg)
        elif cmd == "/touched":
            log.append_info(self._render_touched())
        elif cmd == "/sessions":
            from truecode.core.history import SessionManager

            mgr = SessionManager()
            sessions = mgr.list_sessions()
            if not sessions:
                log.append_info("No sessions found.")
            else:
                lines = ["[bold]Available sessions:[/bold]"]
                for s in sessions[:20]:
                    lines.append(
                        f"  {s['session_id'][:12]}  "
                        f"msgs={s['message_count']}  "
                        f"user={s['user_messages']}  "
                        f"tokens={s['total_tokens']}  "
                        f"last={s['last_ts']}"
                    )
                log.append_info("\n".join(lines))
                log.append_info("[dim]Use /resume <session_id> to resume[/dim]")
        elif cmd == "/resume":
            if not arg:
                log.append_info("[red]usage: /resume <session_id>[/red]")
            else:
                log.append_info(
                    f"Resuming session {arg}... (restart TUI with: truecode resume {arg})"
                )
        elif cmd in ("/help", "/?"):
            log.append_info(
                "commands: /open /read /ls /edit /write /search /touched /copy"
                " /model /workspace /clear /help /quit /sessions /resume"
            )
        else:
            log.append_info(f"unknown command: {cmd} (try /help)")

    async def _switch_model(self, arg: str, log: ChatLog) -> None:
        """Switch to a different model/preset."""
        parts = arg.split(maxsplit=1)
        from truecode.config import apply_model_preset, get_model_presets

        if len(parts) == 1:
            # Single argument: preset name for current provider
            model_name = parts[0]
            provider = self.config.api.provider
            models = get_model_presets(provider)
            presets = models.get("presets", {})
            if model_name in presets:
                apply_model_preset(self.config, model_name)
                # Recreate handler with new config
                self.handler = RequestHandler(self.config)
                log.append_info(f"[green]Switched to {model_name} ({provider})[/green]")
                self._set_status("idle")
            else:
                log.append_info(f"[red]Unknown preset: {model_name}[/red]")
        elif len(parts) == 2:
            # Two arguments: provider and model name
            provider, model_name = parts
            valid_providers = ["openai_compat", "anthropic", "ollama"]
            if provider not in valid_providers:
                log.append_info(
                    f"[red]Unknown provider: {provider}. Valid: {', '.join(valid_providers)}[/red]"
                )
                return
            models = get_model_presets(provider)
            presets = models.get("presets", {})
            if model_name not in presets:
                log.append_info(f"[red]Unknown model for {provider}: {model_name}[/red]")
                return
            self.config.api.provider = provider
            apply_model_preset(self.config, model_name)
            self.handler = RequestHandler(self.config)
            log.append_info(f"[green]Switched to {provider}:{model_name}[/green]")
            self._set_status("idle")

    # --- file command renderers ---------------------------------------------

    def _file_error(self, log: ChatLog, msg: str) -> None:
        log.append_info(f"[red]usage: {msg}[/red]")

    def _render_read(self, arg: str) -> str:
        try:
            path, _, limit = arg.partition(" ")
            limit_n = int(limit) if limit.strip() else None
            res = file_tools.read_file(self.workspace, path, limit=limit_n)
            return f"[cyan]{res.render()}[/cyan]"
        except AideError as exc:
            return f"[red]{exc}[/red]"

    def _render_ls(self, arg: str) -> str:
        try:
            return file_tools.ls_tree(self.workspace, arg, depth=2)
        except AideError as exc:
            return f"[red]{exc}[/red]"

    def _render_edit(self, log: ChatLog, arg: str) -> None:
        path, _, rest = arg.partition(" ")
        if not path or "=>" not in rest:
            self._file_error(log, "edit <path> <old> => <new>")
            return
        old_string, _, new_string = rest.partition("=>")
        try:
            res = file_tools.edit_file(self.workspace, path, old_string.strip(), new_string.strip())
            log.append_info(f"[green]edited {res.path.name}[/green]")
            log.append_info(res.preview)
        except AideError as exc:
            log.append_info(f"[red]{exc}[/red]")

    def _render_write(self, log: ChatLog, arg: str) -> None:
        path, _, content = arg.partition(" ")
        if not path or not content:
            self._file_error(log, "write <path> <content>")
            return
        try:
            res = file_tools.write_file(self.workspace, path, content)
            action = "created" if res.created else "overwritten"
            log.append_info(f"[green]{action} {res.path.name}[/green]")
        except AideError as exc:
            log.append_info(f"[red]{exc}[/red]")

    def _render_search(self, log: ChatLog, arg: str) -> None:
        try:
            hits = file_tools.search_files(self.workspace, arg)
            if not hits:
                log.append_info("[dim]no matches[/dim]")
                return
            for hit in hits:
                log.append_info(hit.render())
        except AideError as exc:
            log.append_info(f"[red]{exc}[/red]")

    def _render_touched(self) -> str:
        if not self.workspace.touched:
            return "[dim]no files touched yet[/dim]"
        return "\n".join(sorted(self.workspace.touched))


async def main(project_dir: str, resume_session: str | None = None) -> int:
    app = AideApp(project_dir, resume_session=resume_session)
    await app.run_async()
    return 0
