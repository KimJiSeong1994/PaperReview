"""Integration tests for search-related endpoints.

Covers:
  POST /api/analyze-query
  POST /api/search
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared mock return values
# ---------------------------------------------------------------------------

_ANALYZE_QUERY_RESULT = {
    "intent": "paper_search",
    "keywords": ["machine learning"],
    "improved_query": "machine learning survey",
    "search_filters": {},
    "confidence": 0.9,
    "original_query": "machine learning",
    "analysis_details": None,
}

_CLASSIFY_TOPIC_RESULT = {"is_academic": True, "confidence": 0.95}

_SEARCH_AGENT_RESULTS = {
    "arxiv": [
        {
            "title": "A Survey on Machine Learning",
            "authors": ["Author A"],
            "abstract": "This paper surveys...",
            "year": "2024",
            "url": "https://arxiv.org/abs/2401.00001",
            "source": "arxiv",
        }
    ]
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_query_analyzer_mock() -> MagicMock:
    """Return a QueryAnalyzer mock with default happy-path behaviour."""
    mock = MagicMock()
    mock.analyze_query.return_value = _ANALYZE_QUERY_RESULT.copy()
    mock.classify_topic.return_value = _CLASSIFY_TOPIC_RESULT.copy()
    mock.classify_difficulty.return_value = "medium"
    mock.generate_source_specific_queries.return_value = {}
    # Unified 3-in-1 method (Sprint 5a)
    mock.analyze_and_prepare.return_value = {
        **_ANALYZE_QUERY_RESULT.copy(),
        "is_academic": True,
        "source_queries": {"arxiv": "machine learning", "dblp": "machine learning", "google_scholar": "machine learning", "default": "machine learning"},
    }
    return mock


def _make_search_agent_mock() -> MagicMock:
    """Return a SearchAgent mock whose async_search_with_filters returns a coroutine."""
    mock = MagicMock()

    # async_search_with_filters is awaited directly by the endpoint handler
    async def _async_search(query, filters):  # noqa: ANN001
        return {k: list(v) for k, v in _SEARCH_AGENT_RESULTS.items()}

    mock.async_search_with_filters.side_effect = _async_search

    # Synchronous helpers used inside deduplication and background threads
    mock.deduplicator = MagicMock()
    mock.deduplicator.deduplicate.side_effect = lambda papers: papers  # identity
    mock.save_papers.return_value = {"new_papers": 1, "duplicates": 0}
    mock.similarity_calculator = MagicMock()

    return mock


@pytest.fixture(autouse=True)
def _patch_search_singletons():
    """Patch all module-level singletons in routers.search for every test.

    Also suppresses cache I/O so tests neither read stale cached results nor
    write files to disk (data/cache/).
    """
    qa_mock = _make_query_analyzer_mock()
    sa_mock = _make_search_agent_mock()
    rf_mock = None   # graceful degradation: no relevance filter
    hr_mock = None   # graceful degradation: no hybrid ranker

    with (
        patch("routers.search.query_analyzer", qa_mock),
        patch("routers.search.search_agent", sa_mock),
        patch("routers.search.relevance_filter", rf_mock),
        patch("routers.search._hybrid_ranker", hr_mock),
        # Prevent reading from / writing to the on-disk search cache
        patch("routers.search._set_cache", return_value=None),
        patch("routers.search._get_cached_result", return_value=None),
        # Prevent the deep-research cache file write at the end of search_papers
        patch("routers.search.json.dump", return_value=None),
        # Prevent Path.mkdir / open calls for data/cache directory creation
        patch("routers.search.Path.mkdir", return_value=None),
    ):
        yield {
            "query_analyzer": qa_mock,
            "search_agent": sa_mock,
        }


# ---------------------------------------------------------------------------
# POST /api/analyze-query
# ---------------------------------------------------------------------------

class TestAnalyzeQuery:
    """POST /api/analyze-query"""

    @pytest.mark.asyncio
    async def test_analyze_query_success(self, client, _patch_search_singletons):
        """Returns full analysis dict when query_analyzer is available."""
        qa_mock = _patch_search_singletons["query_analyzer"]

        resp = await client.post(
            "/api/analyze-query",
            json={"query": "machine learning"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["intent"] == "paper_search"
        assert body["keywords"] == ["machine learning"]
        assert body["improved_query"] == "machine learning survey"
        assert body["confidence"] == 0.9
        assert body["original_query"] == "machine learning"
        qa_mock.analyze_query.assert_called_once_with("machine learning")

    @pytest.mark.asyncio
    async def test_analyze_query_returns_503_when_no_analyzer(self, client):
        """Returns 503 when query_analyzer singleton is None."""
        with patch("routers.search.query_analyzer", None):
            resp = await client.post(
                "/api/analyze-query",
                json={"query": "machine learning"},
            )

        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/search
# ---------------------------------------------------------------------------

class TestSearch:
    """POST /api/search"""

    @pytest.mark.asyncio
    async def test_search_success(self, client, _patch_search_singletons):
        """Returns results and total count for a valid academic query."""
        resp = await client.post(
            "/api/search",
            json={"query": "machine learning", "fast_mode": True, "save_papers": False},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body
        assert isinstance(body["results"], dict)
        assert body["total"] >= 1

        # The arxiv paper injected by the mock must appear somewhere in results
        all_papers = [p for papers in body["results"].values() for p in papers]
        titles = [p["title"] for p in all_papers]
        assert "A Survey on Machine Learning" in titles

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_empty_results(
        self, client, _patch_search_singletons
    ):
        """Non-academic topic classification causes the endpoint to return empty results."""
        qa_mock = _patch_search_singletons["query_analyzer"]
        # Override unified analysis to report non-academic so the endpoint
        # short-circuits and returns empty results.
        qa_mock.analyze_and_prepare.return_value = {
            "is_academic": False,
            "intent": "unknown",
            "keywords": [],
            "improved_query": "",
            "search_filters": {},
            "confidence": 0.0,
            "original_query": "",
            "source_queries": {"arxiv": "", "dblp": "", "google_scholar": "", "default": ""},
        }

        resp = await client.post(
            "/api/search",
            json={"query": "", "fast_mode": True, "save_papers": False},
        )

        assert resp.status_code == 200
        body = resp.json()
        all_papers = [p for papers in body["results"].values() for p in papers]
        assert all_papers == [], "Expected no results for non-academic query"
        assert body["total"] == 0
