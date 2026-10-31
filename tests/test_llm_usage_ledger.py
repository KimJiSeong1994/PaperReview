"""The ledger records both usage shapes and never raises on write failure."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.utils import llm_usage


def test_records_responses_and_chat_shapes(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_usage, "LEDGER_PATH", tmp_path / "u.jsonl")
    responses_usage = SimpleNamespace(
        prompt_tokens=10, completion_tokens=20, total_tokens=30,
        response_usage=SimpleNamespace(
            input_tokens_details=SimpleNamespace(cached_tokens=8),
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        ),
    )
    chat_usage = SimpleNamespace(
        prompt_tokens=1, completion_tokens=2, total_tokens=3,
        prompt_tokens_details=SimpleNamespace(cached_tokens=1),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
    )
    llm_usage.record_llm_usage("a", "m", responses_usage, papers=3)
    llm_usage.record_llm_usage("b", "m", chat_usage)
    llm_usage.record_llm_usage("c", "m", None)
    llm_usage.record_llm_usage("d", "m", MagicMock())
    rows = [json.loads(line) for line in (tmp_path / "u.jsonl").read_text().splitlines()]
    assert [r["stage"] for r in rows] == ["a", "b"]
    assert rows[0]["cached_tokens"] == 8 and rows[0]["reasoning_tokens"] == 5 and rows[0]["papers"] == 3
    assert rows[1]["cached_tokens"] == 1 and rows[1]["prompt_tokens"] == 1


def test_write_failure_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_usage, "LEDGER_PATH", tmp_path / "missing.jsonl" / "u.jsonl")
    (tmp_path / "missing.jsonl").write_text("not a dir")
    llm_usage.record_llm_usage("a", "m", SimpleNamespace(prompt_tokens=1))
