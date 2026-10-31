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
    monkeypatch.setattr(
        rs, "_router_operation_owner", rs.SearchAgent.__new__(rs.SearchAgent)
    )
    agent = SimpleNamespace(deduplicator=PaperDeduplicator())
    monkeypatch.setattr(rs, "search_agent", agent)
    monkeypatch.setattr(rs, "query_analyzer", None)
    monkeypatch.setattr(rs, "_get_cached_result", lambda *a, **k: None)
    monkeypatch.setattr(rs, "_set_cache", MagicMock())
    monkeypatch.setattr(rs, "_persist_last_search", MagicMock())
    monkeypatch.setattr(rs, "_hybrid_ranker", None)
    monkeypatch.setattr(rs, "_RANKER_DEGRADATION_REASONS", [])
    return agent


@pytest.mark.parametrize(
    "change",
    [
        {"sources": []},
        {"sources": ["unknown"]},
        {"max_results": 0},
        {"max_results": 101},
        {"sort_by": "bogus"},
        {"year_start": 2025, "year_end": 2020},
        {"year_start": -1},
    ],
)
def test_invalid_requests(change):
    with pytest.raises(ValidationError):
        rs.SearchRequest(query="research", **change)


def test_sources_are_canonical():
    assert rs.SearchRequest(
        query="x", sources=["openalex", "arxiv", "arxiv"]
    ).sources == ["arxiv", "openalex"]


@pytest.mark.asyncio
async def test_llm_request_dispatches_only_selected_sources(runtime, monkeypatch):
    agent = rs.SearchAgent.__new__(rs.SearchAgent)
    agent.search_history = []
    agent.deduplicator = runtime.deduplicator
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {
        "is_academic": True,
        "confidence": 0.95,
        "improved_query": "graph learning",
        "source_queries": {"openalex": "graph learning"},
    }
    agent.query_analyzer = analyzer
    for attribute in set(agent._SOURCE_SEARCHER_ATTRS.values()):
        provider = MagicMock()
        provider.search.side_effect = AssertionError("unrequested provider invoked")
        setattr(agent, attribute, provider)
    agent.openalex_searcher.search.side_effect = None
    agent.openalex_searcher.search.return_value = [
        {"title": "Selected result", "doi": "10.1234/selected", "source": "OpenAlex"}
    ]
    agent.openalex_searcher.search_korean.side_effect = AssertionError(
        "unrequested Korean source invoked"
    )
    monkeypatch.setattr(rs, "search_agent", agent)
    monkeypatch.setattr(rs, "query_analyzer", analyzer)
    monkeypatch.setattr(rs, "_graphrag_expand", lambda *args, **kwargs: [])

    response = await rs.search_papers(
        rs.SearchRequest(
            query="graph learning",
            sources=["openalex"],
            use_llm_search=True,
            save_papers=False,
        ),
        None,
    )

    agent.openalex_searcher.search.assert_called_once()
    agent.openalex_searcher.search_korean.assert_not_called()
    for source, attribute in agent._SOURCE_SEARCHER_ATTRS.items():
        if source not in ("openalex", "openalex_korean"):
            getattr(agent, attribute).search.assert_not_called()
    assert response.total == 1
    assert response.stage_modes["source_search_mode"] == "llm_context_search"
    assert set(response.source_timings) == {"openalex"}
    assert response.source_timeouts == {"openalex": False}
    assert response.metadata["executed_queries"] == {"openalex": ["graph learning"]}
    assert not (
        set(response.results)
        & {"arxiv", "google_scholar", "connected_papers", "dblp", "openalex_korean"}
    )


def test_relevance_survives_dedup_and_provider_display_source(runtime):
    original = {
        "arxiv": [
            {"title": "Best", "doi": "10.1234/z", "source": "arXiv", "_rank": 0},
            {"title": "Second", "doi": "10.1234/a", "source": "arXiv", "_rank": 1},
        ]
    }
    for _ in range(3):
        finalized, _ = rs._finalize_results(
            original, {"sort_by": "relevance"}, ["arxiv"]
        )
        assert [p["doi"] for p in finalized["arxiv"]] == ["10.1234/z", "10.1234/a"]
        rebuilt = rs._rebuild_results_from_ranked(finalized["arxiv"], ["arxiv"])
        assert len(rebuilt["arxiv"]) == 2
        original = rebuilt


@pytest.mark.asyncio
async def test_http_disconnect_stops_before_save_without_task_cancel(
    runtime, monkeypatch
):
    from starlette.requests import Request

    messages = asyncio.Queue()

    async def receive():
        return await messages.get()

    http = Request(
        {"type": "http", "method": "POST", "path": "/api/search", "headers": []},
        receive,
    )

    async def search(query, filters):
        await messages.put({"type": "http.disconnect"})
        while not filters["_stop_event"].is_set():
            await asyncio.sleep(0)
        return {"arxiv": [{"title": "Completed", "doi": "10.1234/disconnect"}]}

    runtime.async_search_with_filters = search
    save = MagicMock()
    runtime.save_papers = save
    response = await rs.search_papers(
        rs.SearchRequest(query="topic", sources=["arxiv"], fast_mode=True), None, http
    )
    assert response.metadata["save_status"] == "not_admitted_disconnect"
    save.assert_not_called()


@pytest.mark.asyncio
async def test_observer_terminates_when_receive_swallows_cancellation(runtime):
    entered = asyncio.Event()

    class SwallowingRequest:
        state = SimpleNamespace()

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
    response = await asyncio.wait_for(
        rs.search_papers(
            rs.SearchRequest(
                query="topic", sources=["arxiv"], fast_mode=True, save_papers=False
            ),
            None,
            SwallowingRequest(),
        ),
        timeout=1,
    )
    assert response.total == 0
    assert not [
        task
        for task in asyncio.all_tasks() - before
        if "observe_disconnect" in task.get_coro().__qualname__
    ]


@pytest.mark.asyncio
async def test_accepted_save_observer_ends_on_completion(runtime):
    import threading
    from starlette.requests import Request

    release = threading.Event()

    async def receive():
        await asyncio.Event().wait()

    http = Request(
        {"type": "http", "method": "POST", "path": "/api/search", "headers": []},
        receive,
    )

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
            rs.SearchRequest(query="topic", sources=["arxiv"], fast_mode=True),
            None,
            http,
        )
        assert response.metadata["save_status"] == "accepted"
        observers = [
            task
            for task in asyncio.all_tasks() - before
            if "observe_disconnect" in task.get_coro().__qualname__
        ]
        assert len(observers) == 1
    finally:
        release.set()
    await asyncio.wait_for(asyncio.gather(*observers), timeout=1)
    assert all(task.done() for task in observers)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "analysis_status",
    [None, "unavailable_original_query", "low_confidence_original_query"],
)
async def test_returned_analysis_fallback_never_establishes_guard_or_cache(
    runtime, monkeypatch, analysis_status
):
    analysis = {
        "is_academic": True,
        "confidence": 0.95,
        "improved_query": "proposed rewrite",
    }
    if analysis_status:
        analysis["analysis_status"] = analysis_status
    analyzer = SimpleNamespace(analyze_and_prepare=MagicMock(return_value=analysis))
    monkeypatch.setattr(rs, "query_analyzer", analyzer)
    monkeypatch.setattr(rs, "_graphrag_expand", lambda *args, **kwargs: [])
    observed = []

    async def search(query, filters):
        observed.append(query)
        filters["_metadata"].update(
            modes={"arxiv": "searched"}, executed_queries={"arxiv": [query]}
        )
        return {"arxiv": [{"title": "Real result", "doi": "10.1234/result"}]}

    runtime.async_search_with_filters = search
    response = await rs.search_papers(
        rs.SearchRequest(query="original query", sources=["arxiv"], save_papers=False),
        None,
    )
    modes = response.metadata["stage_modes"]
    assert response.total == 1
    if analysis_status:
        assert observed == ["original query"]
        assert modes["academic_guard_passed"] is False
        assert modes["query_analysis_mode"] == "original_query_fallback_returned"
        assert any(
            "original_query_fallback_returned" in reason
            for reason in response.metadata["degraded"]
        )
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
    evaluation = await rs._evaluate_deep_results(
        "q", "paper_search", papers, result, time.monotonic() - 1, threading.Event()
    )
    assert evaluation == {}
    assert result["papers"] == papers
    assert result["metadata"] == {"partial": True, "evaluation_mode": "skipped_budget"}
    constructor.assert_not_called()


@pytest.mark.asyncio
async def test_fresh_rank_opposes_identity_order_and_preserves_buckets(
    runtime, monkeypatch
):
    async def search(query, filters):
        return {
            "arxiv": [
                {"title": "Second", "doi": "10.1234/a", "source": "arXiv"},
                {"title": "Best", "doi": "10.1234/z", "source": "arXiv"},
            ]
        }

    runtime.async_search_with_filters = search

    def rank(**kwargs):
        assert kwargs["deadline"] is not None
        assert kwargs["stop_event"] is not None
        return sorted(kwargs["papers"], key=lambda p: p["doi"], reverse=True)

    monkeypatch.setattr(rs, "_hybrid_ranker", SimpleNamespace(rank_papers=rank))
    response = await rs.search_papers(
        rs.SearchRequest(
            query="topic", sources=["arxiv"], fast_mode=True, save_papers=False
        ),
        None,
    )
    assert [p["doi"] for p in response.results["arxiv"]] == ["10.1234/z", "10.1234/a"]
    assert response.metadata["partial"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry", ["search_source_cutoff", "search_global_cutoff", "llm", "smart"]
)
async def test_cooperative_llm_outer_deadline_keeps_completed_snapshot(
    runtime, monkeypatch, entry
):
    import threading
    import time

    release, finished = threading.Event(), threading.Event()
    snapshot_published = threading.Event()
    loop = asyncio.get_running_loop()
    # Preparation and worker startup must not consume the snapshot's test budget.
    clock = [time.monotonic()]

    def monotonic():
        return clock[0]

    monkeypatch.setattr(
        rs, "time", SimpleNamespace(monotonic=monotonic, time=time.time)
    )
    monkeypatch.setattr(loop, "time", monotonic)
    observed = {}
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {"is_academic": True, "confidence": 0}
    monkeypatch.setattr(rs, "query_analyzer", analyzer)
    monkeypatch.setattr(rs, "_LLM_SEARCH_TIMEOUT", 0.05)
    monkeypatch.setattr(rs, "_SMART_SEARCH_TIMEOUT", 0.05)
    monkeypatch.setattr(
        rs, "_SOURCE_SEARCH_TIMEOUT", 0.05 if entry != "search_global_cutoff" else 1
    )
    monkeypatch.setattr(
        rs, "_SEARCH_TIMEOUT", 0.05 if entry == "search_global_cutoff" else 1
    )

    def llm(
        query,
        max_results_per_source=10,
        context="",
        *,
        sources=None,
        deadline=None,
        stop_event=None,
        snapshot_callback=None,
    ):
        observed.update(deadline=deadline, stop=stop_event)
        assert deadline is not None and 0 < deadline - monotonic() <= 1
        assert isinstance(stop_event, threading.Event)
        snapshot = {
            "arxiv": [{"title": "Completed", "doi": "10.1234/completed"}],
            "openalex": [],
            "_metadata": {
                "timings": {"arxiv": 0.001},
                "modes": {"arxiv": "searched"},
                "timeouts": {"arxiv": False},
                "executed_queries": {"arxiv": ["actual"]},
            },
        }
        snapshot_callback(snapshot)
        # Delivery and this signal are queued in order on the same event loop.
        loop.call_soon_threadsafe(snapshot_published.set)
        release.wait(2)
        snapshot["arxiv"][0]["title"] = "Late mutation"
        snapshot_callback(snapshot)
        finished.set()
        return snapshot

    def smart(
        query, max_results=20, *, deadline=None, stop_event=None, snapshot_callback=None
    ):
        snapshot = llm(
            query,
            deadline=deadline,
            stop_event=stop_event,
            snapshot_callback=snapshot_callback,
        )
        return {"papers": snapshot["arxiv"], "metadata": snapshot["_metadata"]}

    runtime.llm_context_search = llm
    runtime.smart_search = smart
    try:
        if entry.startswith("search_"):
            request = rs.search_papers(
                rs.SearchRequest(
                    query="topic",
                    sources=["arxiv", "openalex"],
                    use_llm_search=True,
                    save_papers=False,
                ),
                None,
            )
        elif entry == "llm":
            request = rs.llm_context_search(
                rs.LLMSearchRequest(query="topic", save_papers=False), None
            )
        else:
            request = rs.smart_search(
                rs.LLMSearchRequest(query="topic", save_papers=False), None
            )

        request_task = asyncio.create_task(request)
        snapshot_seen = await asyncio.to_thread(snapshot_published.wait, 2)
        clock[0] += 0.051
        await asyncio.sleep(0)
        response = await request_task
        assert snapshot_seen

        if entry.startswith("search_"):
            papers, metadata = response.results["arxiv"], response.metadata
            assert response.source_timeouts["openalex"] is True
            assert response.stage_modes["source_search_mode"] == "timeout_partial"
            rs._set_cache.assert_not_called()
        elif entry == "llm":
            papers, metadata = response.results["arxiv"], response.metadata
            assert metadata["partial"] is True
        else:
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
            {
                "title": "동일 제목",
                "doi": "10.1234/a",
                "year": 2024,
                "authors": ["Li"],
                "_rank": 8,
            },
            {
                "title": "동일 제목",
                "doi": "10.1234/b",
                "year": 2024,
                "authors": ["Li"],
                "_rank": 4,
            },
        ],
        "graphrag": [{"title": "Rejected", "authors": ["Williams"]}],
    }
    results, drops = rs._finalize_results(
        raw, {"year_start": 2024, "author": "Li", "max_results": 10}, ["arxiv"]
    )
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
        filters["_partial_results"]["arxiv"] = [
            {"title": "Completed", "doi": "10.1234/complete"}
        ]
        filters["_metadata"]["modes"]["arxiv"] = "searched"
        await asyncio.Event().wait()

    runtime.async_search_with_filters = search
    monkeypatch.setattr(rs, "_SOURCE_SEARCH_TIMEOUT", 0.01)
    response = await rs.search_papers(
        rs.SearchRequest(
            query="topic",
            sources=["arxiv", "openalex"],
            fast_mode=True,
            save_papers=False,
        ),
        None,
    )
    assert response.total == 1
    assert response.results["arxiv"][0]["_rank"] == 0
    assert response.source_timeouts["openalex"] is True
    assert response.stage_modes["source_search_mode"] == "timeout_partial"
    rs._set_cache.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query", ["10.1234/example", "2301.12345", '"Exact Paper Title"']
)
async def test_exact_routes_bypass_analysis_and_rewrite(runtime, monkeypatch, query):
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.side_effect = AssertionError(
        "must not analyze exact routes"
    )
    monkeypatch.setattr(rs, "query_analyzer", analyzer)
    seen = []

    async def search(actual, filters):
        seen.append(actual)
        return {"arxiv": []}

    runtime.async_search_with_filters = search
    response = await rs.search_papers(
        rs.SearchRequest(query=query, sources=["arxiv"], save_papers=False), None
    )
    assert seen == [query]
    assert response.metadata["executed_query"] == query
    analyzer.analyze_and_prepare.assert_not_called()


@pytest.mark.asyncio
async def test_fast_rank_capabilities_and_actual_query(runtime, monkeypatch):
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {
        "is_academic": True,
        "confidence": 0.95,
        "improved_query": "graph retrieval",
        "source_queries": {"openalex": "graph retrieval"},
    }
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
    response = await rs.search_papers(
        rs.SearchRequest(
            query="그래프 검색", sources=["openalex"], fast_mode=True, save_papers=False
        ),
        None,
    )
    assert ranker.rank_papers.call_args.kwargs["fast_mode"] is True
    assert ranker.rank_papers.call_args.kwargs["openai_client"] is None
    assert response.metadata["executed_queries"] == {"openalex": ["graph retrieval"]}
    assert response.metadata["save_status"] == "not_requested"
    graph.assert_not_called()


@pytest.mark.asyncio
async def test_cache_finalization_filters_and_keeps_executed_query(
    runtime, monkeypatch
):
    monkeypatch.setattr(
        rs,
        "_get_cached_result",
        lambda *a, **k: {
            "arxiv": [
                {"title": "Old", "year": 2010},
                {"title": "New", "year": 2025, "doi": "10.1234/new", "_rank": 9},
            ],
            "_metadata": {
                "executed_query": "translated",
                "executed_queries": {"arxiv": ["translated"]},
            },
        },
    )
    response = await rs.search_papers(
        rs.SearchRequest(
            query="original", sources=["arxiv"], year_start=2020, save_papers=False
        ),
        "reader",
    )
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
    task = asyncio.create_task(
        rs.search_papers(
            rs.SearchRequest(query="topic", sources=["arxiv"], fast_mode=True),
            None,
        )
    )
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
    monkeypatch.setattr(rs, "_RANKING_TIMEOUT", 0.01)
    try:
        response = await rs.search_papers(
            rs.SearchRequest(
                query="topic", sources=["arxiv"], fast_mode=True, save_papers=False
            ),
            None,
        )
        assert response.results["arxiv"][0]["title"] == "Before"
        rs._set_cache.assert_not_called()
    finally:
        release.set()
    assert finished.wait(1)
    assert response.results["arxiv"][0]["title"] == "Before"


@pytest.mark.asyncio
async def test_search_timings_split_cache_finalize_and_handoff(runtime):
    async def search(query, filters):
        return {"arxiv": [{"title": "Timed result", "doi": "10.1234/timed"}]}

    runtime.async_search_with_filters = search
    response = await rs.search_papers(
        rs.SearchRequest(
            query="10.1234/timing-contract",
            sources=["arxiv"],
            save_papers=False,
        ),
        None,
    )

    timings = response.stage_timings
    assert timings is not None
    assert {
        "search_cache_read",
        "search_cache_write",
        "search_finalize",
        "search_handoff",
        "search_cache_io",
        "total",
    } <= set(timings)
    assert all(elapsed >= 0 for elapsed in timings.values())
    assert "10.1234/timing-contract" not in timings
    assert rs._set_cache.call_count == 1
    assert rs._persist_last_search.call_count == 1


@pytest.mark.asyncio
async def test_cache_hit_timing_keeps_read_and_finalize_separate(runtime, monkeypatch):
    monkeypatch.setattr(
        rs,
        "_get_cached_result",
        lambda *args, **kwargs: {
            "arxiv": [{"title": "Cached", "doi": "10.1234/cached"}],
            "_metadata": {},
        },
    )
    response = await rs.search_papers(
        rs.SearchRequest(
            query="cached timing",
            sources=["arxiv"],
            save_papers=False,
        ),
        None,
    )

    timings = response.stage_timings
    assert response.cache_hit is True
    assert timings is not None
    assert timings["search_cache_read"] >= 0
    assert timings["search_finalize"] >= 0
    assert "search_cache_write" not in timings
    assert "search_handoff" not in timings
    assert "search_cache_io" in timings


def test_graphrag_seed_expansion_avoids_embedding_index_load(monkeypatch):
    import networkx as nx
    from src.graph_rag import search_engine

    graph = nx.MultiDiGraph()
    graph.add_node("seed", title="Seed")
    graph.add_node("neighbor", title="Neighbor", abstract="related")
    graph.add_edge("seed", "neighbor", edge_type="CITES")
    monkeypatch.setattr(rs, "_load_graph_cached", lambda: graph)
    loader = MagicMock(side_effect=AssertionError("graph-only expansion loaded FAISS"))
    fallback = MagicMock(side_effect=AssertionError("seed expansion used fallback"))
    monkeypatch.setattr(search_engine.SearchEngine, "load_embeddings", loader)
    monkeypatch.setattr(search_engine.SearchEngine, "_keyword_fallback", fallback)

    expanded = rs._graphrag_expand(
        "unrelated query", [{"title": "Seed"}], max_expand=5
    )

    assert [paper["title"] for paper in expanded] == ["Neighbor"]
    loader.assert_not_called()
    fallback.assert_not_called()


@pytest.mark.parametrize(
    "seed",
    [
        {"title": "DOI Seed", "doi": "https://doi.org/10.1234/SEED"},
        {"title": "Graph-RAG: 한글 검색"},
        {"title": "A long graph paper title " * 8},
        {"title": "", "doi": "10.1234/titleless"},
    ],
)
def test_graphrag_uses_graph_builder_identity(monkeypatch, seed):
    import networkx as nx
    from src.graph.node_creator import NodeCreator
    from src.graph_rag import search_engine

    node = NodeCreator().create_node(seed)
    graph = nx.MultiDiGraph()
    graph.add_node(node["node_id"], **node)
    graph.add_node("neighbor", title="Neighbor", abstract="related")
    graph.add_edge(node["node_id"], "neighbor", edge_type="CITES")
    monkeypatch.setattr(rs, "_load_graph_cached", lambda: graph)
    fallback = MagicMock(side_effect=AssertionError("known seed used keyword scan"))
    monkeypatch.setattr(search_engine.SearchEngine, "_keyword_fallback", fallback)

    expanded = rs._graphrag_expand("unrelated query", [seed], max_expand=5)

    assert [paper["title"] for paper in expanded] == ["Neighbor"]
    fallback.assert_not_called()


def test_graphrag_excludes_existing_canonical_ids_and_keeps_order(monkeypatch):
    import networkx as nx
    from src.graph_rag import search_engine
    from src.utils.paper_utils import generate_paper_id

    seed = {"title": "Seed", "doi": "10.1234/seed"}
    existing = {"title": "Existing", "doi": "10.1234/existing"}
    seed_id = generate_paper_id(seed)
    existing_id = generate_paper_id(existing)
    graph = nx.MultiDiGraph()
    graph.add_node(seed_id, **seed)
    graph.add_node(existing_id, **existing)
    graph.add_node("first", title="First")
    graph.add_node("second", title="Second")
    graph.add_node("third", title="Third")
    monkeypatch.setattr(rs, "_load_graph_cached", lambda: graph)
    expand = MagicMock(
        return_value=[seed_id, existing_id, "second", "second", "first", "third"]
    )
    monkeypatch.setattr(search_engine.SearchEngine, "expand_graph", expand)

    expanded = rs._graphrag_expand(
        "unrelated query", [seed, dict(seed), existing], max_expand=2
    )

    assert [paper["title"] for paper in expanded] == ["Second", "First"]
    assert expand.call_args.args[0] == [seed_id, existing_id]
    assert expand.call_args.kwargs["max_expanded"] == 4


def test_graphrag_keyword_fallback_keeps_graph_only_results(monkeypatch):
    import networkx as nx
    from src.graph_rag import search_engine

    graph = nx.MultiDiGraph()
    graph.add_node(
        "fallback",
        title="Fallback Candidate",
        abstract="graph retrieval",
    )
    monkeypatch.setattr(rs, "_load_graph_cached", lambda: graph)
    loader = MagicMock(side_effect=AssertionError("graph-only fallback loaded FAISS"))
    monkeypatch.setattr(search_engine.SearchEngine, "load_embeddings", loader)

    expanded = rs._graphrag_expand(
        "graph retrieval", [{"title": "Missing seed"}], max_expand=5
    )

    assert [paper["title"] for paper in expanded] == ["Fallback Candidate"]
    loader.assert_not_called()


def test_graphrag_missing_graph_is_a_graceful_noop(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing_graph.pkl"
    monkeypatch.setattr(rs, "_GRAPH_PATH", missing_path)
    monkeypatch.setattr(rs, "_cached_graph", None)
    monkeypatch.setattr(rs, "_cached_graph_mtime", 0.0)

    assert rs._load_graph_cached() is None
    assert rs._graphrag_expand("graph retrieval", [{"title": "Seed"}]) == []


def test_graph_cache_refreshes_when_pickle_mtime_changes(monkeypatch, tmp_path):
    import os
    import pickle
    import networkx as nx

    graph_path = tmp_path / "paper_graph.pkl"
    monkeypatch.setattr(rs, "_GRAPH_PATH", graph_path)
    monkeypatch.setattr(rs, "_cached_graph", None)
    monkeypatch.setattr(rs, "_cached_graph_mtime", 0.0)

    first = nx.MultiDiGraph()
    first.add_node("first", title="First")
    second = nx.MultiDiGraph()
    second.add_node("second", title="Second")

    with graph_path.open("wb") as handle:
        pickle.dump(first, handle)
    os.utime(graph_path, ns=(1_000_000_000, 1_000_000_000))
    loaded_first = rs._load_graph_cached()
    assert loaded_first is not None
    assert set(loaded_first.nodes) == {"first"}
    assert rs._load_graph_cached() is loaded_first

    with graph_path.open("wb") as handle:
        pickle.dump(second, handle)
    os.utime(graph_path, ns=(2_000_000_000, 2_000_000_000))
    loaded_second = rs._load_graph_cached()

    assert loaded_second is not loaded_first
    assert set(loaded_second.nodes) == {"second"}


def test_graphrag_does_not_open_embedding_mapping_file(monkeypatch, tmp_path):
    import builtins
    import os
    import pickle
    import networkx as nx

    graph_path = tmp_path / "paper_graph.pkl"
    graph = nx.MultiDiGraph()
    graph.add_node("seed", title="Seed")
    graph.add_node("neighbor", title="Neighbor", abstract="related")
    graph.add_edge("seed", "neighbor", edge_type="CITES")
    with graph_path.open("wb") as handle:
        pickle.dump(graph, handle)

    monkeypatch.setattr(rs, "_GRAPH_PATH", graph_path)
    monkeypatch.setattr(rs, "_cached_graph", None)
    monkeypatch.setattr(rs, "_cached_graph_mtime", 0.0)
    opened_paths = []
    real_open = builtins.open

    def tracking_open(path, *args, **kwargs):
        normalized = os.fspath(path)
        opened_paths.append(normalized)
        assert os.path.basename(normalized) != "paper_id_mapping.json"
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracking_open)

    expanded = rs._graphrag_expand(
        "unrelated query", [{"title": "Seed"}], max_expand=5
    )

    assert [paper["title"] for paper in expanded] == ["Neighbor"]
    assert os.fspath(graph_path) in opened_paths
    assert all(
        os.path.basename(path) != "paper_id_mapping.json" for path in opened_paths
    )
