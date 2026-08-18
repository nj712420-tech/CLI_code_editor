# Truecode

A terminal-native, AI-powered code editor. Talk to an OpenAI-compatible model from
inside your own workspace — stream responses into a Textual TUI, and keep every
session in JSONL history.

> **Status:** Phase 3 — Agent Loop with Tool Calling.

## Install

Requires Python 3.11+.

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Quickstart

```sh
aide init                       # scaffold ~/.config/aide/config.toml if missing
aide config path                # show the config file location
aide chat "ping"                # one-shot request, streams to stdout
aide                            # launch the interactive TUI (same as `aide shell`)
aide --version
```

By default `aide init` writes a config pointing at a local OpenAI-compatible
endpoint (`http://localhost:11434/v1`, e.g. Ollama). Override anything with
environment variables — see `.env.example`:

```sh
export AIDE_API__MODEL=gpt-oss:120b-cloud
export AIDE_API__BASE_URL=http://localhost:11434/v1
```

Config precedence (lowest → highest): defaults → `.aide.toml` → `~/.config/aide/config.toml`
→ `AIDE_*` environment variables.

## TUI

- **Chat panel** — scrollable conversation log; user / assistant messages are
  colour-coded, and assistant tokens stream in live.
- **Input bar** — Enter sends, Esc clears the input, Ctrl+L clears the panel.
- **Status bar** — shows the active model, connection state, and session id.
- **Commands** — `/clear`, `/model`, `/workspace`, `/help`, `/quit`.
  `Ctrl+C` / `Ctrl+D` also quit.

## Phase 2 — File & workspace tools

The TUI exposes filesystem tools scoped to your workspace root. Out-of-root paths
and deny-listed dirs (`.git`, `node_modules`, `.aide-backup`) are rejected.

| Command                              | Action                                            |
| ------------------------------------ | ------------------------------------------------- |
| `/ls [path]`                         | show a tree of the workspace (depth 2)            |
| `/open <path>` / `/read <path> [n]`  | read a file (optional line limit)                 |
| `/edit <path> <old> => <new>`        | exact-match edit (fails on no/ambiguous match)    |
| `/write <path> <content>`            | create/overwrite a file                           |
| `/search <pattern>`                  | ripgrep (or python fallback) search               |
| `/touched`                           | list files modified this session                  |

Edits are safe by default: the pre-edit file is backed up to `.aide-backup/`
(preserving relative structure), and edits reject ambiguous/absent matches.
Every modified file is tracked in an in-memory "touched" index for later diff
reporting.

## Phase 3 — Agent Loop with Tool Calling

Prompts now run through an agent loop: the model can call workspace tools
(`read_file`, `edit_file`, `write_file`, `list_files`, `glob_files`,
`search_files`), observe results, and iterate until it answers. Tool schemas are
generated from the Phase 2 functions and streamed back in the TUI (e.g.
`⏳ read_file(path='a.py')`).

- **Loop control:** bounded by `max_turns` (default 8) and `max_tool_calls_per_turn`
  (default 8); press `Esc` mid-turn to interrupt, or the model can `ask_user`
  to hand control back for a clarifying question.
- **Token accounting:** each turn's prompt/completion tokens are recorded in a
  `TokenLedger` and rolled into the session history for later diff/usage reports.
- **`/stop`** is available as a command; the model-driven loop means plain prompts
  can now modify files autonomously — verify before trusting destructive edits.

### Interactive thinking & command permissions

- **Thinking block:** reasoning models (e.g. `gpt-oss`) stream their chain of
  thought into a collapsed `🧠 thinking` box. Tap it to expand the faded words;
  tap again to collapse. It streams live as the model thinks.
- **Command permission:** the model can now `run_command` (e.g. `python hsv.py`
  or `pytest tests/`). Every run is gated behind a permission dialog with three
  choices:
  - **Allow once** — run this command, ask again next time.
  - **Always allow** — remember this tool for the rest of the session.
  - **Deny once** — cancel; the agent stops working on the task.
  Denying halts the loop, so nothing destructive happens without your say-so.

## Development

```sh
make lint      # ruff check
make format    # ruff format + fix
make type      # mypy
make test      # pytest
make dev       # textual dev console
```

## Layout

```
aide/
├── cli.py                  # argparse root -> subcommands
├── config.py               # TOML + env merge; `init` scaffolding
├── providers/              # Provider ABC + OpenAI-compatible SSE client
├── core/
│   ├── request_handler.py  # prompt -> provider -> history pipeline
│   ├── history.py          # JSONL session store
│   ├── errors.py           # typed exceptions
│   ├── workspace.py        # root resolution + path guards + safe writes
│   ├── file_tools.py       # read/edit/write/glob/tree/search tools
│   ├── tool_registry.py    # ToolSpec schemas + dispatch (Phase 3)
│   ├── agent.py            # AgentLoop: prompt -> (tool|assistant) -> stop
│   ├── turn_cost.py        # per-turn token ledger (F3.5)
│   └── runner.py           # permission-gated command execution
└── tui/                    # Textual app + widgets + modal screens
```

Sessions are written to `~/.local/state/aide/sessions/<timestamp>.jsonl`.
