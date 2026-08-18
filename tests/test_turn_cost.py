from truecode.core.turn_cost import TokenLedger
from truecode.providers.base import Usage


def test_ledger_records_and_sums():
    ledger = TokenLedger()
    ledger.record(1, Usage(prompt_tokens=10, completion_tokens=2))
    ledger.record(2, Usage(prompt_tokens=20, completion_tokens=4))

    total = ledger.total
    assert total.prompt_tokens == 30
    assert total.completion_tokens == 6
    assert total.total == 36
    assert len(ledger.records) == 2
    assert ledger.records[0].turn == 1
    assert ledger.records[1].total == 24


def test_ledger_summary_and_json():
    ledger = TokenLedger()
    ledger.record(1, Usage(prompt_tokens=10, completion_tokens=2))
    s = ledger.summary()
    assert "turns: 1" in s and "total: 12" in s
    assert ledger.as_json() == [{"turn": 1, "prompt_tokens": 10, "completion_tokens": 2}]


def test_empty_ledger():
    ledger = TokenLedger()
    assert ledger.total.total == 0
    assert ledger.records == []
