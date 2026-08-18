"""Turn-by-turn token accounting (F3.5)."""

from __future__ import annotations

from dataclasses import dataclass

from aide.providers.base import Usage


@dataclass
class TurnRecord:
    """Token usage attributed to a single agent turn."""

    turn: int
    prompt_tokens: int
    completion_tokens: int

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def usage(self) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )


class TokenLedger:
    """A cumulative, per-turn record of token consumption."""

    def __init__(self) -> None:
        self.records: list[TurnRecord] = []

    def record(self, turn: int, usage: Usage) -> None:
        self.records.append(
            TurnRecord(
                turn=turn,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
            )
        )

    @property
    def total(self) -> Usage:
        total = Usage()
        for rec in self.records:
            total = total + rec.usage
        return total

    def summary(self) -> str:
        total = self.total
        return (
            f"turns: {len(self.records)} · prompt: {total.prompt_tokens} "
            f"· completion: {total.completion_tokens} · total: {total.total}"
        )

    def as_json(self) -> list[dict[str, int]]:
        return [
            {
                "turn": rec.turn,
                "prompt_tokens": rec.prompt_tokens,
                "completion_tokens": rec.completion_tokens,
            }
            for rec in self.records
        ]


__all__ = ["TokenLedger", "TurnRecord"]
