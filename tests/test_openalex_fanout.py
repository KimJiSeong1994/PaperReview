"""OpenAlex request fan-out per search.

The daily credit budget (1000 credits, 10 per request) is the binding
constraint on search: every extra request per search divides the number of
searches the free tier supports. These tests pin the request count so a
regression shows up here rather than as a quota exhaustion in production.
"""
from unittest.mock import MagicMock

from app.SearchAgent.search_agent import SearchAgent


def _agent(basic_hits: int):
    """SearchAgent whose OpenAlex searcher records calls and returns N papers."""
    agent = SearchAgent.__new__(SearchAgent)
    searcher = MagicMock()
    papers = [{"title": f"paper {i}", "abstract": ""} for i in range(basic_hits)]
    searcher.enhanced_search.return_value = list(papers)
    searcher.search_by_title.return_value = []
    searcher.search_korean.return_value = []
    agent.openalex_searcher = searcher
    return agent, searcher


def _run(agent, source, query, filters=None, source_queries=None):
    return agent._search_single_source(
        source, query, filters or {}, source_queries or {}, 10
    )


def test_optimized_query_that_fills_results_skips_the_title_fallback():
    """A full result set must not trigger a third OpenAlex request."""
    agent, searcher = _agent(basic_hits=10)

    _run(agent, "openalex", "graph neural networks",
         source_queries={"openalex": "graph representation learning"})

    searcher.enhanced_search.assert_called_once()
    searcher.search_by_title.assert_not_called()


def test_short_result_set_still_falls_back_to_the_original_query():
    """The fallback is a recall guard; it must survive when results are thin."""
    agent, searcher = _agent(basic_hits=2)

    _run(agent, "openalex", "graph neural networks",
         source_queries={"openalex": "graph representation learning"})

    searcher.search_by_title.assert_called_once()


def test_english_query_makes_no_korean_request():
    """search_korean costs up to two requests and cannot help an English query.

    The async orchestrator gated this, but the sync path used by prefetch did
    not, so every prefetched English query paid for a Korean search.
    """
    agent, searcher = _agent(basic_hits=10)

    assert _run(agent, "openalex_korean", "graph neural networks") == []
    searcher.search_korean.assert_not_called()


def test_korean_query_still_reaches_the_korean_search():
    agent, searcher = _agent(basic_hits=10)

    _run(agent, "openalex_korean", "그래프 신경망")

    searcher.search_korean.assert_called_once()


def test_korean_detected_via_original_query_or_source_query():
    """The gate must see Korean wherever it appears, not only in `query`."""
    for filters, source_queries in (
        ({"original_query": "그래프 신경망"}, {}),
        ({}, {"openalex_korean": "그래프 신경망"}),
    ):
        agent, searcher = _agent(basic_hits=10)
        _run(agent, "openalex_korean", "graph neural networks",
             filters=filters, source_queries=source_queries)
        searcher.search_korean.assert_called_once()
