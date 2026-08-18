"""CLI entry point: `truecode init | shell | chat | config`."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Coroutine
from typing import Any

from aide import __version__
from aide.config import config_dir, load_config, scaffold_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="truecode",
        description="Terminal-native AI code editor.",
    )
    parser.add_argument("--version", action="version", version=f"truecode {__version__}")
    parser.set_defaults(command="shell", project_dir=".", action=None)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Create the default config file if missing.")
    parser_shell = sub.add_parser("shell", help="Launch the interactive TUI.")
    parser_shell.add_argument(
        "project_dir",
        nargs="?",
        default=".",
        help="Workspace root (default: current directory)",
    )
    parser_chat = sub.add_parser("chat", help="One-shot non-interactive request.")
    parser_chat.add_argument("prompt", help="The prompt to send.")
    parser_chat.add_argument("--model", help="Override the configured model.", default=None)
    parser_chat.add_argument("--profile", help="Reserved: named config profiles.", default=None)
    parser_config = sub.add_parser("config", help="Config utilities.")
    parser_config.add_argument("action", choices=["path", "init"], help="What to do.")
    parser_undo = sub.add_parser("undo", help="Restore a file from backup.")
    parser_undo.add_argument("path", help="File path to restore.")
    parser_undo.add_argument("--list", action="store_true", help="List available backups.")
    parser_undo.add_argument("--clear", action="store_true", help="Clear all backups.")
    sub.add_parser("history", help="List all sessions.")
    parser_resume = sub.add_parser("resume", help="Resume a previous session.")
    parser_resume.add_argument("session_id", help="Session ID to resume.")
    return parser


def _run(coro: Coroutine[Any, Any, int]) -> int:
    return asyncio.run(coro)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command is None:
        args.command = "shell"

    if args.command == "init":
        path = scaffold_config()
        print(f"Config ready at {path}")
        return

    if args.command == "config":
        if args.action == "path":
            print(config_dir() / "config.toml")
            return
        path = scaffold_config()
        print(f"Config ready at {path}")
        return

    if args.command == "chat":
        from aide.core.request_handler import get_handler

        config = load_config()
        if args.model:
            config.api.model = args.model
        handler = get_handler(config)

        async def run() -> int:
            try:
                text = await handler.ask(args.prompt)
            except Exception as exc:  # noqa: BLE001 - top-level user-facing
                print(f"error: {exc}", file=sys.stderr)
                return 1
            finally:
                await handler.aclose()
            print(text)
            return 0

        sys.exit(_run(run()))

    if args.command == "shell":
        from aide.tui.app import main as tui_main

        sys.exit(_run(tui_main(args.project_dir)))

    if args.command == "undo":
        from aide.core.workspace import workspace_from

        ws = workspace_from(args.project_dir if hasattr(args, "project_dir") else ".")
        if args.list:
            backups = ws.list_backups()
            if backups:
                print("Available backups:")
                for b in backups:
                    print(f"  {b}")
            else:
                print("No backups found.")
            return
        if args.clear:
            count = ws.clear_backups()
            print(f"Cleared {count} backup file(s).")
            return
        if not args.path:
            print("error: path required for undo", file=sys.stderr)
            sys.exit(1)
        try:
            ws.restore(args.path)
            print(f"Restored {args.path} from backup.")
        except Exception as exc:  # noqa: BLE001
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)

    if args.command == "history":
        from aide.core.history import SessionManager

        mgr = SessionManager()
        sessions = mgr.list_sessions()
        if not sessions:
            print("No sessions found.")
            return
        for s in sessions:
            print(
                f"{s['session_id'][:12]}  "
                f"msgs={s['message_count']}  "
                f"user={s['user_messages']}  "
                f"tokens={s['total_tokens']}  "
                f"last={s['last_ts']}"
            )

    if args.command == "resume":
        from aide.tui.app import main as tui_main

        sys.exit(_run(tui_main(".", resume_session=args.session_id)))


if __name__ == "__main__":
    main()
