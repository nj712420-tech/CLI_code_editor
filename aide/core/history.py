"""JSONL-backed session history with a small in-memory message cache."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from aide.config import state_dir
from aide.providers.base import ChatMessage, Role, StreamEvent, ToolCall, Usage


class SessionHistory:
    """Appends every round-trip to a single JSONL file per session."""

    def __init__(self, session_id: str | None = None, base: Path | None = None) -> None:
        base = base or state_dir() / "sessions"
        base.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.path = base / f"{self.session_id}.jsonl"
        self._records: list[dict[str, Any]] = []

    @classmethod
    def open(cls, session_id: str, base: Path | None = None) -> SessionHistory:
        inst = cls(session_id=session_id, base=base)
        if inst.path.exists():
            inst._records = [json.loads(line) for line in inst.path.read_text().splitlines()]
        return inst

    @property
    def messages(self) -> list[ChatMessage]:
        msgs: list[ChatMessage] = []
        for rec in self._records:
            if rec.get("type") == "message":
                msgs.append(
                    ChatMessage(
                        role=cast(Role, rec["role"]),
                        content=str(rec["content"]),
                        tool_call_id=rec.get("tool_call_id"),
                        tool_calls=rec.get("tool_calls"),
                    )
                )
            elif rec.get("type") == "tool_result":
                msgs.append(
                    ChatMessage(
                        role="tool",
                        content=str(rec["content"]),
                        tool_call_id=rec.get("tool_call_id"),
                    )
                )
        return msgs

    def record_message(self, role: str, content: str) -> None:
        self._append({"type": "message", "role": role, "content": content})
        self._records.append({"type": "message", "role": role, "content": content})

    def record_assistant_message(
        self, content: str, tool_calls: list[ToolCall] | None = None
    ) -> None:
        record: dict[str, Any] = {
            "type": "message",
            "role": "assistant",
            "content": content,
        }
        if tool_calls:
            record["tool_calls"] = [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                }
                for tc in tool_calls
            ]
        self._append(record)
        self._records.append(record)

    def record_tool_result(self, tool_call_id: str, content: str) -> None:
        record = {
            "type": "tool_result",
            "role": "tool",
            "content": content,
            "tool_call_id": tool_call_id,
        }
        self._append(record)
        self._records.append(record)

    def record_usage(self, usage: Usage) -> None:
        self._append(
            {
                "type": "usage",
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            }
        )
        self._records.append(
            {
                "type": "usage",
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            }
        )

    def record_stream(self, event: StreamEvent) -> None:
        pass  # stream deltas are transient; only terminal events land in history

    def _append(self, record: dict[str, Any]) -> None:
        record.setdefault("ts", datetime.now(UTC).isoformat())
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def summary(self) -> dict[str, Any]:
        """Return a summary of the session for listing."""
        msg_count = sum(1 for r in self._records if r.get("type") == "message")
        user_msgs = sum(1 for r in self._records if r.get("role") == "user")
        total_tokens = sum(
            r.get("prompt_tokens", 0) + r.get("completion_tokens", 0)
            for r in self._records
            if r.get("type") == "usage"
        )
        first_ts = self._records[0].get("ts") if self._records else None
        last_ts = self._records[-1].get("ts") if self._records else None
        return {
            "session_id": self.session_id,
            "message_count": msg_count,
            "user_messages": user_msgs,
            "total_tokens": total_tokens,
            "first_ts": first_ts,
            "last_ts": last_ts,
        }

    def estimate_tokens(self) -> int:
        """Estimate total tokens in the conversation history."""
        # Rough estimate: 4 chars ≈ 1 token for English text
        total_chars = sum(
            len(str(r.get("content", ""))) for r in self._records if r.get("type") == "message"
        )
        usage_tokens = sum(
            int(r.get("prompt_tokens", 0)) + int(r.get("completion_tokens", 0))
            for r in self._records
            if r.get("type") == "usage"
        )
        return total_chars // 4 + usage_tokens

    def compact(
        self,
        max_tokens: int = 8000,
        keep_recent: int = 4,
        summarizer: Any | None = None,
    ) -> bool:
        """Compact history by summarizing old messages when token budget exceeded.

        Args:
            max_tokens: Maximum estimated tokens before compaction triggers.
            keep_recent: Number of recent user-assistant pairs to keep verbatim.
            summarizer: Optional callable that takes old messages and returns a summary string.
                       If None, creates a simple summary without LLM.

        Returns:
            True if compaction was performed, False otherwise.
        """
        if self.estimate_tokens() <= max_tokens:
            return False

        messages = self.messages
        if len(messages) <= keep_recent * 2:
            return False

        # Keep system message if present, and recent messages
        other_msgs = [m for m in messages if m.role != "system"]

        # Keep last N messages (user + assistant pairs)
        keep_count = keep_recent * 2
        recent_msgs = other_msgs[-keep_count:] if len(other_msgs) > keep_count else other_msgs
        old_msgs = other_msgs[:-keep_count] if len(other_msgs) > keep_count else []

        if not old_msgs:
            return False

        # Generate summary
        if summarizer is not None:
            summary_text = summarizer(old_msgs)
        else:
            summary_text = self._generate_simple_summary(old_msgs)

        # Rebuild records: keep system + summary + recent messages
        new_records: list[dict[str, Any]] = []

        # Keep system messages and usage records
        for rec in self._records:
            rec_type = rec.get("type")
            rec_role = rec.get("role")
            if (rec_type == "message" and rec_role == "system") or rec_type == "usage":
                new_records.append(rec)

        # Add summary as a system message
        summary_record = {
            "type": "message",
            "role": "system",
            "content": f"[Previous conversation summary]\n{summary_text}",
        }
        new_records.append(summary_record)

        # Add recent messages
        for msg in recent_msgs:
            record: dict[str, Any] = {
                "type": "message",
                "role": msg.role,
                "content": msg.content,
            }
            if msg.tool_call_id:
                record["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                record["tool_calls"] = msg.tool_calls
            new_records.append(record)

        # Rewrite the file
        with self.path.open("w", encoding="utf-8") as fh:
            for rec in new_records:
                fh.write(json.dumps(rec) + "\n")

        self._records = new_records
        return True

    def _generate_simple_summary(self, messages: list[ChatMessage]) -> str:
        """Generate a simple text summary without LLM."""
        topics: list[str] = []
        files_mentioned: set[str] = set()
        tools_used: set[str] = set()

        for msg in messages:
            content = msg.content.lower()
            if msg.role == "user":
                # Extract potential topics from user messages
                words = content.split()
                for w in words[:10]:  # First 10 words as topic hint
                    if len(w) > 3:
                        topics.append(w)
                        break
            elif msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        tools_used.add(tc.get("name", ""))
                    else:
                        tools_used.add(getattr(tc, "name", ""))

        summary_parts = []
        if topics:
            summary_parts.append(f"Topics discussed: {', '.join(topics[:5])}")
        if files_mentioned:
            summary_parts.append(f"Files: {', '.join(list(files_mentioned)[:5])}")
        if tools_used:
            summary_parts.append(f"Tools used: {', '.join(tools_used)}")
        summary_parts.append(f"Total messages summarized: {len(messages)}")

        return "\n".join(summary_parts)


class SessionManager:
    """Manages multiple sessions - listing, creating, loading."""

    def __init__(self, base: Path | None = None) -> None:
        self.base = base or state_dir() / "sessions"
        self.base.mkdir(parents=True, exist_ok=True)

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions with summaries, sorted by last activity (newest first)."""
        sessions: list[dict[str, Any]] = []
        for path in self.base.glob("*.jsonl"):
            session_id = path.stem
            hist = SessionHistory.open(session_id, self.base)
            sessions.append(hist.summary())
        sessions.sort(key=lambda s: s.get("last_ts") or "", reverse=True)
        return sessions

    def create_session(self) -> SessionHistory:
        """Create a new empty session."""
        return SessionHistory(base=self.base)

    def get_session(self, session_id: str) -> SessionHistory:
        """Load an existing session."""
        return SessionHistory.open(session_id, self.base)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session file. Returns True if deleted."""
        path = self.base / f"{session_id}.jsonl"
        if path.exists():
            path.unlink()
            return True
        return False
