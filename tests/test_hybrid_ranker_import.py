"""Regression test: routers.search._hybrid_ranker must initialize.

Prior to the fix, ``routers/search.py`` used ``from graph_rag.hybrid_ranker
import HybridRanker`` (missing the ``src.`` prefix). The ModuleNotFoundError
was silently swallowed, leaving ``_hybrid_ranker = None`` — so the entire
hybrid ranking stage (and Phase 2 US-009 HyDE/CE-batch optimizations) was
dead code in production.

This test guards against a re-regression by asserting the module-level
``_hybrid_ranker`` is an actual ``HybridRanker`` instance after import.
"""
from __future__ import annotations


def test_hybrid_ranker_initialized() -> None:
    """routers.search._hybrid_ranker must be a HybridRanker instance (not None).

    If the import path is ever broken again, this test fails loudly — whereas
    the production ``try/except`` only whispers to the log.
    """
    from routers import search as search_router
    from src.graph_rag.hybrid_ranker import HybridRanker

    assert search_router._hybrid_ranker is not None, (
        "routers.search._hybrid_ranker is None — the HybridRanker import "
        "at routers/search.py likely fell back to the except branch. "
        "Check that the import path is `from src.graph_rag.hybrid_ranker ...`."
    )
    assert isinstance(search_router._hybrid_ranker, HybridRanker), (
        f"Expected HybridRanker instance, got {type(search_router._hybrid_ranker).__name__}"
    )
