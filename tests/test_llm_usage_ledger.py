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


def test_ledger_path_defaults_under_data(monkeypatch):
    import importlib

    monkeypatch.delenv("LLM_USAGE_LEDGER", raising=False)
    try:
        assert importlib.reload(llm_usage).LEDGER_PATH == llm_usage.Path("data/logs/llm_usage.jsonl")
    finally:
        importlib.reload(llm_usage)


def test_stream_llm_records_usage_from_final_chunk(tmp_path, monkeypatch):
    import asyncio

    from app.assistant import turn_runner

    monkeypatch.setattr(llm_usage, "LEDGER_PATH", tmp_path / "u.jsonl")
    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ab"))]),
        SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=9, completion_tokens=2, total_tokens=11)),
    ]
    seen_kwargs = {}

    def fake_create(client, **kw):
        seen_kwargs.update(kw)
        return iter(chunks)

    monkeypatch.setattr(turn_runner, "create_chat_completion", fake_create)
    monkeypatch.setattr(turn_runner, "get_openai_client", lambda: None)
    deltas = []
    assert asyncio.run(turn_runner.stream_llm([], deltas.append)) == "ab"
    assert deltas == [{"delta": "ab"}]
    assert seen_kwargs["stream_options"] == {"include_usage": True}
    rows = [json.loads(line) for line in (tmp_path / "u.jsonl").read_text().splitlines()]
    assert [(r["stage"], r["prompt_tokens"], r["completion_tokens"]) for r in rows] == [("assistant_stream", 9, 2)]
