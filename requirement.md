# AI CLI Code Editor — Requirements Document

_Status: Draft v1 — Locked decisions recorded; phase contents evolve as we build_

---

## 1. Product Vision

A terminal-native, AI-powered code editor akin to Claude Code / Codex / Cursor, that
lives inside the developer's own workspace. It should let a developer converse with an
AI agent that can read, write, and execute files in the project, apply diffs, and
collaborate over iterative tasks — all from the terminal with a full TUI.

## 2. Locked Decisions (v1)

| Decision   | Choice                                | Rationale                                                      |
| ---------- | ------------------------------------- | -------------------------------------------------------------- |
| Language   | **Python 3.11+**                      | Fast iteration; rich ecosystem for TUI + LLM SDKs              |
| LLM API    | **OpenAI-compatible** (any provider)  | Greps behind `base_url`; works with OpenAI + drop-in providers |
| First UI   | **TUI from day one** (Textual)        | Interactive first-class experience, no rewrite later           |
| CLI style  | Subcommand-style binary (`aide <cmd>`) | Familiar, scriptable, composable                               |

Reference binaries/stacks for inspiration: Claude Code, OpenAI Codex CLI, Cursor
terminal mode.

## 3. Goals

- G1. Conversational agent that understands the current project and executes edits.
- G2. Full TUI: panels, status bar, input box, streaming output, syntax highlighting.
- G3. Safe by default: diffs are reviewed before application; destructive ops confirm.
- G4. Extensible provider support via a single interface.
- G5. Offline-friendly config (local `config.toml`) and reproducible behavior.

## 4. Non-Goals (for now)

- NG1. Full IDE features (refactoring tools, debugger integration).
- NG2. Multiple simultaneous agents / orchestration.
- NG3. Hosted/cloud backend; everything runs locally.
- NG4. Plugin marketplace (plugin system is just a documented hook point).
- NG5. Code indexing/RAG until later phases.

## 5. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        CLI entry (argparse)                  │
│                  `main.py` → route to subcommands            │
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│                       App / Sessions                         │
│   Session manager · prompt builder · history · config        │
└───────┬──────────────────────────────┬───────────────────────┘
        │                              │
┌───────▼─────────────┐        ┌───────▼─────────────────────┐
│      TUI layer      │        │        Agent core           │
│  Textual app        │        │  agent loop · tool calling  │
│  panels / input     │        │  file ops · runner · plan   │
│  streaming renderer │        │  (Phase 1: direct request   │
└─────────────────────┘        │   handler -> provider)      │
                               └───────────┬─────────────────┘
                                           │
                               ┌───────────▼─────────────────┐
                               │     LLM provider layer      │
                               │ OpenAI-compatible client    │
                               │ interface: Provider         │
                               └─────────────────────────────┘
```

Core principles:
- **Thin provider layer** — every capability a provider needs is behind one Python
  interface, so OpenAI + Anthropic + local (Ollama) can coexist.
- **TUI and core are decoupled** — the agent core never imports Textual; the TUI is a
  view. This enables headless mode and testing later.
- **Every phase ends runnable and testable.**

## 6. Conventions

- Package name (placeholder, subject to change): **`aide`** (AI code editor).
- Python 3.11+, type-checked with `mypy`, formatted with `ruff`, tests via `pytest`.
- Config file: `~/.config/aide/config.toml` + optional project-local `.aide.toml`.
- Logging to `~/.local/state/aide/logs/` (structured, not spammy stdout).

---

## Phase 1 — Core CLI Skeleton + Request Handler + Shell TUI

**Goal:** A runnable Python app that can receive a user prompt, send it to an
OpenAI-compatible API using configured credentials, stream the response into a TUI
message panel, and log everything. Nothing agentic yet — just a solid foundation.

### Features
- F1.1 Subcommand CLI:
  - `aide init` — scaffold config file if missing
  - `aide` (no args) / `aide shell` — launch TUI
  - `aide chat "<prompt>"` — one-shot non-interactive request (streams to stdout)
  - `aide --version`, `aide config path`
- F1.2 Config loading: `config.toml` with `[api] base_url, model, api_key` (from env
  var fallback), `[ui] theme`, `[log] level`.
- F1.3 Provider interface (`openai_compatible`): stream chat completion, accept/emit
  SSE (OpenAI streaming). Throws typed errors (auth, timeouts, bad request).
- F1.4 Basic request handler orchestration: prompt → model call → stream → save to
  session history (JSONL, `~/.local/state/aide/sessions/<ts>.jsonl`).
- F1.5 TUI shell (Textual):
  - Left/top panel: scrollable conversation log (user + assistant role coloring)
  - Bottom input box with Enter-to-send, multiline editing
  - Status bar with model + connection state
  - Live streaming: tokens appear incrementally as they arrive
  - `/quit` (or ctrl-d) exits; `/clear` clears panel; `/help` lists commands
- F1.6 Keyboard & UX: ctrl-l clear, esc clears input, scrolling in log panel.
- F1.7 Headless request pipeline shared between `chat` and TUI (same handler class).

### Architecture (new modules)
```
aide/
├── __init__.py
├── __main__.py            # python -m aide
├── cli.py                 # argparse root -> subcommands
├── config.py              # load/merge TOML + env; scaffold via init
├── providers/
│   ├── __init__.py
│   ├── base.py            # Provider ABC: stream_chat()
│   └── openai_compat.py   # httpx-based SSE streaming
├── core/
│   ├── request_handler.py # orchestrate prompt->provider->history
│   ├── history.py         # JSONL session store
│   └── errors.py          # typed exceptions
└── tui/
    ├── app.py             # Textual app
    └── widgets/
        ├── chat_log.py
        ├── input_bar.py
        └── status_bar.py
```

Dependencies: `textual`, `httpx`, `tomli/tomllib` (stdlib in 3.11).

### Deliverables
- Project scaffold: `pyproject.toml`, lint/type/test configs, `Makefile` or task
  scripts (dev / lint / type / test).
- `.env.example` + `aide init` writing `config.toml`.
- Working `aide chat "ping"` against a real or mock provider.
- TUI shell with streaming conversation.
- Unit tests: config merge, provider error mapping, history JSONL round-trip.
- `README.md` quickstart section.

### Exit Criteria
- [ ] `aide init` creates a valid config; overrides via env vars work.
- [ ] `aide chat "hello"` streams a full response to stdout from a live provider.
- [ ] TUI shows streaming assistant output, coloured roles, works with /commands.
- [ ] A session file is written for every round-trip and loads back correctly.
- [ ] `ruff check` and `mypy` pass; `pytest` green.

---

## Phase 2 — File & Workspace Toolkit

**Goal:** Give the agent (and user) the ability to read/write the filesystem within a
workspace root — the first step toward real agentic editing. Still driven from the TUI
chat, but tools exist as callable actions.

### Features
- F2.1 Workspace root detection: `aide <dir>` accepts a target directory; protects
  against out-of-root writes (deny-list `.git`, `node_modules` by default).
- F2.2 File tools exposed to the model and/or TUI commands:
  - `read_file(path, offset, limit)`
  - `edit_file(path, old_string, new_string)` with exact-match preconditions
  - `write_file(path, content)`
  - `ls_tree(path, depth)` / `glob(pattern)`
  - `search(pattern)` via ripgrep when available
- F2.3 Edit safety: dry-run preview, backup of pre-edit file (`.aide-backup/`), and
  reject edits with no/ambiguous match.
- F2.4 TUI `/open <path>`, `/ls`, `/read <path>`, `/edit ...` commands wired to tools.
- F2.5 Track an in-memory index of "touched" files for later diff reporting.

### Architecture
```
aide/core/file_tools.py   # pure functions, no I/O dependency injection yet
aide/core/workspace.py    # root resolution + path guards + safe_write
```

### Deliverables
- Tested `file_tools` with fixture trees.
- TUI file commands + result rendering.

### Exit Criteria
- [ ] Reading a file by offset/limit returns correct slices.
- [ ] `edit_file` fails loudly when match is ambiguous or absent.
- [ ] Writes outside workspace root are rejected.
- [ ] `/read`, `/ls`, `/edit` work from the TUI.

---

## Phase 3 — Agent Loop with Tool Calling

**Goal:** Make the core agentic — the model can decide to call tools, observe results,
and iterate until it answers or hands back control.

### Features
- F3.1 Tool-calling plumbing on top of the provider layer:
  - `tools` declared in request; `tool_calls` in response parsed into actions.
  - Tool execution result (or error) fed back into the next turn.
- F3.2 Loop control: max turns, max tool calls per turn, interrupt (esc / ctrl-c),
  "stop and ask the user" escape hatch.
- F3.3 Tool registry with schemas generated from the Phase 2 functions.
- F3.4 Streaming + tool calls the TUI can render (e.g. "⏳ running read_file …").
- F3.5 Turn-by-turn token accounting (input/output per turn, cumulative).

### Architecture
```
aide/core/agent.py        # AgentLoop: prompt -> (tool|assistant) -> stop
aide/core/tool_registry.py
aide/core/turn_cost.py    # token ledger
```

### Exit Criteria
- [ ] A prompt like “rename function `foo` to `bar` in `src/a.py`” results in correct
  read → edit sequence with no user hand-holding.
- [ ] Loop bounds respected; interrupts work mid-turn.
- [ ] Token ledger written to the session log.

---

## Phase 4 — Diff Application & Auto-Repair

**Goal:** Formalize edits as diffs; show the user what will change; allow the agent to
apply changes with confidence, review, and retry-on-failure.

### Features
- F4.1 Unified-diff generation (`git diff --no-index` style) from file_tool edits.
- F4.2 TUI diff view panel (side-by-side or inline) with apply/abort prompt
  (safe-by-default: **always preview, auto-apply only with `--yes`**).
- F4.3 Apply with concurrency guard (serialize edits; detect conflicting edits).
- F4.4 Auto-repair loop: when an edit precondition fails, the model gets the exact
  failure message and is prompted to retry a corrected edit (bounded retries).
- F4.5 `aide undo` / per-file restore from `.aide-backup/`.

### Exit Criteria
- [ ] Every `edit_file` yields a diff the user can review.
- [ ] Conflicting edits are detected, not silently merged.
- [ ] Failed match leads to a bounded agent retry that self-corrects.

---

## Phase 5 — Conversation Memory & Streaming UX Polish

**Goal:** Make the tool pleasant at scale — context management, resume, and rich TUI.

### Features
- F5.1 Session persistence: `aide resume` / `aide history` / TUI `/sessions`.
- F5.2 Context compaction: automatic summarization of old turns when token budget
  approached (client-side estimate).
- F5.3 TUI: syntax highlighting in the assistant panel (pygments), markdown
  rendering, copy blocks (yank to clipboard), scroll-to-newest toggle.
- F5.4 User edits buffer directly (a real mini-editor pane for scratch notes/edit
  proposals).
- F5.5 Tabbed panels: chat / files / diff / cost — keyboard-togglable.

### Exit Criteria
- [ ] Resume keeps full conversation continuity (history + tool state).
- [ ] Long sessions auto-compact without losing critical context.
- [ ] Highlighted markdown renders in the chat panel.

---

## Phase 6 — Multi-Model & Local Providers

**Goal:** Make the provider layer pay off — any OpenAI-compatible endpoint, plus
Anthropic and local models.

### Features
- F6.1 `Provider` interface implemented for: Anthropic (native), Ollama/local
  (OpenAI-compat), and custom `base_url` registrations.
- F6.2 Model config presets: temperature/max_tokens/stop lists per provider.
- F6.3 Model sync endpoint in TUI status bar (`/model` switching).
- F6.4 Structured error surface: retry with backoff on 429/5xx, clear auth errors.

### Exit Criteria
- [ ] One config switch moves the whole app between ≥3 providers.
- [ ] Backoff/retry demonstrably handles a mocked rate limit.

---

## Phase 7 — Plugins & Extensibility

**Goal:** External hooks so the tool composes with a developer's real workflow.

### Features
- F7.1 Lifecycle hooks: `pre-tool`, `post-tool`, `pre-apply`, `pre-send`
  (JSON event bus; users listen with a Python plugin).
- F7.2 Plugin loading from `~/.local/share/aide/plugins/` (simple Python entry
  points). Documented minimal API.
- F7.3 Custom tools: third-party tools declared by plugins, appearing in the tool
  registry with schemas.
- F7.4 Post-edit generators: `after-edit: git commit -m …`, lint on save.

### Exit Criteria
- [ ] A sample plugin adds a custom tool visible to the agent.
- [ ] Hooks fire with correct payloads (verified by a test plugin).

---

## Phase 8 — Indexing & Project Context (RAG-lite)

**Goal:** Give the agent broad project awareness without stuffing the whole repo into
context.

### Features
- F8.1 Repo scan → file embeddings (or token-based chunk embeddings) stored locally
  (`~/.local/state/aide/index/`).
- F8.2 Semantic search tool (`search_semantic(query, k)`) surfaced to the agent.
- F8.3 Rebuild on file change (watch via `watchdog`), incremental index.
- F8.4 Lazy mode: index only files touched by or near the current task scope.

### Exit Criteria
- [ ] `search_semantic` returns relevant files for queries not matching symbols.
- [ ] Index updates after edits within seconds.

---

## Phase 9 — Safety, Sandboxing, and Execution Control

**Goal:** Make running commands from the agent safe and transparent.

### Features
- F9.1 `run_command` tool with pre-approval flows (approve-once / approve-session /
  allowlisted commands).
- F9.2 Sandboxing options: run in container (Docker), or restricted shell, or
  bash with a deny-list. Config-gated.
- F9.3 Timeouts, env injection control, working-directory locking.
- F9.4 Output truncation + streaming into the TUI log.

### Exit Criteria
- [ ] Command execution requires approval by default; allowlists work.
- [ ] Timeouts kill long-running commands and surface the error.

---

## Phase 10 — Multi-Agent & Advanced Orchestration (Roadmap)

**Goal:** Enterprise-grade workflows. Scoped as future roadmap, not this build-out
order (>= P10 considered optional/stretch).

- F10.1 Sub-agent delegation: `/delegate "task"` spins a capped sub-context.
- F10.2 Plan-then-execute mode: model drafts a plan; user approves steps.
- F10.3 Spec-driven workflows: `aide run specs/*.md` executes doc-defined tasks.
- F10.4 MCP (Model Context Protocol) server/client support.
- F10.5 Packaging: distributable installs (`pipx`, Homebrew), CI, signed releases.

---

## 7. Cross-Cutting Concerns (addressed per phase)

- **Testing:** unit + integration; provider tests use a mock SSE server.
- **Config schema:** strict parsing; unknown keys warn.
- **Security:** never log API keys; redact in output; principle-of-least-privilege
  tool permissions in all phases.
- **Perf:** streaming everywhere; no blocking on provider I/O; large-file reads are
  paginated.
- **Observability:** every model call logged with turn id, latency, token counts.

## 8. Definition of Done (applies to every phase)

1. Feature list implemented and usable from the TUI/CLI.
2. Tests added and passing (`pytest`).
3. `ruff format --check`, `ruff check`, `mypy` clean.
4. New behavior documented in `README.md` / `docs/`.
5. No secrets introduced; config redaction verified.
6. A live smoke test demonstrates the phase's headline feature (where network exists).