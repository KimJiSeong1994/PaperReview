"""Real ReAct ownership under blocked providers/model calls; no live transport."""

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import routers.search as router
from app.SearchAgent.react_search_agent import ReActSearchAgent
from app.SearchAgent.search_agent import SearchAgent, SearchCapacityExceeded


async def _until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(wait(), 3)


def _active(owner):
    lock, generations = owner._operation_generation_state()
    with lock:
        return len(generations.get("react_search", ()))


def _owner(search):
    owner = SearchAgent.__new__(SearchAgent)
    owner.arxiv_searcher = SimpleNamespace(search=search)
    owner.openalex_searcher = SimpleNamespace(search=search)
    owner.dblp_searcher = SimpleNamespace(search=search)
    owner.deduplicator = SimpleNamespace(deduplicate=lambda papers: papers)
    return owner


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["deep", "sse"])
async def test_endpoint_cancellation_retains_two_slots_then_capacity_and_recovery(monkeypatch, stream):
    release = threading.Event()
    calls = []

    def blocked(query, limit, *, deadline, stop_event):
        calls.append((deadline, stop_event))
        assert release.wait(5), "test failed to release provider"
        return []

    owner = _owner(blocked)
    monkeypatch.setattr(router, "search_agent", owner)
    monkeypatch.setattr(router, "query_analyzer", None)
    monkeypatch.setattr(router, "get_openai_client", lambda: None)
    monkeypatch.setattr(router, "_hybrid_ranker", None)
    monkeypatch.setattr(router, "_router_shutdown", threading.Event())
    monkeypatch.setattr("app.QueryAgent.rubric_evaluator.RubricEvaluator.evaluate", AsyncMock(return_value={}))

    async def request():
        if stream:
            response = await router.deep_search_stream(
                router.DeepSearchStreamRequest(query="transformer", save_papers=False), None,
            )
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)
        return await router.deep_search(
            router.LLMSearchRequest(query="transformer", save_papers=False), None,
        )

    tasks = [asyncio.create_task(request()) for _ in range(2)]
    try:
        await _until(lambda: len(calls) == 4)
        assert _active(owner) == 2
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert all(stop.is_set() for _, stop in calls)
        assert _active(owner) == 2
        if stream:
            body = await request()
            assert "event: error" in body
            assert "capacity" in body.lower()
        else:
            with pytest.raises(HTTPException) as exc:
                await request()
            assert exc.value.status_code == 503
        assert len(calls) == 4
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _until(lambda: _active(owner) == 0)
    # Draining actual provider futures, not cancelling wrappers, restores admission.
    recovered = await request()
    if stream:
        assert "event: complete" in recovered
    else:
        assert recovered["papers"] == []
    await _until(lambda: _active(owner) == 0)


@pytest.mark.asyncio
async def test_deadline_preserves_completed_provider_and_rank_without_new_turn(monkeypatch):
    release = threading.Event()
    entered = threading.Event()
    calls = []
    paper = {"title": "Completed provider", "doi": "10.1/completed", "_source": "arxiv"}

    def fast(query, limit, **budget):
        calls.append("arxiv")
        return [paper]

    def blocked(query, limit, **budget):
        calls.append("openalex")
        entered.set()
        assert release.wait(5)
        return [{"title": "Late paper", "doi": "10.1/late"}]

    owner = _owner(fast)
    owner.openalex_searcher.search = blocked
    agent = ReActSearchAgent(owner, openai_client=object(), max_turns=3)
    gap = AsyncMock(side_effect=AssertionError("gap must not start after stop"))
    monkeypatch.setattr(agent, "_analyze_and_plan_next", gap)
    monkeypatch.setattr(router, "search_agent", owner)
    monkeypatch.setattr(router, "_hybrid_ranker", None)
    stop = threading.Event()
    expired = threading.Event()
    deadline = time.monotonic() + 60
    monkeypatch.setattr(
        "app.SearchAgent.react_search_agent.time",
        SimpleNamespace(monotonic=lambda: deadline + 1 if expired.is_set() else time.monotonic()),
    )
    task = asyncio.create_task(agent.search("transformer", deadline=deadline, stop_event=stop))
    try:
        await _until(entered.is_set)
        lock, generations = owner._operation_generation_state()
        with lock:
            generation = next(iter(generations["react_search"]))
        await _until(lambda: generation._futures[0].done())
        expired.set()
        result = await task
        assert entered.is_set()
        assert stop.is_set()
        assert [p["doi"] for p in result["papers"]] == [paper["doi"]]
        assert result["turns"] == 1
        assert sorted(calls) == ["arxiv", "openalex"]
        assert _active(owner) == 1
        ranked = await router._dedup_and_rank_deep_search(
            "transformer", result["papers"], "paper_search", deadline=deadline, stop_event=stop,
        )
        assert ranked[0]["_rank"] == 0
        assert ranked[0]["result_key"]
        gap.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await _until(lambda: _active(owner) == 0)
    assert len(result["papers"]) == 1
    assert sorted(calls) == ["arxiv", "openalex"]


@pytest.mark.asyncio
async def test_blocked_gap_model_retains_capacity_and_stop_prevents_followup(monkeypatch):
    release = threading.Event()
    entered = []
    provider_calls = []

    def provider(query, limit, **budget):
        provider_calls.append(query)
        return []

    def model(*args, **kwargs):
        entered.append(True)
        assert release.wait(5)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            "is_sufficient": False, "next_query": "must not execute", "missing": [],
        })))])

    monkeypatch.setattr("app.SearchAgent.react_search_agent.create_chat_completion", model)
    owner = _owner(provider)
    client_options = []

    def with_options(**kwargs):
        client_options.append(kwargs)
        return object()

    agent = ReActSearchAgent(
        owner, openai_client=SimpleNamespace(with_options=with_options), max_turns=3,
    )
    stops = [threading.Event(), threading.Event()]
    tasks = [asyncio.create_task(agent.search("transformer", stop_event=stop)) for stop in stops]
    try:
        await _until(lambda: len(entered) == 2)
        for stop in stops:
            stop.set()
        await asyncio.gather(*tasks)
        assert _active(owner) == 2
        with pytest.raises(SearchCapacityExceeded):
            await agent.search("third")
        assert len(provider_calls) == 4
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _until(lambda: _active(owner) == 0)
    assert "must not execute" not in provider_calls
    assert len(entered) == 2
    assert all(options["max_retries"] == 0 and options["timeout"] > 0 for options in client_options)
