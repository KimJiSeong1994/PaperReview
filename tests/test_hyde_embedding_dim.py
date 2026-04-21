"""US-011: HyDE embedding dimension parity regression tests.

Why this exists
---------------
Prior to US-011 ``_generate_hyde_embedding`` hardcoded ``text-embedding-3-small``
(1536 dim) while paper embeddings are produced by
``SimilarityCalculator.get_embeddings_batch`` which picks the model per text
(Korean → ``text-embedding-3-large`` → 3072 dim; English → 1536 dim). When the
two pipelines disagreed, ``np.dot`` in ``_cosine_similarity`` raised
``ValueError`` which was silently swallowed by the outer ``except`` in
``_compute_semantic_scores``, causing semantic scores to collapse to ``0.0`` and
RRF to quietly drop the semantic signal.

These tests lock:

1. HyDE now reuses the same ``SimilarityCalculator`` batch pipeline, so HyDE
   embedding dim always matches paper embedding dim.
2. If a dimension mismatch still occurs (defensive path), a loud
   ``logger.error`` with the ``HyDE dim mismatch`` marker is emitted instead of
   a silent collapse.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.graph_rag import hybrid_ranker as hr_mod
from src.graph_rag.hybrid_ranker import HybridRanker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_hyde_cache() -> None:
    """Clear module-level HyDE cache so tests do not pollute each other."""
    hr_mod._HYDE_CACHE.clear()


def _stub_hyde_unified(ranker: HybridRanker) -> None:
    """Bypass the LLM call — return fixed abstract and alternative queries."""
    ranker._generate_hyde_unified = lambda query, openai_client, research_area="": (  # type: ignore[assignment]
        "hypothetical abstract body",
        ["alt-query-one", "alt-query-two"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_hyde_embedding_matches_paper_dim_3072() -> None:
    """Regression: HyDE embedding dim MUST equal SimilarityCalculator dim (3072)."""
    sim_calc = MagicMock()
    # 4 texts: [query, hypothetical_abstract, alt_1, alt_2]
    sim_calc.get_embeddings_batch.return_value = [
        np.random.randn(3072).astype(np.float64),
        np.random.randn(3072).astype(np.float64),
        np.random.randn(3072).astype(np.float64),
        np.random.randn(3072).astype(np.float64),
    ]

    ranker = HybridRanker(similarity_calculator=sim_calc)
    _stub_hyde_unified(ranker)

    hyde_emb = ranker._generate_hyde_embedding(
        query="comparison of transformer architectures",
        openai_client=MagicMock(),
    )

    assert hyde_emb is not None, "HyDE embedding should be produced"
    assert hyde_emb.shape == (3072,), (
        f"HyDE dim must match paper dim 3072, got {hyde_emb.shape}"
    )
    # Must be L2-normalized (‖v‖ ≈ 1)
    assert abs(float(np.linalg.norm(hyde_emb)) - 1.0) < 1e-6


def test_hyde_embedding_matches_paper_dim_1536() -> None:
    """HyDE dim tracks the calculator's dim — here 1536 (text-embedding-3-small)."""
    sim_calc = MagicMock()
    sim_calc.get_embeddings_batch.return_value = [
        np.random.randn(1536).astype(np.float64) for _ in range(4)
    ]

    ranker = HybridRanker(similarity_calculator=sim_calc)
    _stub_hyde_unified(ranker)

    hyde_emb = ranker._generate_hyde_embedding(
        query="english-only query so small model would be picked",
        openai_client=MagicMock(),
    )

    assert hyde_emb is not None
    assert hyde_emb.shape == (1536,)


def test_hyde_embedding_uses_similarity_calculator_not_openai_client() -> None:
    """When SimilarityCalculator is provided, openai_client.embeddings.create must NOT be called.

    Guards the core fix: the hardcoded ``text-embedding-3-small`` path is
    replaced with the SimilarityCalculator batch path when available.
    """
    sim_calc = MagicMock()
    sim_calc.get_embeddings_batch.return_value = [
        np.ones(3072, dtype=np.float64) for _ in range(4)
    ]

    openai_client = MagicMock()
    # If anything calls this, the test fails loudly.
    openai_client.embeddings.create.side_effect = AssertionError(
        "openai_client.embeddings.create must NOT be called when "
        "SimilarityCalculator is available (US-011 fix)"
    )

    ranker = HybridRanker(similarity_calculator=sim_calc)
    _stub_hyde_unified(ranker)

    hyde_emb = ranker._generate_hyde_embedding(
        query="any query", openai_client=openai_client
    )

    assert hyde_emb is not None
    sim_calc.get_embeddings_batch.assert_called_once()
    openai_client.embeddings.create.assert_not_called()


def test_hyde_embedding_fallback_to_openai_client_without_similarity_calculator() -> None:
    """Without a SimilarityCalculator the legacy openai_client path is preserved."""

    class _E:
        def __init__(self, vec: list[float]) -> None:
            self.embedding = vec

    openai_client = MagicMock()
    openai_client.embeddings.create.return_value = MagicMock(
        data=[_E([1.0, 0.0, 0.0]), _E([0.0, 1.0, 0.0]), _E([0.0, 0.0, 1.0]), _E([0.5, 0.5, 0.5])]
    )

    ranker = HybridRanker(similarity_calculator=None)
    _stub_hyde_unified(ranker)

    hyde_emb = ranker._generate_hyde_embedding(
        query="legacy path",
        openai_client=openai_client,
    )

    assert hyde_emb is not None
    assert hyde_emb.shape == (3,)
    openai_client.embeddings.create.assert_called_once()


def test_hyde_dim_mismatch_logs_loud_error_not_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If a dim mismatch still occurs, logger.error must fire with 'HyDE dim mismatch'.

    Simulates a stale/inconsistent state where HyDE emb is 1536-dim but
    paper emb is 3072-dim. We feed the embeddings directly through the
    semantic scoring path.
    """
    sim_calc = MagicMock()
    # texts: [query, title_0, abstract_0]
    # query → 1536-d (simulates stale HyDE)
    # paper title+abstract → 3072-d
    sim_calc.get_embeddings_batch.return_value = [
        np.random.randn(1536).astype(np.float64),  # query
        np.random.randn(3072).astype(np.float64),  # title
        np.random.randn(3072).astype(np.float64),  # abstract
    ]

    # Provide a real-ish cosine that would raise on shape mismatch
    def _cosine(v1: np.ndarray, v2: np.ndarray) -> float:
        return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))

    sim_calc._cosine_similarity.side_effect = _cosine

    ranker = HybridRanker(similarity_calculator=sim_calc)
    # No HyDE generation → use raw query embedding (first of batch) which here is 1536-d
    # while paper embeddings are 3072-d. This reproduces the silent-failure mode.
    papers = [{"title": "A paper", "abstract": "An abstract"}]

    with caplog.at_level(logging.ERROR, logger="src.graph_rag.hybrid_ranker"):
        scores = ranker._compute_semantic_scores(
            query="test query",
            papers=papers,
            openai_client=None,  # skip HyDE
        )

    # Should return a score list (not exception), with the mismatched field forced to 0
    assert scores == [0.0]

    # Loud error must fire — grep-able marker
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any(
        "HyDE dim mismatch" in r.getMessage() for r in error_records
    ), (
        "Expected 'HyDE dim mismatch' marker in logs but got: "
        + repr([r.getMessage() for r in error_records])
    )


def test_hyde_mixed_language_batch_graceful() -> None:
    """Mixed-dim SC batch (Korean 3072 + English 1536) must not crash."""
    sim_calc = MagicMock()
    sim_calc.get_embeddings_batch.return_value = [
        np.random.randn(1536),  # english query
        np.random.randn(1536),  # english abstract
        np.random.randn(3072),  # korean alt (mixed dim)
        np.random.randn(1536),  # english alt
    ]
    ranker = HybridRanker(similarity_calculator=sim_calc)
    _stub_hyde_unified(ranker)
    emb = ranker._generate_hyde_embedding("test query", openai_client=MagicMock())
    # Must not crash; must produce uniform-dim vector or gracefully None
    assert emb is None or emb.shape in {(1536,), (3072,)}


def test_hyde_fallback_without_sc_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Legacy path (no SC) MUST log warning about dim parity risk."""

    class _E:
        def __init__(self, vec: list) -> None:
            self.embedding = vec

    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = MagicMock(
        data=[_E([0.1] * 1536)] * 4
    )
    ranker = HybridRanker(similarity_calculator=None)
    _stub_hyde_unified(ranker)
    with caplog.at_level(logging.WARNING):
        ranker._generate_hyde_embedding("q", openai_client=mock_client)
    assert any("dim parity" in r.message for r in caplog.records), (
        "Expected 'dim parity' warning in logs but got: "
        + repr([r.message for r in caplog.records])
    )


def test_hyde_truncates_input_to_8000_chars() -> None:
    """Per-text input must be truncated to 8000 chars before calling embeddings."""
    sim_calc = MagicMock()
    sim_calc.get_embeddings_batch.return_value = [
        np.random.randn(1536).astype(np.float64) for _ in range(4)
    ]

    ranker = HybridRanker(similarity_calculator=sim_calc)
    huge_query = "x" * 50_000
    ranker._generate_hyde_unified = lambda query, openai_client, research_area="": (  # type: ignore[assignment]
        "y" * 50_000,
        ["z" * 50_000, "w" * 50_000],
    )

    ranker._generate_hyde_embedding(query=huge_query, openai_client=MagicMock())

    # Inspect the call: every input text must be ≤ 8000 chars
    sim_calc.get_embeddings_batch.assert_called_once()
    (positional_texts,) = sim_calc.get_embeddings_batch.call_args.args
    assert all(len(t) <= 8000 for t in positional_texts)
