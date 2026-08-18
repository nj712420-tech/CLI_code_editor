"""Safe subprocess runner for agent tools (always permission-gated)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aide.core.errors import AideError

DEFAULT_TIMEOUT = 30.0
MAX_OUTPUT_CHARS = 4000


class CommandError(AideError):
    """Raised when a command fails to run."""


def run_command(command: str, cwd: Path, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Run `command` in `cwd` and return trimmed stdout+stderr.

    Never called directly by the model — the agent loop gates every invocation
    behind user permission first.
    """
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"error: command timed out after {timeout:.0f}s"
    except OSError as exc:
        return f"error: could not start command: {exc}"

    parts: list[str] = []
    if proc.stdout:
        parts.append(proc.stdout)
    if proc.stderr:
        parts.append(f"[stderr]\n{proc.stderr}")
    if not parts:
        parts.append("(no output)")
    output = "\n".join(parts).strip()

    if proc.returncode != 0:
        return f"error: exit code {proc.returncode}\n{output}"
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n…(output truncated)"
    return output


__all__ = ["CommandError", "run_command"]
