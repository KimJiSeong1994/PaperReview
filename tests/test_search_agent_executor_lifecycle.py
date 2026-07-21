from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from app.SearchAgent import search_agent as search_agent_module
from app.SearchAgent.search_agent import SearchAgent, SearchCapacityExceeded


def _search_threads() -> list[threading.Thread]:
    return [
        thread for thread in threading.enumerate() if thread.name.startswith("search_")
    ]


def _wait_for_search_threads_to_stop(timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while _search_threads() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert _search_threads() == []


def _wait_for_operation_generation_release(
    agent: SearchAgent, operation: str, timeout: float = 1.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lock, generations = agent._operation_generation_state()
        with lock:
            if operation not in generations:
                return
        time.sleep(0.005)

    lock, generations = agent._operation_generation_state()
    with lock:
        assert operation not in generations


def _make_agent() -> SearchAgent:
    agent = SearchAgent.__new__(SearchAgent)
    agent.search_history = []

    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {
        "keywords": ["graph", "neural"],
        "improved_query": "graph neural networks",
        "search_strategy": "keyword search",
        "source_queries": {
            "arxiv": "graph neural networks",
            "google_scholar": "graph neural networks",
            "scholar_queries": ["graph neural networks"],
        },
    }
    agent.query_analyzer = analyzer

    agent.arxiv_searcher = MagicMock()
    agent.arxiv_searcher.search.return_value = []
    agent.google_scholar_searcher = MagicMock()
    agent.google_scholar_searcher.search.return_value = []
    agent.connected_papers_searcher = MagicMock()
    agent.connected_papers_searcher.search.return_value = []
    agent.openalex_searcher = MagicMock()
    agent.openalex_searcher.search.return_value = []
    agent.openalex_searcher.search_korean.return_value = []
    agent.dblp_searcher = MagicMock()
    agent.dblp_searcher.search.return_value = []
    return agent


@pytest.fixture(autouse=True)
def no_preexisting_search_threads() -> None:
    assert _search_threads() == []


def test_llm_context_search_joins_workers_after_success() -> None:
    agent = _make_agent()

    result = agent.llm_context_search("graph neural networks")

    assert "_metadata" in result
    assert _search_threads() == []


def test_llm_context_search_joins_workers_after_worker_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _make_agent()
    agent.arxiv_searcher.search.side_effect = RuntimeError("worker failed")
    monkeypatch.setattr(
        search_agent_module,
        "_new_search_executor",
        lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="search"),
    )

    result = agent.llm_context_search("graph neural networks")

    assert result["arxiv"] == []
    assert agent.google_scholar_searcher.search.call_count == 1
    assert agent.connected_papers_searcher.search.call_count == 1
    assert agent.openalex_searcher.search.call_count == 1
    assert agent.openalex_searcher.search_korean.call_count == 1
    assert agent.dblp_searcher.search.call_count == 1
    assert _search_threads() == []


def test_same_operation_concurrent_calls_use_independent_generations() -> None:
    agent = _make_agent()
    providers_started = threading.Barrier(2)

    def analyze(query: str) -> dict[str, object]:
        return {
            "keywords": [query],
            "improved_query": query,
            "search_strategy": "keyword search",
            "source_queries": {
                "arxiv": query,
                "google_scholar": query,
                "scholar_queries": [query],
            },
        }

    def arxiv_search(query: str, _max_results: int) -> list[dict[str, object]]:
        providers_started.wait(timeout=1)
        return [{"title": query}]

    agent.query_analyzer.analyze_and_prepare.side_effect = analyze
    agent.arxiv_searcher.search.side_effect = arxiv_search

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="caller") as callers:
        futures = [
            callers.submit(agent.llm_context_search, query)
            for query in ("first query", "second query")
        ]
        results = [future.result(timeout=2) for future in futures]

    assert agent.arxiv_searcher.search.call_count == 2
    assert {result["arxiv"][0]["title"] for result in results} == {
        "first query",
        "second query",
    }
    _wait_for_operation_generation_release(agent, "llm_context_search")
    _wait_for_search_threads_to_stop()


def test_releasing_one_generation_preserves_other_set_member() -> None:
    agent = _make_agent()
    first = agent._begin_operation_generation("llm_context_search")
    second = agent._begin_operation_generation("llm_context_search")

    first.close()

    lock, generations = agent._operation_generation_state()
    with lock:
        assert generations["llm_context_search"] == {second}

    second.close()
    _wait_for_operation_generation_release(agent, "llm_context_search")
    _wait_for_search_threads_to_stop()


def test_operation_capacity_raises_before_query_analysis() -> None:
    agent = _make_agent()
    first = agent._begin_operation_generation("llm_context_search")
    second = agent._begin_operation_generation("llm_context_search")

    try:
        with pytest.raises(SearchCapacityExceeded, match="llm_context_search"):
            agent.llm_context_search("over capacity")
        agent.query_analyzer.analyze_and_prepare.assert_not_called()
    finally:
        first.close()
        second.close()

    _wait_for_operation_generation_release(agent, "llm_context_search")
    _wait_for_search_threads_to_stop()


def test_llm_context_search_timeout_is_nonblocking_and_generation_is_reusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _make_agent()
    worker_started = threading.Event()
    release_worker = threading.Event()
    call_lock = threading.Lock()
    call_count = 0

    def first_search_blocks(query: str, _max_results: int) -> list[dict[str, object]]:
        nonlocal call_count
        with call_lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            worker_started.set()
            release_worker.wait(timeout=2)
            return []
        return [{"title": query}]

    agent.arxiv_searcher.search.side_effect = first_search_blocks
    monkeypatch.setattr(
        search_agent_module, "_LLM_CONTEXT_SEARCH_TIMEOUT_SECONDS", 0.02
    )
    monkeypatch.setattr(
        search_agent_module,
        "_new_search_executor",
        lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="search"),
    )
    try:
        started_at = time.monotonic()
        result = agent.llm_context_search("graph neural networks")
        elapsed = time.monotonic() - started_at

        assert worker_started.is_set()
        assert elapsed < 0.2
        assert result["arxiv"] == []
        assert len(_search_threads()) == 1

        second_started_at = time.monotonic()
        second_result = agent.llm_context_search("graph neural networks")
        second_elapsed = time.monotonic() - second_started_at

        assert second_elapsed < 0.1
        assert second_result["arxiv"][0]["title"] == "graph neural networks"
        assert agent.arxiv_searcher.search.call_count == 2
        lock, generations = agent._operation_generation_state()
        with lock:
            assert len(generations["llm_context_search"]) == 1

        release_worker.set()
        _wait_for_search_threads_to_stop()
        _wait_for_operation_generation_release(agent, "llm_context_search")

        later_result = agent.llm_context_search("graph neural networks")

        assert "_metadata" in later_result
        assert agent.arxiv_searcher.search.call_count == 3
        assert agent.google_scholar_searcher.search.call_count == 2
        assert agent.connected_papers_searcher.search.call_count == 2
        assert agent.openalex_searcher.search.call_count == 2
        assert agent.openalex_searcher.search_korean.call_count == 2
        assert agent.dblp_searcher.search.call_count == 2
        assert _search_threads() == []
    finally:
        release_worker.set()
        _wait_for_search_threads_to_stop()
