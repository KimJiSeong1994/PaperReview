"""Search latency tuning: shared S2 session, partial-result caching, HyDE warm-up, Scholar page size."""
from unittest.mock import MagicMock, patch

import pytest

from src.collector.paper.connected_papers_searcher import ConnectedPapersSearcher
from src.collector.paper.semantic_scholar_client import SemanticScholarClient


def test_connected_papers_uses_keyed_session_and_shared_throttle(monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "k")
    searcher = ConnectedPapersSearcher()
    assert searcher.session.headers["x-api-key"] == "k"
    searcher.session = MagicMock()
    searcher.session.get.return_value.json.return_value = {"data": []}
    with patch.object(SemanticScholarClient, "_rate_limiter") as limiter:
        assert searcher.search("q") == []
    limiter.wait.assert_called_once()


def test_scholar_requests_twenty_results_per_page(monkeypatch):
    from types import SimpleNamespace
    from src.collector.paper.google_scholar_searcher import GoogleScholarSearcher

    searcher = GoogleScholarSearcher()
    seen = {}

    def backoff(url, params, **kwargs):
        seen.update(params)
        return SimpleNamespace(text="")

    monkeypatch.setattr(searcher, "_is_available", lambda: True)
    monkeypatch.setattr(searcher, "_request_with_backoff", backoff)
    monkeypatch.setattr(searcher, "_is_captcha_response", lambda response: False)
    monkeypatch.setattr(searcher, "_parse_search_results", lambda text, limit: [])
    searcher.search("q", 50)
    assert seen["num"] == 20


def _analyzer():
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {
        "is_academic": True, "intent": "paper_search", "keywords": ["t"],
        "improved_query": "t", "search_filters": {}, "confidence": 0.9,
        "original_query": "t", "source_queries": {},
    }
    return analyzer


def _agent(source_modes):
    agent = MagicMock()

    async def _search(query, filters):  # noqa: ANN001
        filters["_metadata"]["modes"].update(source_modes)
        return {"arxiv": [{"title": "P", "source": "arxiv", "abstract": "a"}], "connected_papers": []}

    agent.async_search_with_filters.side_effect = _search
    agent.deduplicator = MagicMock()
    agent.deduplicator.deduplicate.side_effect = lambda papers: papers
    agent.save_papers.return_value = {"new_papers": 0, "duplicates": 0}
    agent.similarity_calculator = MagicMock()
    return agent


@pytest.mark.asyncio
async def test_source_error_still_caches_with_short_ttl(client):
    from routers import search as rs

    with (
        patch.object(rs, "query_analyzer", _analyzer()),
        patch.object(rs, "search_agent", _agent({"arxiv": "searched", "connected_papers": "error"})),
        patch.object(rs, "_hybrid_ranker", None),
        patch.object(rs, "_get_cached_result", return_value=None),
        patch.object(rs, "_set_cache", return_value=None) as set_cache,
    ):
        resp = await client.post("/api/search", json={"query": "t", "sources": ["arxiv", "connected_papers"], "fast_mode": True, "save_papers": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["metadata"]["partial"] is True
    assert set_cache.call_args.kwargs["ttl_seconds"] == rs._PARTIAL_CACHE_TTL_SECONDS
    assert set_cache.call_args.args[1]["_metadata"]["partial"] is True


@pytest.mark.asyncio
async def test_partial_cache_hit_reports_partial(client):
    from routers import search as rs

    cached = {"arxiv": [{"title": "P", "source": "arxiv", "abstract": "a"}], "_metadata": {"partial": True}}
    with (
        patch.object(rs, "query_analyzer", _analyzer()),
        patch.object(rs, "search_agent", _agent({})),
        patch.object(rs, "_hybrid_ranker", None),
        patch.object(rs, "_get_cached_result", return_value=cached),
        patch.object(rs, "_set_cache", return_value=None) as set_cache,
    ):
        resp = await client.post("/api/search", json={"query": "t", "sources": ["arxiv"], "fast_mode": True, "save_papers": False})
    body = resp.json()
    assert body["cache_hit"] is True and body["metadata"]["partial"] is True
    assert "source_incomplete" in body["degraded"]
    set_cache.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fast_mode,submitted", [(False, True), (True, False)])
async def test_hyde_warm_up_only_on_standard_topic_miss(client, fast_mode, submitted):
    from routers import search as rs

    ranker = MagicMock()
    ranker.rank_papers.side_effect = lambda **kw: kw["papers"]
    with (
        patch.object(rs, "query_analyzer", _analyzer()),
        patch.object(rs, "search_agent", _agent({"arxiv": "searched"})),
        patch.object(rs, "_hybrid_ranker", ranker),
        patch.object(rs, "_HYDE_EXECUTOR") as executor,
        patch.object(rs, "_get_cached_result", return_value=None),
        patch.object(rs, "_set_cache", return_value=None),
        patch.object(rs, "rerank_papers") as rerank,
    ):
        rerank.side_effect = lambda q, p, **kw: (p, {"mode": "skipped_insufficient_evidence", "scored_count": 0})
        resp = await client.post("/api/search", json={"query": "graph retrieval", "sources": ["arxiv"], "fast_mode": fast_mode, "save_papers": False})
    assert resp.status_code == 200, resp.text
    assert executor.submit.called is submitted
    if submitted:
        assert executor.submit.call_args.args[:2] == (ranker._generate_hyde_embedding, "graph retrieval")
