"""Publication contracts use real identity/filter logic and fake transports."""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from routers import search as rs
from src.collector.paper.deduplicator import PaperDeduplicator


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(rs, "_router_shutdown", __import__("threading").Event())
    monkeypatch.setattr(rs, "_router_operation_owner", rs.SearchAgent.__new__(rs.SearchAgent))
    agent = SimpleNamespace(deduplicator=PaperDeduplicator())
    monkeypatch.setattr(rs, "search_agent", agent)
    monkeypatch.setattr(rs, "query_analyzer", None)
    monkeypatch.setattr(rs, "_get_cached_result", lambda *a, **k: None)
    monkeypatch.setattr(rs, "_set_cache", MagicMock())
    monkeypatch.setattr(rs, "_persist_last_search", MagicMock())
    monkeypatch.setattr(rs, "_hybrid_ranker", None)
    monkeypatch.setattr(rs, "_RANKER_DEGRADATION_REASONS", [])
    return agent


@pytest.mark.parametrize("change", [
    {"sources": []}, {"sources": ["unknown"]}, {"max_results": 0},
    {"max_results": 101}, {"sort_by": "bogus"},
    {"year_start": 2025, "year_end": 2020}, {"year_start": -1},
])
def test_invalid_requests(change):
    with pytest.raises(ValidationError):
        rs.SearchRequest(query="research", **change)


def test_sources_are_canonical():
    assert rs.SearchRequest(query="x", sources=["openalex", "arxiv", "arxiv"]).sources == ["arxiv", "openalex"]


def test_relevance_survives_dedup_and_provider_display_source(runtime):
    original = {"arxiv": [
        {"title": "Best", "doi": "10.1234/z", "source": "arXiv", "_rank": 0},
        {"title": "Second", "doi": "10.1234/a", "source": "arXiv", "_rank": 1},
    ]}
    for _ in range(3):
        finalized, _ = rs._finalize_results(original, {"sort_by": "relevance"}, ["arxiv"])
        assert [p["doi"] for p in finalized["arxiv"]] == ["10.1234/z", "10.1234/a"]
        rebuilt = rs._rebuild_results_from_ranked(finalized["arxiv"], ["arxiv"])
        assert len(rebuilt["arxiv"]) == 2
        original = rebuilt


@pytest.mark.asyncio
async def test_http_disconnect_stops_before_save_without_task_cancel(runtime, monkeypatch):
    from starlette.requests import Request
    messages = asyncio.Queue()
    async def receive():
        return await messages.get()
    http = Request({"type": "http", "method": "POST", "path": "/api/search", "headers": []}, receive)
    async def search(query, filters):
        await messages.put({"type": "http.disconnect"})
        while not filters["_stop_event"].is_set():
            await asyncio.sleep(0)
        return {"arxiv": [{"title": "Completed", "doi": "10.1234/disconnect"}]}
    runtime.async_search_with_filters = search
    save = MagicMock()
    runtime.save_papers = save
    response = await rs.search_papers(rs.SearchRequest(query="topic", sources=["arxiv"], fast_mode=True), None, http)
    assert response.metadata["save_status"] == "not_admitted_disconnect"
    save.assert_not_called()


@pytest.mark.asyncio
async def test_observer_terminates_when_receive_swallows_cancellation(runtime):
    entered = asyncio.Event()
    class SwallowingRequest:
        async def is_disconnected(self):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return False
    async def search(query, filters):
        await entered.wait()
        return {"arxiv": []}
    runtime.async_search_with_filters = search
    before = asyncio.all_tasks()
    response = await asyncio.wait_for(rs.search_papers(
        rs.SearchRequest(query="topic", sources=["arxiv"], fast_mode=True, save_papers=False),
        None, SwallowingRequest(),
    ), timeout=1)
    assert response.total == 0
    assert not [task for task in asyncio.all_tasks() - before if "observe_disconnect" in task.get_coro().__qualname__]


@pytest.mark.asyncio
async def test_accepted_save_observer_ends_on_completion(runtime):
    import threading
    from starlette.requests import Request
    release = threading.Event()
    async def receive():
        await asyncio.Event().wait()
    http = Request({"type": "http", "method": "POST", "path": "/api/search", "headers": []}, receive)
    async def search(query, filters):
        return {"arxiv": [{"title": "Persist", "doi": "10.1234/persist"}]}
    def save(*args, **kwargs):
        release.wait(2)
        return {"success": True, "new_papers": 0}
    runtime.async_search_with_filters = search
    runtime.save_papers = save
    before = asyncio.all_tasks()
    try:
        response = await rs.search_papers(
            rs.SearchRequest(query="topic", sources=["arxiv"], fast_mode=True), None, http,
        )
        assert response.metadata["save_status"] == "accepted"
        observers = [task for task in asyncio.all_tasks() - before if "observe_disconnect" in task.get_coro().__qualname__]
        assert len(observers) == 1
    finally:
        release.set()
    await asyncio.wait_for(asyncio.gather(*observers), timeout=1)
    assert all(task.done() for task in observers)


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis_status", [None, "unavailable_original_query", "low_confidence_original_query"])
async def test_returned_analysis_fallback_never_establishes_guard_or_cache(runtime, monkeypatch, analysis_status):
    analysis = {"is_academic": True, "confidence": 0.95, "improved_query": "proposed rewrite"}
    if analysis_status:
        analysis["analysis_status"] = analysis_status
    analyzer = SimpleNamespace(analyze_and_prepare=MagicMock(return_value=analysis))
    monkeypatch.setattr(rs, "query_analyzer", analyzer)
    monkeypatch.setattr(rs, "_graphrag_expand", lambda *args, **kwargs: [])
    observed = []

    async def search(query, filters):
        observed.append(query)
        filters["_metadata"].update(modes={"arxiv": "searched"}, executed_queries={"arxiv": [query]})
        return {"arxiv": [{"title": "Real result", "doi": "10.1234/result"}]}

    runtime.async_search_with_filters = search
    response = await rs.search_papers(
        rs.SearchRequest(query="original query", sources=["arxiv"], save_papers=False), None
    )
    modes = response.metadata["stage_modes"]
    assert response.total == 1
    if analysis_status:
        assert observed == ["original query"]
        assert modes["academic_guard_passed"] is False
        assert modes["query_analysis_mode"] == "original_query_fallback_returned"
        assert any("original_query_fallback_returned" in reason for reason in response.metadata["degraded"])
        rs._set_cache.assert_not_called()
    else:
        assert observed == ["proposed rewrite"]
        assert modes["academic_guard_passed"] is True
        assert modes["query_analysis_mode"] == "unified_llm"
        rs._set_cache.assert_called_once()


@pytest.mark.asyncio
async def test_expired_rubric_preserves_partial_papers(runtime, monkeypatch):
    import threading
    import time
    from app.QueryAgent import rubric_evaluator
    constructor = MagicMock(side_effect=AssertionError("expired rubric must not start"))
    monkeypatch.setattr(rubric_evaluator, "RubricEvaluator", constructor)
    papers = [{"title": "Already retrieved", "doi": "10.1234/partial"}]
    result = {"papers": papers}
    evaluation = await rs._evaluate_deep_results("q", "paper_search", papers, result, time.monotonic() - 1, threading.Event())
    assert evaluation == {}
    assert result["papers"] == papers
    assert result["metadata"] == {"partial": True, "evaluation_mode": "skipped_budget"}
    constructor.assert_not_called()


@pytest.mark.asyncio
async def test_fresh_rank_opposes_identity_order_and_preserves_buckets(runtime, monkeypatch):
    async def search(query, filters):
        return {"arxiv": [
            {"title": "Second", "doi": "10.1234/a", "source": "arXiv"},
            {"title": "Best", "doi": "10.1234/z", "source": "arXiv"},
        ]}
    runtime.async_search_with_filters = search
    def rank(**kwargs):
        assert kwargs["deadline"] is not None
        assert kwargs["stop_event"] is not None
        return sorted(kwargs["papers"], key=lambda p: p["doi"], reverse=True)
    monkeypatch.setattr(rs, "_hybrid_ranker", SimpleNamespace(rank_papers=rank))
    response = await rs.search_papers(rs.SearchRequest(query="topic", sources=["arxiv"], fast_mode=True, save_papers=False), None)
    assert [p["doi"] for p in response.results["arxiv"]] == ["10.1234/z", "10.1234/a"]
    assert response.metadata["partial"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["search_source_cutoff", "search_global_cutoff", "llm", "smart"])
async def test_cooperative_llm_outer_deadline_keeps_completed_snapshot(runtime, monkeypatch, entry):
    import threading
    import time
    release, finished = threading.Event(), threading.Event()
    observed = {}
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {"is_academic": True, "confidence": 0}
    monkeypatch.setattr(rs, "query_analyzer", analyzer)
    monkeypatch.setattr(rs, "_LLM_SEARCH_TIMEOUT", .05)
    monkeypatch.setattr(rs, "_SMART_SEARCH_TIMEOUT", .05)
    monkeypatch.setattr(rs, "_SOURCE_SEARCH_TIMEOUT", .05 if entry != "search_global_cutoff" else 1)
    monkeypatch.setattr(rs, "_SEARCH_TIMEOUT", .05 if entry == "search_global_cutoff" else 1)

    def llm(query, max_results_per_source=10, context="", *, deadline=None, stop_event=None, snapshot_callback=None):
        observed.update(deadline=deadline, stop=stop_event)
        assert deadline is not None and 0 < deadline - time.monotonic() <= 1
        assert isinstance(stop_event, threading.Event)
        snapshot = {
            "arxiv": [{"title": "Completed", "doi": "10.1234/completed"}],
            "openalex": [],
            "_metadata": {"timings": {"arxiv": .001}, "modes": {"arxiv": "searched"},
                          "timeouts": {"arxiv": False}, "executed_queries": {"arxiv": ["actual"]}},
        }
        snapshot_callback(snapshot)
        release.wait(2)
        snapshot["arxiv"][0]["title"] = "Late mutation"
        snapshot_callback(snapshot)
        finished.set()
        return snapshot

    def smart(query, max_results=20, *, deadline=None, stop_event=None, snapshot_callback=None):
        snapshot = llm(query, deadline=deadline, stop_event=stop_event, snapshot_callback=snapshot_callback)
        return {"papers": snapshot["arxiv"], "metadata": snapshot["_metadata"]}

    runtime.llm_context_search = llm
    runtime.smart_search = smart
    try:
        if entry.startswith("search_"):
            response = await rs.search_papers(rs.SearchRequest(
                query="topic", sources=["arxiv", "openalex"], use_llm_search=True, save_papers=False,
            ), None)
            papers, metadata = response.results["arxiv"], response.metadata
            assert response.source_timeouts["openalex"] is True
            assert response.stage_modes["source_search_mode"] == "timeout_partial"
            rs._set_cache.assert_not_called()
        elif entry == "llm":
            response = await rs.llm_context_search(rs.LLMSearchRequest(query="topic", save_papers=False), None)
            papers, metadata = response.results["arxiv"], response.metadata
            assert metadata["partial"] is True
        else:
            response = await rs.smart_search(rs.LLMSearchRequest(query="topic", save_papers=False), None)
            papers, metadata = response["papers"], response["metadata"]
            assert metadata["partial"] is True
        assert papers[0]["title"] == "Completed"
        assert papers[0]["_rank"] == 0
        assert metadata["executed_queries"] == {"arxiv": ["actual"]}
        assert metadata["save_status"] == "not_requested"
        assert observed["stop"].is_set()
    finally:
        release.set()
    assert finished.wait(1)
    await asyncio.sleep(0)
    assert papers[0]["title"] == "Completed"
    assert metadata["executed_queries"] == {"arxiv": ["actual"]}


def test_finalize_filters_graph_and_identity(runtime):
    raw = {
        "arxiv": [
            {"title": "동일 제목", "doi": "10.1234/a", "year": 2024, "authors": ["Li"], "_rank": 8},
            {"title": "동일 제목", "doi": "10.1234/b", "year": 2024, "authors": ["Li"], "_rank": 4},
        ],
        "graphrag": [{"title": "Rejected", "authors": ["Williams"]}],
    }
    results, drops = rs._finalize_results(raw, {"year_start": 2024, "author": "Li", "max_results": 10}, ["arxiv"])
    papers = results["arxiv"]
    assert len(papers) == 2
    assert len({p["result_key"] for p in papers}) == 2
    assert [p["_rank"] for p in papers] == [0, 1]
    assert results["graphrag"] == []
    assert drops == {"unknown_year": 1}
    assert raw["arxiv"][0]["_rank"] == 8


@pytest.mark.asyncio
async def test_timeout_publishes_completed_source_only(runtime, monkeypatch):
    async def search(query, filters):
        filters["_partial_results"]["arxiv"] = [{"title": "Completed", "doi": "10.1234/complete"}]
        filters["_metadata"]["modes"]["arxiv"] = "searched"
        await asyncio.Event().wait()
    runtime.async_search_with_filters = search
    monkeypatch.setattr(rs, "_SOURCE_SEARCH_TIMEOUT", 0.01)
    response = await rs.search_papers(rs.SearchRequest(query="topic", sources=["arxiv", "openalex"], fast_mode=True, save_papers=False), None)
    assert response.total == 1
    assert response.results["arxiv"][0]["_rank"] == 0
    assert response.source_timeouts["openalex"] is True
    assert response.stage_modes["source_search_mode"] == "timeout_partial"
    rs._set_cache.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["10.1234/example", "2301.12345", '"Exact Paper Title"'])
async def test_exact_routes_bypass_analysis_and_rewrite(runtime, monkeypatch, query):
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.side_effect = AssertionError("must not analyze exact routes")
    monkeypatch.setattr(rs, "query_analyzer", analyzer)
    seen = []
    async def search(actual, filters):
        seen.append(actual)
        return {"arxiv": []}
    runtime.async_search_with_filters = search
    response = await rs.search_papers(rs.SearchRequest(query=query, sources=["arxiv"], save_papers=False), None)
    assert seen == [query]
    assert response.metadata["executed_query"] == query
    analyzer.analyze_and_prepare.assert_not_called()


@pytest.mark.asyncio
async def test_fast_rank_capabilities_and_actual_query(runtime, monkeypatch):
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {"is_academic": True, "confidence": .95, "improved_query": "graph retrieval", "source_queries": {"openalex": "graph retrieval"}}
    monkeypatch.setattr(rs, "query_analyzer", analyzer)
    ranker = MagicMock()
    ranker.rank_papers.side_effect = lambda **kw: kw["papers"]
    monkeypatch.setattr(rs, "_hybrid_ranker", ranker)
    graph = MagicMock(side_effect=AssertionError("fast graph forbidden"))
    monkeypatch.setattr(rs, "_graphrag_expand", graph)
    async def search(query, filters):
        assert query == "graph retrieval"
        filters["_metadata"]["executed_queries"] = {"openalex": [query]}
        return {"openalex": [{"title": "Graph retrieval", "doi": "10.1234/graph"}]}
    runtime.async_search_with_filters = search
    response = await rs.search_papers(rs.SearchRequest(query="그래프 검색", sources=["openalex"], fast_mode=True, save_papers=False), None)
    assert ranker.rank_papers.call_args.kwargs["fast_mode"] is True
    assert ranker.rank_papers.call_args.kwargs["openai_client"] is None
    assert response.metadata["executed_queries"] == {"openalex": ["graph retrieval"]}
    assert response.metadata["save_status"] == "not_requested"
    graph.assert_not_called()


@pytest.mark.asyncio
async def test_cache_finalization_filters_and_keeps_executed_query(runtime, monkeypatch):
    monkeypatch.setattr(rs, "_get_cached_result", lambda *a, **k: {
        "arxiv": [{"title": "Old", "year": 2010}, {"title": "New", "year": 2025, "doi": "10.1234/new", "_rank": 9}],
        "_metadata": {"executed_query": "translated", "executed_queries": {"arxiv": ["translated"]}},
    })
    response = await rs.search_papers(rs.SearchRequest(query="original", sources=["arxiv"], year_start=2020, save_papers=False), "reader")
    assert response.cache_hit
    assert response.total == 1
    paper = response.results["arxiv"][0]
    assert paper["_rank"] == 0 and paper["result_key"] == "doi:10.1234/new"
    assert paper["searched_by"] == "reader"
    assert response.metadata["executed_query"] == "translated"


@pytest.mark.asyncio
async def test_disconnect_before_publication_creates_no_save(runtime, monkeypatch):
    started = asyncio.Event()
    async def search(query, filters):
        started.set()
        await asyncio.Event().wait()
    runtime.async_search_with_filters = search
    admission = MagicMock()
    monkeypatch.setattr(rs, "_admit_save", admission)
    task = asyncio.create_task(rs.search_papers(
        rs.SearchRequest(query="topic", sources=["arxiv"], fast_mode=True), None,
    ))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    admission.assert_not_called()


@pytest.mark.asyncio
async def test_late_rank_worker_cannot_mutate_published_partial(runtime, monkeypatch):
    import threading
    release, finished = threading.Event(), threading.Event()
    async def search(query, filters):
        return {"arxiv": [{"title": "Before", "doi": "10.1234/private"}]}
    runtime.async_search_with_filters = search
    def rank(**kwargs):
        release.wait(2)
        kwargs["papers"][0]["title"] = "After"
        finished.set()
        return kwargs["papers"]
    monkeypatch.setattr(rs, "_hybrid_ranker", SimpleNamespace(rank_papers=rank))
    monkeypatch.setattr(rs, "_RANKING_TIMEOUT", .01)
    try:
        response = await rs.search_papers(rs.SearchRequest(query="topic", sources=["arxiv"], fast_mode=True, save_papers=False), None)
        assert response.results["arxiv"][0]["title"] == "Before"
        rs._set_cache.assert_not_called()
    finally:
        release.set()
    assert finished.wait(1)
    assert response.results["arxiv"][0]["title"] == "Before"
