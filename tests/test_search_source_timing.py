from unittest.mock import MagicMock

import pytest

from app.SearchAgent.search_agent import SearchAgent


@pytest.mark.asyncio
async def test_async_search_records_source_timing_metadata(monkeypatch):
    agent = SearchAgent.__new__(SearchAgent)

    def fake_search(source_name, query, filters, source_queries, max_results):  # noqa: ANN001
        return [{"title": f"{source_name} result", "source": source_name}]

    monkeypatch.setattr(agent, "_search_single_source", fake_search)

    metadata = {"timings": {}, "timeouts": {}, "modes": {}}
    results = await agent.async_search_with_filters(
        "transformer",
        {"sources": ["arxiv"], "max_results": 1, "_metadata": metadata},
    )

    assert results["arxiv"][0]["title"] == "arxiv result"
    assert set(metadata["timings"]) == {"arxiv"}
    assert metadata["timings"]["arxiv"] >= 0
    assert metadata["timeouts"] == {"arxiv": False}
    assert metadata["modes"] == {"arxiv": "searched"}


@pytest.mark.asyncio
async def test_async_search_reports_empty_result_as_its_own_mode(monkeypatch):
    """A source that ran but matched nothing must not claim a plain "searched"."""
    agent = SearchAgent.__new__(SearchAgent)
    monkeypatch.setattr(
        agent, "_search_single_source", lambda *a, **k: []
    )

    metadata = {"timings": {}, "timeouts": {}, "modes": {}}
    results = await agent.async_search_with_filters(
        "transformer",
        {"sources": ["arxiv"], "max_results": 1, "_metadata": metadata},
    )

    assert results == {"arxiv": []}
    assert metadata["modes"] == {"arxiv": "searched_empty"}


@pytest.mark.asyncio
async def test_async_search_reports_open_circuit_breaker(monkeypatch):
    """An empty result from a short-circuited source is reported as circuit_open."""
    agent = SearchAgent.__new__(SearchAgent)
    agent.google_scholar_searcher = MagicMock()
    agent.google_scholar_searcher.is_circuit_open.return_value = True
    monkeypatch.setattr(agent, "_search_single_source", lambda *a, **k: [])

    metadata = {"timings": {}, "timeouts": {}, "modes": {}}
    await agent.async_search_with_filters(
        "transformer",
        {"sources": ["google_scholar"], "max_results": 1, "_metadata": metadata},
    )

    assert metadata["modes"] == {"google_scholar": "circuit_open"}

    # A breaker that is closed again falls back to the plain empty mode.
    agent.google_scholar_searcher.is_circuit_open.return_value = False
    metadata = {"timings": {}, "timeouts": {}, "modes": {}}
    await agent.async_search_with_filters(
        "transformer",
        {"sources": ["google_scholar"], "max_results": 1, "_metadata": metadata},
    )

    assert metadata["modes"] == {"google_scholar": "searched_empty"}


@pytest.mark.asyncio
async def test_async_search_skips_openalex_korean_for_non_korean_query(monkeypatch):
    agent = SearchAgent.__new__(SearchAgent)

    def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("openalex_korean should be skipped for non-Korean queries")

    monkeypatch.setattr(agent, "_search_single_source", fail_if_called)

    metadata = {"timings": {}, "timeouts": {}, "modes": {}}
    results = await agent.async_search_with_filters(
        "large language models",
        {"sources": ["openalex_korean"], "max_results": 1, "_metadata": metadata},
    )

    assert results == {"openalex_korean": []}
    assert metadata["timings"] == {"openalex_korean": 0.0}
    assert metadata["timeouts"] == {"openalex_korean": False}
    assert metadata["modes"] == {"openalex_korean": "skipped_non_korean_query"}


@pytest.mark.asyncio
async def test_async_search_keeps_openalex_korean_when_original_query_is_korean(monkeypatch):
    agent = SearchAgent.__new__(SearchAgent)
    calls = []

    def fake_search(source_name, query, filters, source_queries, max_results):  # noqa: ANN001
        calls.append((source_name, query, filters, source_queries, max_results))
        return [{"title": "Korean source result", "source": source_name}]

    monkeypatch.setattr(agent, "_search_single_source", fake_search)

    metadata = {"timings": {}, "timeouts": {}, "modes": {}}
    results = await agent.async_search_with_filters(
        "large language models",
        {
            "sources": ["openalex_korean"],
            "max_results": 1,
            "original_query": "거대 언어 모델",
            "_metadata": metadata,
        },
    )

    assert results["openalex_korean"][0]["title"] == "Korean source result"
    assert calls and calls[0][0] == "openalex_korean"
    assert metadata["modes"] == {"openalex_korean": "searched"}


def test_openalex_korean_search_prefers_original_korean_query():
    agent = SearchAgent.__new__(SearchAgent)
    agent.openalex_searcher = MagicMock()
    agent.openalex_searcher.search_korean.return_value = [{"title": "Korean Paper"}]

    result = agent._search_single_source(
        "openalex_korean",
        "large language models",
        {"original_query": "거대 언어 모델"},
        {"openalex_korean": "large language models"},
        5,
    )

    assert result == [{"title": "Korean Paper"}]
    agent.openalex_searcher.search_korean.assert_called_once_with("거대 언어 모델", 5)
