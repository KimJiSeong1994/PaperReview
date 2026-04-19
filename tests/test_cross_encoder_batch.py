"""US-009 Phase C+D: Cross-encoder batch_size=32 + (query_hash, paper_id) LRU TTL cache.

Verifies:
- LocalRelevanceScorer.score_papers calls model.predict with batch_size=32.
- HybridRanker._compute_cross_encoder_scores uses a (query_hash, paper_id)
  cache: second identical call does not invoke score_papers again.
- Cache TTL expiry: after 1h+ simulated elapsed time, cache miss → recompute.

All tests mock the cross-encoder model, no sentence-transformers required.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.QueryAgent.relevance_filter import LocalRelevanceScorer
from src.graph_rag import hybrid_ranker as hr_mod
from src.graph_rag.hybrid_ranker import (
    HybridRanker,
    _ce_cache_clear,
    _ce_cache_get,
    _ce_cache_set,
    _ce_query_hash,
)


# ---------------------------------------------------------------------------
# Phase C: batch_size=32 on model.predict
# ---------------------------------------------------------------------------


def test_predict_called_with_batch_size_32() -> None:
    """LocalRelevanceScorer.score_papers must pass batch_size=32 to predict."""
    fake_model = MagicMock()
    # Raw logits → sigmoid produces 0..1 scores; shape must match pairs
    fake_model.predict.return_value = np.array([0.0, 1.0, 2.0])

    papers = [
        {"title": "Paper A", "abstract": "Abstract A"},
        {"title": "Paper B", "abstract": "Abstract B"},
        {"title": "Paper C", "abstract": "Abstract C"},
    ]

    # Patch the classmethod that retrieves the model
    with patch.object(LocalRelevanceScorer, "get_model", return_value=fake_model):
        scores = LocalRelevanceScorer.score_papers("query X", papers)

    # Scoring successful
    assert len(scores) == 3
    # Assert batch_size=32 was explicitly passed
    call_kwargs = fake_model.predict.call_args.kwargs
    assert call_kwargs.get("batch_size") == 32
    assert call_kwargs.get("show_progress_bar") is False


def test_score_papers_determinism_on_same_pairs() -> None:
    """Calling score_papers twice with identical inputs yields identical scores."""
    fake_model = MagicMock()
    fake_model.predict.return_value = np.array([0.5, -0.5])

    papers = [
        {"title": "P1", "abstract": "a1"},
        {"title": "P2", "abstract": "a2"},
    ]

    with patch.object(LocalRelevanceScorer, "get_model", return_value=fake_model):
        s1 = LocalRelevanceScorer.score_papers("q", papers)
        s2 = LocalRelevanceScorer.score_papers("q", papers)

    assert s1 == s2
    assert len(s1) == 2


# ---------------------------------------------------------------------------
# Phase D: (query_hash, paper_id) LRU TTL cache
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_ce_cache() -> None:
    """Clear CE cache before each test to avoid cross-test pollution."""
    _ce_cache_clear()
    yield
    _ce_cache_clear()


def _ce_papers() -> List[Dict[str, Any]]:
    return [
        {"paper_id": "pA", "title": "A", "abstract": "aa"},
        {"paper_id": "pB", "title": "B", "abstract": "bb"},
        {"paper_id": "pC", "title": "C", "abstract": "cc"},
    ]


def test_cache_hit_avoids_score_papers_recompute() -> None:
    """Second call with same (query, paper_ids) should not invoke score_papers again."""
    papers = _ce_papers()

    with patch.object(
        LocalRelevanceScorer, "score_papers", return_value=[0.1, 0.2, 0.3]
    ) as mock_score:
        ranker = HybridRanker()
        # First call: 3 misses → score_papers called once with all 3
        scores1 = ranker._compute_cross_encoder_scores("query-Z", papers)
        assert scores1 == [0.1, 0.2, 0.3]
        assert mock_score.call_count == 1

        # Second call: same query + same paper_ids → all hits, no new score_papers call
        # NOTE: fresh paper dicts to avoid paper['_cross_encoder_score'] short-circuit
        fresh_papers = _ce_papers()
        scores2 = ranker._compute_cross_encoder_scores("query-Z", fresh_papers)
        assert scores2 == [0.1, 0.2, 0.3]
        assert mock_score.call_count == 1  # Still 1 — all cache hits


def test_cache_partial_hit_only_computes_misses() -> None:
    """Pre-populated cache for 2 of 3 papers → score_papers called with 1 paper."""
    query = "partial-hit-query"
    q_hash = _ce_query_hash(query)
    # Pre-populate cache for pA and pC
    _ce_cache_set(q_hash, "pA", 0.11)
    _ce_cache_set(q_hash, "pC", 0.33)

    papers = _ce_papers()  # pA, pB, pC — only pB is a miss

    # score_papers should be called only with the miss (pB) and return 1 score
    with patch.object(
        LocalRelevanceScorer, "score_papers", return_value=[0.22]
    ) as mock_score:
        ranker = HybridRanker()
        scores = ranker._compute_cross_encoder_scores(query, papers)

    assert mock_score.call_count == 1
    # Inspect positional args: (query, miss_papers)
    called_query, called_papers = mock_score.call_args.args
    assert called_query == query
    assert [p["paper_id"] for p in called_papers] == ["pB"]
    # Final scores preserve original paper order
    assert scores == [0.11, 0.22, 0.33]


def test_cache_ttl_expires() -> None:
    """Entry older than _CE_CACHE_TTL must not be returned."""
    q_hash = _ce_query_hash("ttl-query")
    _ce_cache_set(q_hash, "pX", 0.77)
    assert _ce_cache_get(q_hash, "pX") == 0.77

    # Simulate 1h + 1s elapsed by rewinding stored timestamp
    key = (q_hash, "pX")
    score_val, ts = hr_mod._CE_CACHE[key]
    hr_mod._CE_CACHE[key] = (score_val, ts - (hr_mod._CE_CACHE_TTL + 1))

    assert _ce_cache_get(q_hash, "pX") is None
    # Expired entry must be evicted
    assert key not in hr_mod._CE_CACHE


def test_cache_different_queries_are_isolated() -> None:
    """Different query hashes must not share cache entries for the same paper."""
    hA = _ce_query_hash("alpha")
    hB = _ce_query_hash("beta")
    _ce_cache_set(hA, "p1", 0.9)

    assert _ce_cache_get(hA, "p1") == 0.9
    assert _ce_cache_get(hB, "p1") is None


def test_cache_key_fallback_uses_title_hash_when_no_id() -> None:
    """Papers without id/paper_id/arxiv_id/doi still cache correctly via title hash."""
    papers = [{"title": "No-ID Paper", "abstract": "x"}]

    with patch.object(
        LocalRelevanceScorer, "score_papers", return_value=[0.42]
    ) as mock_score:
        ranker = HybridRanker()
        s1 = ranker._compute_cross_encoder_scores("qid", papers)
        assert s1 == [0.42]
        assert mock_score.call_count == 1

        # Second call: fresh dicts but same title → cache hit
        s2 = ranker._compute_cross_encoder_scores("qid", [{"title": "No-ID Paper", "abstract": "x"}])
        assert s2 == [0.42]
        assert mock_score.call_count == 1  # Still 1 — title hash matched


def test_query_hash_stable_length_and_determinism() -> None:
    """_ce_query_hash returns 16 chars and is deterministic."""
    h1 = _ce_query_hash("some query")
    h2 = _ce_query_hash("some query")
    h3 = _ce_query_hash("different query")
    assert len(h1) == 16
    assert h1 == h2
    assert h1 != h3
