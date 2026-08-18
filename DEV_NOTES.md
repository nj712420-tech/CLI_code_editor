# aide — Dev Notes (current work)

## Hum kya bana rahe hain
**aide** ek AI CLI Code Editor hai (Python 3.11+ / Textual TUI). Phase 3 (Agent Loop + Tool Calling)
kaam complete ho chuka hai. Ab hum aapke latest 3 UX complaints fix kar rahe hain.

## Aapki 3 complaints (current active work)

1. **Selection 10-20 lines tak hi hota hai**
   - Problem: ChatLog m selection drag karte waqt scroll hota hai to upar wale blocks ka
     selection drop ho jata hai (deselect), aur mouse up par poori content copy nahi hoti.
   - Root cause (verified): Textual ka built-in selection **viewport-clipped** hai —
     `selection.py` m `selection_bounds` sirf visible region cover karta hai, aur
     scroll-away blocks ki `region` = `(0,0,0,0)` hoti hai (virtualization). Isliye
     `get_selected_text()` sirf visible text deta hai.
   - Chah rahe hain: select start se, auto-scroll ke saath continue, mouse up par
     **puri** content auto-copy.
   - Files: `aide/tui/widgets/chat_log.py` (custom selection yahan aayegi), `aide/tui/app.py`
     (mouse handlers + copy), `pyproject.toml`, tests `tests/`.

2. **Permission popup attractive nahi hai ("too primary")**
   - Problem: `PermissionScreen` dialog ka styling basic lagta hai.
   - Files: `aide/tui/screens.py` (PermissionScreen), `aide/tui/app.py` (CSS `#perm-dialog` etc).

3. **Arrow keys buttons ke beech focus nahi move karti**
   - Problem: Allow once / Always allow / Deny once ke beech arrow se focus shift nahi hota.
   - Files: `aide/tui/screens.py` (PermissionScreen BINDINGS + focus actions).

## Key facts / constraints

- Commands: `.venv/bin/aide` (TUI), `make lint type test`.
- Quality: `ruff check aide tests`, `ruff format --check aide tests`, `mypy aide` (strict), `pytest -q`.
- Model (verified working): Ollama `gpt-oss:120b-cloud` (default). Tiny models tool_calls
  emit nahi karte. Model overrides: env `AIDE_<SECTION>__<KEY>`.
- Thinking stream: `delta.reasoning` (gpt-oss). Usage tokens: `stream_options.include_usage` added.
- Textual 8.2.8: `Collapsible`, `ModalScreen`, `push_screen_wait`, `ALLOW_SELECT` ClassVar
  (widget.py:328), instance override `widget.ALLOW_SELECT = False` works
  (screen.py mouse-down check `select_widget.allow_select`).
- `get_widget_and_offset_at(x, y)` returns `(widget, offset)` where offset widget content-space
  (scroll-independent per-widget) — useful for custom selection.
- Textual auto-scroll helpers: `textual._auto_scroll.get_auto_scroll_regions(region, lines)`,
  `Screen._start_auto_scroll/_check_auto_scroll` (screen.py:1703-1814), constants
  `MAX_FPS=60`, app `SELECT_AUTO_SCROLL_LINES=3`, `SELECT_AUTO_SCROLL_SPEED=60`.
- `Screen.focus_next()` / `focus_previous()` exist for button navigation.

## Files involved

| File | Role |
|---|---|
| `aide/tui/widgets/chat_log.py` | Custom scroll-aware selection yahan implement hogi |
| `aide/tui/app.py` | TUI main app; mouse handlers, CSS, permission wiring |
| `aide/tui/screens.py` | `PermissionScreen` restyle + arrow-key navigation |
| `aide/core/agent.py` | AgentLoop (permission gating, thinking events) |
| `aide/core/tool_registry.py` | `run_command` tool (requires_permission), `AskUser` |
| `aide/core/runner.py` | `run_command` subprocess runner |
| `aide/providers/openai_compat.py` | `delta.reasoning` thinking + usage stream_options |
| `aide/tui/widgets/status_bar.py`, `input_bar.py` | UI widgets |
| `pyproject.toml` | `pythonpath = ["."]` under pytest ini |
| `tests/` | 74 tests passing (test_agent, test_tool_registry, test_runner, test_turn_cost, provider SSE) |

## Current implementation plan (selection fix)

Custom selection in ChatLog:
1. ChatLog keeps a list of mounted block widgets in order.
2. Disable Textual built-in selection for ChatLog area (`ALLOW_SELECT = False`).
3. Handle `on_mouse_down` (record start widget + content offset via `get_widget_and_offset_at`),
   `on_mouse_move` (update end + own auto-scroll using `get_auto_scroll_regions` + `set_interval`),
   `on_mouse_up` (build full text across ALL blocks in range — including scrolled-away ones — and copy).
4. Visual highlight: add CSS class to blocks in range; keep Textual's per-widget selection
   via `Widget.ALLOW_SELECT` on visible ones OR block-level class highlight.
5. Update `aide/tui/app.py` `_copy_selection` / `on_mouse_up` to use the custom full range.

## Status
- Phase 3 done, 74 tests pass, lint+mypy clean.
- Selection fix: investigation complete, code NOT yet written.
- PermissionScreen restyle + arrow keys: NOT started.
- TODO list in session stale — new todos pending.
