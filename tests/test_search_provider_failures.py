"""Transport failures must not masquerade as zero scholarly matches."""
from unittest.mock import MagicMock

import pytest
import requests

from src.collector.paper.connected_papers_searcher import ConnectedPapersSearcher


@pytest.mark.parametrize("failure", [requests.Timeout("expired"), requests.HTTPError("429"), ValueError("invalid JSON")])
def test_semantic_scholar_propagates_search_failure(failure):
    searcher = ConnectedPapersSearcher()
    searcher.session = MagicMock()
    searcher.session.get.side_effect = failure
    with pytest.raises(type(failure)):
        searcher.search("graph retrieval")


def test_semantic_scholar_retains_external_identity_and_real_empty():
    searcher = ConnectedPapersSearcher()
    searcher.session = MagicMock()
    response = searcher.session.get.return_value
    response.json.return_value = {"data": [{"paperId": "s2-id", "title": "Paper", "externalIds": {"DOI": "10.1234/paper", "ArXiv": "1706.03762"}}]}
    paper = searcher.search("paper")[0]
    assert paper["doi"] == "10.1234/paper"
    assert paper["arxiv_id"] == "1706.03762"
    assert paper["semantic_scholar_id"] == "s2-id"
    assert "externalIds" in searcher.session.get.call_args.kwargs["params"]["fields"]
    response.json.return_value = {"data": []}
    assert searcher.search("no matches") == []


@pytest.mark.asyncio
async def test_transport_error_is_reported_as_error_not_searched_empty():
    from app.SearchAgent.search_agent import SearchAgent

    agent = SearchAgent.__new__(SearchAgent)
    agent.connected_papers_searcher = ConnectedPapersSearcher()
    agent.connected_papers_searcher.session = MagicMock()
    agent.connected_papers_searcher.session.get.side_effect = requests.HTTPError("429")
    metadata = {}
    result = await agent.async_search_with_filters("topic", {"sources": ["connected_papers"], "_metadata": metadata})
    assert result == {"connected_papers": []}
    assert metadata["modes"]["connected_papers"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,mode", [
    (requests.HTTPError("503"), "error"),
    (requests.HTTPError("429"), "timeout"),
    (requests.Timeout("expired"), "timeout"),
])
async def test_real_arxiv_failures_reach_collector(monkeypatch, failure, mode):
    import time
    from app.SearchAgent.search_agent import SearchAgent
    from src.collector.paper.arxiv_searcher import ArxivSearcher
    agent = SearchAgent.__new__(SearchAgent)
    agent.arxiv_searcher = ArxivSearcher()
    monkeypatch.setattr(agent.arxiv_searcher, "_rate_limit", lambda *args: None)
    agent.arxiv_searcher.client.results = MagicMock(side_effect=failure)
    metadata = {}
    result = await agent.async_search_with_filters("ti:graph", {
        "sources": ["arxiv"], "_metadata": metadata, "_deadline": time.monotonic() + 1,
    })
    assert result["arxiv"] == []
    assert metadata["modes"]["arxiv"] == mode
    assert metadata["provider_attempts"]["arxiv"][0]["status"] in ("error", "timeout")


@pytest.mark.asyncio
async def test_real_scholar_mixed_buckets_keep_success_and_expose_error(monkeypatch):
    from app.SearchAgent.search_agent import SearchAgent
    from src.collector.paper.google_scholar_searcher import GoogleScholarSearcher
    agent = SearchAgent.__new__(SearchAgent)
    agent.search_history = []
    searcher = agent.google_scholar_searcher = GoogleScholarSearcher()
    monkeypatch.setattr(searcher, "_ensure_proxy", lambda **kwargs: None)
    monkeypatch.setattr(searcher, "_rate_limit", lambda: None)
    response = MagicMock(status_code=200, url="https://scholar.google.com", text="paper")
    def request(url, params, **kwargs):
        if params["q"] == "broken":
            raise requests.HTTPError("503")
        return response
    monkeypatch.setattr(searcher.session, "get", request)
    monkeypatch.setattr(searcher, "_parse_search_results", lambda *args: [{"title": "healthy", "doi": "10.1234/healthy"}])
    metadata = {}
    result = await agent.async_search_with_filters("topic", {
        "sources": ["google_scholar"], "source_queries": {"scholar_queries": ["broken", "healthy"]},
        "_metadata": metadata,
    })
    assert [p["title"] for p in result["google_scholar"]] == ["healthy"]
    assert metadata["modes"]["google_scholar"] == "partial_error"
    assert {a["status"] for a in metadata["provider_attempts"]["google_scholar"]} == {"error", "searched"}


@pytest.mark.asyncio
async def test_korean_openalex_stops_before_second_attempt_and_keeps_first(monkeypatch):
    import threading
    from app.SearchAgent.search_agent import SearchAgent
    from src.collector.paper.openalex_searcher import OpenAlexSearcher
    agent = SearchAgent.__new__(SearchAgent)
    searcher = agent.openalex_searcher = OpenAlexSearcher()
    monkeypatch.setattr(searcher, "_rate_limit", lambda: None)
    stop = threading.Event()
    response = MagicMock()
    def payload():
        stop.set()
        return {"results": [{"id": "first"}]}
    response.json.side_effect = payload
    searcher.session = MagicMock()
    searcher.session.get.return_value = response
    monkeypatch.setattr(searcher, "_parse_paper", lambda work: {"title": "한글 논문"})
    metadata = {}
    result = await agent.async_search_with_filters("한글", {
        "sources": ["openalex_korean"], "_stop_event": stop, "_metadata": metadata,
    })
    assert len(result["openalex_korean"]) == 1
    assert metadata["modes"]["openalex_korean"] == "partial_timeout"
    assert metadata["timeouts"]["openalex_korean"] is True
    searcher.session.get.assert_called_once()


def test_scholar_captcha_does_not_spawn_manual_or_scholarly_work(monkeypatch):
    from src.collector.paper.google_scholar_searcher import GoogleScholarSearcher
    searcher = GoogleScholarSearcher()
    monkeypatch.setattr(searcher, "_request_with_backoff", lambda *args, **kwargs: MagicMock(status_code=429))
    manual = MagicMock()
    fallback = MagicMock()
    monkeypatch.setattr(searcher, "_solve_captcha_manually", manual)
    monkeypatch.setattr(searcher, "_search_via_scholarly", fallback)
    attempts = []
    assert searcher.search("topic", attempts=attempts) == []
    assert attempts[0]["status"] == "error"
    manual.assert_not_called()
    fallback.assert_not_called()


def test_proxy_discovery_is_synchronous_and_stopped_before_transport(monkeypatch):
    import threading
    from src.collector.paper import google_scholar_searcher as module
    transport = MagicMock()
    monkeypatch.setattr(module.requests, "get", transport)
    stop = threading.Event()
    stop.set()
    before = {thread.ident for thread in threading.enumerate()}
    assert module._get_free_proxy(stop_event=stop) is None
    assert {thread.ident for thread in threading.enumerate()} == before
    transport.assert_not_called()


def test_scholar_retry_does_not_start_after_stop(monkeypatch):
    import threading
    from src.collector.paper.google_scholar_searcher import GoogleScholarSearcher
    searcher = GoogleScholarSearcher()
    searcher.max_retries = 2
    stop = threading.Event()
    monkeypatch.setattr(searcher, "_ensure_proxy", lambda **kwargs: None)
    monkeypatch.setattr(searcher, "_rate_limit", lambda: None)
    def fail(*args, **kwargs):
        stop.set()
        raise requests.Timeout("first request")
    searcher.session = MagicMock()
    searcher.session.get.side_effect = fail
    attempts = []
    assert searcher.search("topic", stop_event=stop, attempts=attempts) == []
    assert attempts[-1]["status"] == "timeout"
    searcher.session.get.assert_called_once()


def test_scholar_enhanced_does_not_start_second_strategy_after_stop(monkeypatch):
    import threading
    from src.collector.paper.google_scholar_searcher import GoogleScholarSearcher
    searcher = GoogleScholarSearcher()
    stop = threading.Event()
    def first(*args, **kwargs):
        stop.set()
        return [{"title": "finished"}]
    search = MagicMock(side_effect=first)
    monkeypatch.setattr(searcher, "search", search)
    attempts = []
    assert searcher.enhanced_search("topic", stop_event=stop, attempts=attempts) == [{"title": "finished"}]
    search.assert_called_once()
    assert attempts[-1]["status"] == "timeout"


@pytest.mark.asyncio
async def test_openalex_true_empty_is_healthy_but_http_error_is_not(monkeypatch):
    from app.SearchAgent.search_agent import SearchAgent
    from src.collector.paper.openalex_searcher import OpenAlexSearcher
    agent = SearchAgent.__new__(SearchAgent)
    searcher = agent.openalex_searcher = OpenAlexSearcher()
    monkeypatch.setattr(searcher, "_rate_limit", lambda: None)
    searcher.session = MagicMock()
    searcher.session.get.return_value.json.return_value = {"results": []}
    for failure, expected in [(None, "searched_empty"), (requests.HTTPError("503"), "error")]:
        searcher.session.get.side_effect = failure
        metadata = {}
        result = await agent.async_search_with_filters("topic", {"sources": ["openalex"], "_metadata": metadata})
        assert result["openalex"] == []
        assert metadata["modes"]["openalex"] == expected


@pytest.mark.parametrize("source", ["arxiv", "google_scholar"])
@pytest.mark.asyncio
async def test_successful_empty_adapters_remain_searched_empty(monkeypatch, source):
    from app.SearchAgent.search_agent import SearchAgent
    from src.collector.paper.arxiv_searcher import ArxivSearcher
    from src.collector.paper.google_scholar_searcher import GoogleScholarSearcher
    agent = SearchAgent.__new__(SearchAgent)
    agent.search_history = []
    if source == "arxiv":
        searcher = agent.arxiv_searcher = ArxivSearcher()
        monkeypatch.setattr(searcher, "_rate_limit", lambda *args: None)
        searcher.client.results = MagicMock(return_value=iter([]))
    else:
        searcher = agent.google_scholar_searcher = GoogleScholarSearcher()
        monkeypatch.setattr(searcher, "_ensure_proxy", lambda **kwargs: None)
        monkeypatch.setattr(searcher, "_rate_limit", lambda: None)
        searcher.session = MagicMock()
        searcher.session.get.return_value = MagicMock(
            status_code=200, url="https://scholar.google.com", text="<html></html>",
        )
    metadata = {}
    result = await agent.async_search_with_filters("ti:graph", {"sources": [source], "_metadata": metadata})
    assert result[source] == []
    assert metadata["modes"][source] == "searched_empty"
