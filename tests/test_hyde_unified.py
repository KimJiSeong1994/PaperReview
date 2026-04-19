"""US-009 Phase B: HyDE 2→1 unified call tests.

Verifies:
- Single gpt-4o-mini JSON call returns (abstract, alt_queries[2]).
- Mocked openai_client.chat.completions.create is invoked exactly once for the
  unified path (no second LLM call).
- On invalid JSON / incomplete response, fallback to individual per-piece
  methods (_generate_hypothetical_abstract + _generate_alt_queries) is used.

All tests are network-free: OpenAI client is fully mocked.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest

from src.graph_rag.hybrid_ranker import HybridRanker


def _make_response(content: Optional[str]) -> MagicMock:
    """Build a mock OpenAI chat completion response wrapping *content*."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _unified_client(payload: dict) -> MagicMock:
    """Mock openai_client returning *payload* as a JSON string."""
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response(json.dumps(payload))
    return client


def test_hyde_unified_single_call_returns_abstract_and_two_alts() -> None:
    """Unified call: exactly 1 LLM invocation, returns (str, [str,str])."""
    payload = {
        "abstract": "This hypothetical abstract explains the proposed method X "
        "achieving state-of-the-art on benchmark Y.",
        "alt_queries": ["alt-rephrase-1", "alt-rephrase-2"],
    }
    client = _unified_client(payload)

    ranker = HybridRanker()
    abstract, alts = ranker._generate_hyde_unified(
        query="transformer attention",
        openai_client=client,
        research_area="NLP",
    )

    assert client.chat.completions.create.call_count == 1
    assert isinstance(abstract, str) and abstract.startswith("This hypothetical")
    assert alts == ["alt-rephrase-1", "alt-rephrase-2"]

    # Assert response_format=json_object and JSON contract requested
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs.get("response_format") == {"type": "json_object"}
    assert call_kwargs.get("model") == "gpt-4o-mini"


def test_hyde_unified_fallback_on_invalid_json() -> None:
    """Invalid JSON triggers fallback → individual _generate_* methods called."""
    client = MagicMock()
    # First call (unified) returns garbage JSON; subsequent calls (fallback
    # individual calls) return valid content.
    client.chat.completions.create.side_effect = [
        _make_response("not a json object {{{"),
        _make_response("Fallback hypothetical abstract body."),
        _make_response("alt fallback 1\nalt fallback 2"),
    ]

    ranker = HybridRanker()
    abstract, alts = ranker._generate_hyde_unified(
        query="quantum error correction",
        openai_client=client,
    )

    # Unified attempt + 2 fallback individual calls = 3 chat.completions.create calls
    assert client.chat.completions.create.call_count == 3
    assert abstract == "Fallback hypothetical abstract body."
    assert alts == ["alt fallback 1", "alt fallback 2"]


def test_hyde_unified_fallback_on_incomplete_response() -> None:
    """Missing alt_queries triggers fallback."""
    client = MagicMock()
    # Unified returns incomplete JSON (only 1 alt query)
    client.chat.completions.create.side_effect = [
        _make_response(json.dumps({"abstract": "ok", "alt_queries": ["only-one"]})),
        _make_response("fallback abstract"),
        _make_response("alt-a\nalt-b"),
    ]

    ranker = HybridRanker()
    abstract, alts = ranker._generate_hyde_unified(
        query="few-shot learning",
        openai_client=client,
    )

    assert client.chat.completions.create.call_count == 3
    assert abstract == "fallback abstract"
    assert alts == ["alt-a", "alt-b"]


def test_hyde_unified_empty_content_triggers_fallback() -> None:
    """Empty LLM content triggers fallback."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _make_response(""),
        _make_response("abs-fb"),
        _make_response("x1\nx2"),
    ]

    ranker = HybridRanker()
    abstract, alts = ranker._generate_hyde_unified(
        query="drug discovery",
        openai_client=client,
    )

    assert client.chat.completions.create.call_count == 3
    assert abstract == "abs-fb"
    assert alts == ["x1", "x2"]


def test_hyde_unified_all_failures_returns_empty() -> None:
    """Unified + fallback both failing → ('', []) graceful degradation."""
    client = MagicMock()
    # All three calls fail (API error simulation)
    client.chat.completions.create.side_effect = RuntimeError("simulated API error")

    ranker = HybridRanker()
    abstract, alts = ranker._generate_hyde_unified(
        query="broken query",
        openai_client=client,
    )

    assert abstract == ""
    assert alts == []


def test_hyde_unified_fallback_when_alt_queries_is_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LLM returns alt_queries as a string (non-list). Should trigger fallback gracefully."""
    import logging

    client = MagicMock()
    # Unified call returns alt_queries as a plain string (not a list).
    client.chat.completions.create.side_effect = [
        _make_response(json.dumps({"abstract": "valid abstract", "alt_queries": "not a list"})),
        _make_response("fallback abstract string"),
        _make_response("fb-alt-1\nfb-alt-2"),
    ]

    ranker = HybridRanker()
    with caplog.at_level(logging.WARNING, logger="src.graph_rag.hybrid_ranker"):
        abstract, alts = ranker._generate_hyde_unified(
            query="graph neural network",
            openai_client=client,
        )

    # Unified attempt + 2 fallback individual calls = 3 total
    assert client.chat.completions.create.call_count == 3
    assert abstract == "fallback abstract string"
    assert alts == ["fb-alt-1", "fb-alt-2"]

    # Confirm grep-friendly marker was logged
    assert any(
        "hyde_unified_fallback_triggered" in record.message
        for record in caplog.records
    ), "Expected 'hyde_unified_fallback_triggered' log marker not found"


def test_hyde_embedding_uses_unified_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """_generate_hyde_embedding should call _generate_hyde_unified (not 2 calls)."""
    # Clear HyDE embedding cache to avoid short-circuit
    from src.graph_rag import hybrid_ranker as hr_mod

    hr_mod._HYDE_CACHE.clear()

    payload = {
        "abstract": "An abstract sentence.",
        "alt_queries": ["q-alt-1", "q-alt-2"],
    }
    client = _unified_client(payload)

    # Stub embeddings.create to return 4 mock vectors (query + abstract + 2 alts)
    class _E:
        def __init__(self, vec: List[float]) -> None:
            self.embedding = vec

    client.embeddings.create.return_value = MagicMock(
        data=[_E([1.0, 0.0]), _E([0.0, 1.0]), _E([1.0, 1.0]), _E([0.5, 0.5])]
    )

    ranker = HybridRanker()
    emb = ranker._generate_hyde_embedding(
        query="novel-query-for-unified-test",
        openai_client=client,
    )

    # Unified path → exactly 1 chat.completions.create call (not 2)
    assert client.chat.completions.create.call_count == 1
    # Embedding produced
    assert emb is not None
    assert hasattr(emb, "shape")
