# truecode Setup & Usage Guide

## Overview

**truecode** is a terminal-native AI code editor with a full TUI (Textual User Interface). It lets you converse with an AI agent that can read, write, and edit files in your workspace, apply diffs, and collaborate over iterative tasks — all from the terminal.

---

## Quick Start

### Prerequisites

- **Python 3.11+**
- **Git** (for cloning)
- An OpenAI-compatible API endpoint (Ollama, OpenAI, Anthropic, etc.)

### One-Line Install

```bash
git clone https://github.com/nj712420-tech/CLI_code_editor.git
cd CLI_code_editor
./install.sh --dev
source .venv/bin/activate
truecode shell
```

---

## Detailed Installation

### 1. Clone the Repository

```bash
git clone https://github.com/nj712420-tech/CLI_code_editor.git
cd CLI_code_editor
```

### 2. Run the Installer

The `install.sh` script creates a virtual environment and installs all dependencies.

**Basic install (runtime only):**
```bash
./install.sh
```

**With development tools (pytest, ruff, mypy):**
```bash
./install.sh --dev
```

**Custom virtual environment name:**
```bash
./install.sh --venv myenv --dev
```

**Use a specific Python version:**
```bash
./install.sh --python python3.11 --dev
```

**Skip venv (install in current environment):**
```bash
./install.sh --skip-venv --dev
```

### 3. Activate the Virtual Environment

**Linux/macOS:**
```bash
source .venv/bin/activate
```

**Windows (Command Prompt):**
```cmd
.venv\Scripts\activate
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

### 4. Verify Installation

```bash
truecode --help
```

You should see:
```
usage: truecode [-h] [--version] {init,shell,chat,config,undo,history,resume} ...
```

---

## Configuration

### Initial Config

```bash
truecode init
```

This creates a config file at `~/.config/truecode/config.toml` (Linux/macOS) or `%APPDATA%\truecode\config.toml` (Windows).

### Configure Your API

Edit the config file to set your provider and API key:

```toml
[api]
# Provider: openai_compat, anthropic, ollama
provider = "openai_compat"

# OpenAI-compatible endpoint (Ollama, OpenAI, etc.)
base_url = "http://localhost:11434/v1"

# Model name
model = "llama3.1"

# API key (or set AIDE_API__API_KEY env var)
api_key = "ollama"

temperature = 0.7
max_tokens = 4096
timeout = 120.0
```

**Environment variable override:**
```bash
export AIDE_API__API_KEY="your-api-key"
export AIDE_API__BASE_URL="https://api.openai.com/v1"
export AIDE_API__MODEL="gpt-4o"
```

### Provider Presets

The config includes model presets for each provider:

```toml
[models.openai_compat]
default = "gpt-4o"
[models.openai_compat.presets]
gpt-4o = { temperature = 0.7, max_tokens = 4096 }
gpt-4o-mini = { temperature = 0.7, max_tokens = 4096 }

[models.anthropic]
default = "claude-3-5-sonnet-20241022"
[models.anthropic.presets]
claude-3-5-sonnet-20241022 = { temperature = 0.7, max_tokens = 4096 }

[models.ollama]
default = "llama3.1"
[models.ollama.presets]
llama3.1 = { temperature = 0.7, max_tokens = 4096 }
codellama = { temperature = 0.3, max_tokens = 4096 }
```

---

## Running truecode

### Interactive TUI (Main Interface)

```bash
truecode shell
```

Or specify a project directory:
```bash
truecode shell /path/to/your/project
```

### One-Shot Request (Non-Interactive)

```bash
truecode chat "Refactor the UserService class to use dependency injection"
```

With custom model:
```bash
truecode chat --model gpt-4o "Write a README for this project"
```

### Other Commands

```bash
# List all sessions
truecode history

# Resume a previous session
truecode resume <session_id>

# Undo a file edit (restore from backup)
truecode undo path/to/file.py
truecode undo --list          # List available backups
truecode undo --clear         # Clear all backups

# Config utilities
truecode config path          # Show config file path
truecode config init          # Recreate config
```

---

## TUI Usage

### Interface Layout

```
┌─────────────────────────────────────────────┐
│  Chat Log (scrollable conversation)         │
│  ├─ User messages (cyan)                    │
│  ├─ Assistant messages (streaming)          │
│  ├─ Thinking blocks (collapsible)           │
│  └─ Tool outputs                            │
├─────────────────────────────────────────────┤
│  Input Bar (multi-line, Enter=send)         │
├─────────────────────────────────────────────┤
│  Status Bar (model, connection, session)    │
└─────────────────────────────────────────────┘
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Shift+Enter` | New line in input |
| `Esc` | Clear input / stop agent |
| `Ctrl+C` | Quit |
| `Ctrl+D` | Quit |
| `Ctrl+L` | Clear chat log |
| `Ctrl+Shift+C` | Copy selection to clipboard |
| `↑/↓` | Scroll chat log |
| `PgUp/PgDn` | Page scroll |
| `Home/End` | Jump to top/bottom |

### Mouse Selection

Drag to select text across the entire conversation (including scrolled-away messages). Press `Ctrl+Shift+C` to copy.

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/clear` | Clear chat log |
| `/model` | Show current model & presets |
| `/model <preset>` | Switch to preset (e.g., `/model gpt-4o`) |
| `/model <provider> <model>` | Switch provider & model |
| `/open <path>` | Open a file |
| `/read <path> [limit]` | Read file with line limit |
| `/ls [path] [depth]` | List directory tree |
| `/edit <path> <old> => <new>` | Edit file |
| `/write <path> <content>` | Write file |
| `/search <pattern>` | Search files |
| `/touched` | Show modified files |
| `/sessions` | List conversation sessions |
| `/resume <id>` | Show resume instruction |
| `/copy` | Copy last selection |
| `/stop` | Stop current agent |
| `/quit` or `/q` | Exit TUI |

### Model Switching (In TUI)

```bash
/model                    # List current + presets
/model gpt-4o-mini        # Switch preset
/model anthropic claude-3-5-sonnet-20241022  # Switch provider
```

---

## Agent Capabilities

The AI agent can:

- **Read files** - `read_file(path, offset, limit)`
- **Edit files** - `edit_file(path, old_string, new_string)` with exact-match safety
- **Write files** - `write_file(path, content)` with backup
- **List directories** - `list_files(path, depth)`
- **Glob patterns** - `glob_files(pattern)`
- **Search content** - `search_files(pattern)` (uses ripgrep if available)
- **Run commands** - `run_command(command)` (requires permission)
- **Ask user** - `ask_user(question)` for clarification

### Auto-Repair Loop

If an edit fails (no match / ambiguous match), the agent:
1. Receives the exact error
2. Generates a corrected edit with more context
3. Retries up to 3 times (configurable)

### Diff Preview

Before applying edits, the TUI shows a unified diff with **Apply/Abort** buttons.

---

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Linting & Formatting

```bash
ruff check aide/      # Lint
ruff format aide/     # Format
mypy aide/            # Type check (strict)
```

### Project Structure

```
aide/
├── cli.py              # CLI entry point
├── config.py           # Configuration loading
├── core/
│   ├── agent.py        # Agent loop with tool calling
│   ├── file_tools.py   # File operations
│   ├── history.py      # Session persistence & compaction
│   ├── tool_registry.py# Tool schemas & execution
│   └── workspace.py    # Workspace root & path guards
├── providers/
│   ├── base.py         # Provider interface
│   ├── openai_compat.py# OpenAI-compatible provider
│   ├── anthropic.py    # Anthropic (Claude) provider
│   ├── ollama.py       # Ollama provider
│   └── retry.py        # Exponential backoff retry
└── tui/
    ├── app.py          # Textual app
    └── widgets/
        ├── chat_log.py     # Conversation log with selection
        ├── diff_panel.py   # Diff preview modal
        ├── input_bar.py    # Multi-line input
        └── status_bar.py   # Status display
```

---

## Troubleshooting

### "truecode: command not found"

Make sure the virtual environment is activated:
```bash
source .venv/bin/activate
```

### Connection Errors

Check your config:
```bash
truecode config path
cat ~/.config/truecode/config.toml
```

Verify the API endpoint is reachable:
```bash
curl -H "Authorization: Bearer $AIDE_API__API_KEY" $AIDE_API__BASE_URL/models
```

### Ollama Not Running

Start Ollama:
```bash
ollama serve
# In another terminal:
ollama pull llama3.1
```

### Permission Denied on install.sh

```bash
chmod +x install.sh
```

### Virtual Environment Issues

Delete and recreate:
```bash
rm -rf .venv
./install.sh --dev
```

---

## Advanced Configuration

### Project-Local Config

Create `.aide.toml` in your project root to override settings per-project:

```toml
[api]
model = "gpt-4o"
temperature = 0.3
```

### Custom Base URL Providers

Any OpenAI-compatible endpoint works:
```toml
[api]
provider = "openai_compat"
base_url = "https://your-proxy.example.com/v1"
model = "your-model-name"
api_key = "your-key"
```

### Session Management

Sessions are stored in `~/.local/state/truecode/sessions/` as JSONL files. Each session contains:
- Full conversation history
- Tool calls and results
- Token usage per turn

---

## License

MIT License - see LICENSE file for details.

---

## Support

- Issues: https://github.com/nj712420-tech/CLI_code_editor/issues
- Discussions: https://github.com/nj712420-tech/CLI_code_editor/discussions