"""Integration tests for /api/search that DO NOT mock _hybrid_ranker.

US-015 regression guard — the 2-month silent-import bug (HybridRanker
import fell back to None) was invisible in CI because the existing
``tests/test_search.py`` always patched ``routers.search._hybrid_ranker``
to ``None``. These tests keep the real singleton in place and mock ONLY
the external dependencies (OpenAI embeddings, cross-encoder model, source
searchers, query analyzer). That way, any future import regression on the
hybrid-ranker path will fail a test instead of silently degrading prod.

Strategy:
- Keep real ``_hybrid_ranker`` (HybridRanker instance)
- Mock OpenAI embedding batch (deterministic 1536-dim vectors)
- Mock cross-encoder scoring (avoid model download in CI)
- Mock external source APIs via SearchAgent.async_search_with_filters
- Assert the response carries ranking signatures (_hybrid_score,
  _score_breakdown) that are ONLY produced when HybridRanker actually runs
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient


# ── Test data factories ───────────────────────────────────────────────

_EMBED_DIM = 1536  # matches text-embedding-3-small


def _fake_papers(n: int = 10) -> List[Dict[str, Any]]:
    """Return canned paper dicts with enough structure for ranking signals."""
    return [
        {
            "id": f"p{i}",
            "paper_id": f"p{i}",
            "title": f"Test paper {i} on attention mechanisms in transformers",
            "abstract": (
                f"Abstract for paper {i}: we study self-attention, multi-head "
                "transformers, and their scaling properties on benchmarks."
            ),
            "authors": [f"Author {i}"],
            "year": 2023 - (i % 5),
            "citations": max(0, 100 - i * 5),
            "venue": "Conf",
            "url": f"https://example.org/p{i}",
            "source": "arxiv" if i % 2 == 0 else "openalex",
        }
        for i in range(n)
    ]


def _fake_embedding_batch(texts):
    """Deterministic mock embeddings matching 1536-dim (text-embedding-3-small).

    Uses a seeded RNG per text so the same text always hashes to the same
    vector — prevents flaky ranking order across runs.
    """
    out = []
    for t in texts:
        seed = abs(hash(t)) % (2**32)
        rng = np.random.default_rng(seed)
        out.append(rng.standard_normal(_EMBED_DIM).astype(np.float32))
    return out


# ── Fixture: REAL ranker, mocked externals ───────────────────────────


@pytest.fixture
def real_ranker_client(tmp_path, monkeypatch):
    """Async client with REAL _hybrid_ranker but all externals mocked.

    Yields (client, auth_headers) so tests can POST to /api/search.
    """
    # isolate on-disk state to tmp_path
    monkeypatch.setenv("JWT_SECRET", "real-ranker-test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("EVENTS_DB_PATH", str(tmp_path / "events.db"))
    monkeypatch.setenv("PROFILE_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("BOOKMARKS_DB_PATH", str(tmp_path / "bookmarks.db"))

    # 1) QueryAnalyzer.analyze_and_prepare → deterministic response, no LLM
    qa_mock = MagicMock()
    qa_mock.analyze_query.return_value = {
        "intent": "method_search",
        "keywords": ["attention", "transformer"],
        "improved_query": "attention mechanism transformer",
        "search_filters": {},
        "confidence": 0.7,  # <0.8 → keeps original query (simpler path)
        "original_query": "attention",
        "analysis_details": None,
    }
    qa_mock.classify_topic.return_value = {"is_academic": True, "confidence": 0.95}
    qa_mock.classify_difficulty.return_value = "easy"  # ensures HyDE skip
    qa_mock.analyze_and_prepare.return_value = {
        "intent": "method_search",
        "keywords": ["attention", "transformer"],
        "improved_query": "attention mechanism transformer",
        "search_filters": {},
        "confidence": 0.7,
        "original_query": "attention",
        "is_academic": True,
        "source_queries": {
            "arxiv": "attention transformer",
            "dblp": "attention transformer",
            "google_scholar": "attention transformer",
            "default": "attention transformer",
        },
    }

    # 2) SearchAgent.async_search_with_filters → canned papers across sources
    papers = _fake_papers(10)
    arxiv_papers = [p for p in papers if p["source"] == "arxiv"]
    openalex_papers = [p for p in papers if p["source"] == "openalex"]

    async def _async_search(query, filters):  # noqa: ANN001
        return {
            "arxiv": list(arxiv_papers),
            "openalex": list(openalex_papers),
            "google_scholar": [],
            "dblp": [],
            "connected_papers": [],
            "openalex_korean": [],
        }

    sa_mock = MagicMock()
    sa_mock.async_search_with_filters.side_effect = _async_search
    sa_mock.deduplicator = MagicMock()
    sa_mock.deduplicator.deduplicate.side_effect = lambda papers: papers
    sa_mock.save_papers.return_value = {"new_papers": 0, "duplicates": 0}

    # CRITICAL: the real _hybrid_ranker holds a reference to the REAL
    # search_agent.similarity_calculator. We must patch
    # ``get_embeddings_batch`` on that real instance so semantic scoring
    # runs without hitting OpenAI.
    from routers.search import _hybrid_ranker as real_hr

    assert real_hr is not None, (
        "PRECONDITION FAILED: _hybrid_ranker is None at test setup — "
        "the import regression this test guards against is already present."
    )

    real_sim_calc = real_hr.similarity_calculator
    sa_mock.similarity_calculator = real_sim_calc  # used by endpoint handler

    with (
        patch("routers.search.query_analyzer", qa_mock),
        patch("routers.search.search_agent", sa_mock),
        patch("routers.search.relevance_filter", None),  # fast_mode also skips
        # NOTE: we deliberately do NOT patch routers.search._hybrid_ranker
        # Suppress cache IO to keep tests hermetic
        patch("routers.search._set_cache", return_value=None),
        patch("routers.search._get_cached_result", return_value=None),
        patch("routers.search.json.dump", return_value=None),
        patch("routers.search.Path.mkdir", return_value=None),
        # Mock OpenAI embedding calls — keep ranker path, drop network IO
        patch.object(
            real_sim_calc,
            "get_embeddings_batch",
            side_effect=lambda texts, **_kw: _fake_embedding_batch(texts),
        ),
        # Mock cross-encoder — avoid downloading sentence-transformers model
        patch(
            "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
            side_effect=lambda q, ps: [0.8 - 0.05 * i for i in range(len(ps))],
        ),
    ):
        from api_server import app

        app.state.limiter.enabled = False
        try:
            yield app, papers
        finally:
            app.state.limiter.enabled = True


@pytest.fixture
async def real_ranker_async_client(real_ranker_client):
    """Register a user inside the patched app and yield an authenticated client."""
    app, papers = real_ranker_client
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        reg = await ac.post(
            "/api/auth/register",
            json={"username": "realrank_user", "password": "pw1234"},
        )
        assert reg.status_code in (200, 409), reg.text
        login = await ac.post(
            "/api/auth/login",
            json={"username": "realrank_user", "password": "pw1234"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        yield ac, headers, papers


# ── Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_response_has_hybrid_score_signature(real_ranker_async_client):
    """REGRESSION GUARD: /api/search response papers MUST carry _hybrid_score.

    If this fails, HybridRanker is not executing — same class of bug as the
    2-month silent import failure where ``_hybrid_ranker = None`` made all
    ranking silently skipped in production while tests (which mocked it to
    None) still passed.
    """
    ac, headers, _papers = real_ranker_async_client
    resp = await ac.post(
        "/api/search",
        headers=headers,
        json={
            "query": "attention",
            "fast_mode": True,
            "save_papers": False,
            "sources": ["arxiv", "openalex"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    all_papers = [p for papers in body["results"].values() for p in papers]
    assert all_papers, "No papers returned — search pipeline broken upstream"

    first = all_papers[0]
    ranking_fields = {"_hybrid_score", "_cross_encoder_score", "_score_breakdown"}
    present = ranking_fields & set(first.keys())
    assert present, (
        "No ranking signature in response — _hybrid_ranker likely disabled. "
        f"Available fields: {sorted(first.keys())}"
    )


def test_hybrid_ranker_module_level_is_not_none():
    """Direct source-of-truth check: the module-level singleton must be real.

    Complements ``test_hybrid_ranker_import.py`` with the class-level
    isinstance check (so ``_hybrid_ranker = MagicMock()`` would also fail).
    """
    from routers.search import _hybrid_ranker
    from src.graph_rag.hybrid_ranker import HybridRanker

    assert _hybrid_ranker is not None, (
        "_hybrid_ranker is None — import regression: check that "
        "routers/search.py uses `from src.graph_rag.hybrid_ranker import HybridRanker`"
    )
    assert isinstance(_hybrid_ranker, HybridRanker), (
        f"Wrong type: got {type(_hybrid_ranker).__name__}, expected HybridRanker"
    )


@pytest.mark.asyncio
async def test_ranking_signature_proves_path_executed(real_ranker_async_client):
    """Confirm _score_breakdown carries the expected RRF signal keys.

    When HybridRanker.rank_papers_rrf runs, each paper gets a breakdown
    containing bm25/citations/recency (always) plus cross_encoder (when
    available) and optionally semantic (non-zero). Seeing >=2 distinct
    signal keys is strong evidence the RRF path actually executed —
    defeating a future regression where the ranker gets stubbed out or
    swapped for a no-op.
    """
    ac, headers, _papers = real_ranker_async_client
    resp = await ac.post(
        "/api/search",
        headers=headers,
        json={
            "query": "transformer attention",
            "fast_mode": True,
            "save_papers": False,
            "sources": ["arxiv", "openalex"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    all_papers = [p for papers in body["results"].values() for p in papers]
    assert all_papers, "No papers returned"

    first = all_papers[0]
    sb = first.get("_score_breakdown")
    assert isinstance(sb, dict) and sb, (
        "Expected non-empty _score_breakdown dict — HybridRanker did not "
        f"populate it. First paper keys: {sorted(first.keys())}"
    )

    # When HybridRanker runs in RRF mode, these keys are always populated
    expected_signal_keys = {"bm25", "citations", "recency", "cross_encoder"}
    present_keys = expected_signal_keys & set(sb.keys())
    assert len(present_keys) >= 2, (
        f"Too few ranking signals in breakdown — ranker did not run properly. "
        f"Got {sorted(sb.keys())}, expected >=2 of {sorted(expected_signal_keys)}"
    )

    # RRF mode flag: extra confirmation the RRF path ran (not weighted-sum)
    assert sb.get("rrf_mode") is True, (
        "rrf_mode flag missing — rank_papers_rrf did not run. "
        f"Breakdown: {sb}"
    )
