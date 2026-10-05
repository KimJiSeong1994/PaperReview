from __future__ import annotations

import asyncio
import copy
import threading
import time

import httpx
import pytest

from src.graph_rag import jev_reranker
from src.utils.jev_client import JevError, MODEL, RUBRIC_HASH, RUBRIC_VERSION

_API_KEY = "reranker-test-secret"


def _paper(index: int, **extra):
    return {
        "arxiv_id": f"2401.{index:05d}",
        "title": f"Paper {index}",
        "abstract": f"Evidence for paper {index}.",
        "_hybrid_score": float(100 - index),
        "_score_breakdown": {"bm25": float(index), "semantic": 0.25},
        **extra,
    }


def _score(value: int):
    return {
        "model": MODEL,
        "rubric_version": RUBRIC_VERSION,
        "score": float(value),
        "confidence": 0.8,
        "probabilities": {
            "0": float(value == 0),
            "1": float(value == 1),
            "2": float(value == 2),
            "3": float(value == 3),
        },
        "usage": {"input_tokens": 10, "output_tokens": 2},
        "elapsed_ms": 1,
    }


def _enable_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", _API_KEY)


def test_completed_rerank_preserves_slots_tail_objects_and_hybrid_signals(monkeypatch):
    _enable_key(monkeypatch)
    monkeypatch.setattr(jev_reranker, "_CANDIDATE_CAP", 3)
    first, missing, third, tail = (
        _paper(1),
        _paper(2, abstract=""),
        _paper(3),
        _paper(4),
    )
    papers = [first, missing, third, tail]
    scores = {"arxiv:2401.00001": 0, "arxiv:2401.00003": 3}
    calls = []

    async def score(query, candidate, **kwargs):
        calls.append(candidate["paper_key"])
        return _score(scores[candidate["paper_key"]])

    monkeypatch.setattr(jev_reranker, "async_score_candidate", score)
    result, metadata = asyncio.run(jev_reranker.rerank_papers("query", papers))

    assert metadata == {"mode": "completed", "model": MODEL, "scored_count": 2}
    assert result == [third, missing, first, tail]
    assert result[0] is third and result[2] is first and result[3] is tail
    assert calls == ["arxiv:2401.00001", "arxiv:2401.00003"]
    assert first["_score_breakdown"]["bm25"] == 1.0
    assert first["_score_breakdown"]["semantic"] == 0.25
    assert first["_score_breakdown"]["jev"] == _score(0)
    assert third["_score_breakdown"]["jev"] == _score(3)
    assert "jev" not in missing["_score_breakdown"]
    assert "jev" not in tail["_score_breakdown"]


def test_equal_scores_keep_original_eligible_order(monkeypatch):
    _enable_key(monkeypatch)
    first, second, third = _paper(1), _paper(2), _paper(3)

    async def score(query, candidate, **kwargs):
        return _score(2)

    monkeypatch.setattr(jev_reranker, "async_score_candidate", score)
    result, metadata = asyncio.run(
        jev_reranker.rerank_papers("query", [first, second, third])
    )

    assert result == [first, second, third]
    assert metadata["mode"] == "completed"
    assert metadata["scored_count"] == 3


def test_candidate_cap_and_per_request_concurrency_are_bounded(monkeypatch):
    _enable_key(monkeypatch)
    papers = [_paper(index + 1) for index in range(25)]
    active = 0
    maximum_active = 0
    seen = []

    async def score(query, candidate, **kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        seen.append(candidate["paper_key"])
        try:
            await asyncio.sleep(0.02)
            return _score(1)
        finally:
            active -= 1

    monkeypatch.setattr(jev_reranker, "async_score_candidate", score)
    result, metadata = asyncio.run(jev_reranker.rerank_papers("query", papers))

    assert metadata["mode"] == "completed"
    assert metadata["scored_count"] == 20
    assert len(seen) == 20
    assert set(seen) == {f"arxiv:2401.{index:05d}" for index in range(1, 21)}
    assert maximum_active == 8
    assert result[20:] == papers[20:]
    assert all(result[index] is papers[index] for index in range(20))
    assert all("jev" not in paper["_score_breakdown"] for paper in papers[20:])


def test_no_api_key_disables_without_scoring_and_cache_variant_exposes_presence_only(
    monkeypatch,
):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    papers = [_paper(1), _paper(2)]

    async def unexpected_score(*args, **kwargs):
        raise AssertionError("must not score without a key")

    monkeypatch.setattr(jev_reranker, "async_score_candidate", unexpected_score)
    result, metadata = asyncio.run(jev_reranker.rerank_papers("query", papers))
    absent_variant = jev_reranker.ranking_cache_variant()

    assert result[0] is papers[0] and result[1] is papers[1]
    assert metadata == {
        "mode": "disabled_no_api_key",
        "model": MODEL,
        "scored_count": 0,
    }
    assert "key-absent" in absent_variant

    monkeypatch.setenv("TYPESAFE_API_KEY", _API_KEY)
    present_variant = jev_reranker.ranking_cache_variant()
    assert "key-present" in present_variant
    assert "candidate-cap=20" in present_variant
    assert "jev-head20-v1" in present_variant
    assert MODEL in present_variant and RUBRIC_HASH in present_variant
    assert _API_KEY not in present_variant
    assert absent_variant != present_variant


def test_oversized_or_missing_evidence_is_skipped_not_truncated(monkeypatch):
    _enable_key(monkeypatch)
    papers = [
        _paper(1),
        _paper(2, title="x" * 1_001),
        _paper(3, abstract="y" * 12_001),
        _paper(4),
    ]
    sent = []

    async def score(query, candidate, **kwargs):
        sent.append(candidate)
        return _score(1)

    monkeypatch.setattr(jev_reranker, "async_score_candidate", score)
    result, metadata = asyncio.run(jev_reranker.rerank_papers("q" * 2_001, papers))

    assert metadata["mode"] == "skipped_insufficient_evidence"
    assert metadata["scored_count"] == 0
    assert result == papers
    assert not sent

    result, metadata = asyncio.run(jev_reranker.rerank_papers("query", papers))
    assert metadata["mode"] == "completed"
    assert metadata["scored_count"] == 2
    assert result[1] is papers[1] and result[2] is papers[2]
    assert [item["title"] for item in sent] == ["Paper 1", "Paper 4"]


def test_fewer_than_two_eligible_candidates_are_skipped(monkeypatch):
    _enable_key(monkeypatch)
    papers = [_paper(1), _paper(2, abstract="")]

    async def unexpected_score(*args, **kwargs):
        raise AssertionError("insufficient evidence must not be scored")

    monkeypatch.setattr(jev_reranker, "async_score_candidate", unexpected_score)
    result, metadata = asyncio.run(jev_reranker.rerank_papers("query", papers))

    assert metadata["mode"] == "skipped_insufficient_evidence"
    assert metadata["scored_count"] == 0
    assert result[0] is papers[0] and result[1] is papers[1]


@pytest.mark.parametrize(
    ("failure", "expected_mode"),
    [
        ("provider", "fallback_error"),
        ("invalid", "fallback_error"),
        ("timeout", "fallback_timeout"),
    ],
)
def test_scoring_failures_are_atomic_and_leave_input_unchanged(
    monkeypatch, failure, expected_mode
):
    _enable_key(monkeypatch)
    papers = [_paper(1), _paper(2), _paper(3)]
    before = copy.deepcopy(papers)

    async def score(query, candidate, **kwargs):
        if failure == "provider":
            raise RuntimeError("provider failure must not leak")
        if failure == "timeout":
            raise JevError("TypeSafe request timed out")
        result = _score(2)
        result["score"] = 99
        return result

    monkeypatch.setattr(jev_reranker, "async_score_candidate", score)
    result, metadata = asyncio.run(jev_reranker.rerank_papers("query", papers))

    assert metadata == {
        "mode": expected_mode,
        "model": MODEL,
        "scored_count": 0,
    }
    assert all(
        actual is expected for actual, expected in zip(result, papers, strict=True)
    )
    assert papers == before
    assert all("jev" not in paper["_score_breakdown"] for paper in papers)


def test_wall_timeout_cancels_and_awaits_requests_and_closes_client(monkeypatch):
    _enable_key(monkeypatch)
    papers = [_paper(1), _paper(2)]
    before = copy.deepcopy(papers)
    started = asyncio.Event()
    cleaned = 0
    real_async_client = httpx.AsyncClient
    clients = []

    def tracked_client(*args, **kwargs):
        client = real_async_client(*args, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(jev_reranker.httpx, "AsyncClient", tracked_client)

    async def score(query, candidate, **kwargs):
        nonlocal cleaned
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned += 1

    monkeypatch.setattr(jev_reranker, "async_score_candidate", score)

    async def run():
        result_task = asyncio.create_task(
            jev_reranker.rerank_papers(
                "query", papers, deadline=time.monotonic() + 0.04
            )
        )
        await started.wait()
        return await result_task

    result, metadata = asyncio.run(run())

    assert metadata["mode"] == "fallback_timeout"
    assert metadata["scored_count"] == 0
    assert cleaned == 2
    assert clients and all(client.is_closed for client in clients)
    assert papers == before
    assert all(
        actual is expected for actual, expected in zip(result, papers, strict=True)
    )


def test_stop_event_cancels_in_flight_requests(monkeypatch):
    _enable_key(monkeypatch)
    papers = [_paper(1), _paper(2)]
    before = copy.deepcopy(papers)
    stop_event = threading.Event()
    started = asyncio.Event()
    cleaned = 0

    async def score(query, candidate, **kwargs):
        nonlocal cleaned
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned += 1

    monkeypatch.setattr(jev_reranker, "async_score_candidate", score)

    async def run():
        result_task = asyncio.create_task(
            jev_reranker.rerank_papers("query", papers, stop_event=stop_event)
        )
        await started.wait()
        stop_event.set()
        return await result_task

    result, metadata = asyncio.run(run())

    assert metadata["mode"] == "cancelled"
    assert metadata["scored_count"] == 0
    assert cleaned == 2
    assert papers == before
    assert all(
        actual is expected for actual, expected in zip(result, papers, strict=True)
    )


def test_external_cancellation_propagates_after_cleanup_and_client_close(monkeypatch):
    _enable_key(monkeypatch)
    papers = [_paper(1), _paper(2)]
    before = copy.deepcopy(papers)
    started = asyncio.Event()
    cleaned = 0
    real_async_client = httpx.AsyncClient
    clients = []

    def tracked_client(*args, **kwargs):
        client = real_async_client(*args, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(jev_reranker.httpx, "AsyncClient", tracked_client)

    async def score(query, candidate, **kwargs):
        nonlocal cleaned
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned += 1

    monkeypatch.setattr(jev_reranker, "async_score_candidate", score)

    async def run():
        task = asyncio.create_task(jev_reranker.rerank_papers("query", papers))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert cleaned == 2
    assert clients and all(client.is_closed for client in clients)
    assert papers == before


def test_stop_already_set_returns_cancelled_without_starting_client(monkeypatch):
    _enable_key(monkeypatch)
    stop_event = threading.Event()
    stop_event.set()
    papers = [_paper(1), _paper(2)]

    async def unexpected_score(*args, **kwargs):
        raise AssertionError("a stopped request must not score")

    monkeypatch.setattr(jev_reranker, "async_score_candidate", unexpected_score)
    result, metadata = asyncio.run(
        jev_reranker.rerank_papers("query", papers, stop_event=stop_event)
    )

    assert metadata["mode"] == "cancelled"
    assert result[0] is papers[0] and result[1] is papers[1]


@pytest.mark.parametrize("reason", ["stop", "deadline"])
def test_worker_rechecks_admission_after_waiting_for_semaphore(monkeypatch, reason):
    queued = asyncio.Event()
    release = asyncio.Event()
    stop_event = threading.Event()
    expires_at = time.monotonic() + (1 if reason == "stop" else 0.01)
    sent = False

    class GateSemaphore:
        async def __aenter__(self):
            queued.set()
            await release.wait()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    async def score(*args, **kwargs):
        nonlocal sent
        sent = True
        return _score(1)

    async def run():
        task = asyncio.create_task(
            jev_reranker._score_one(
                GateSemaphore(),
                object(),
                "query",
                {"paper_key": "arxiv:2401.00001", "title": "t", "abstract": "a"},
                _API_KEY,
                expires_at,
                stop_event if reason == "stop" else None,
            )
        )
        await queued.wait()
        if reason == "stop":
            stop_event.set()
            expected_error = jev_reranker._StopRequested
        else:
            await asyncio.sleep(0.02)
            expected_error = jev_reranker._DeadlineExpired
        release.set()
        with pytest.raises(expected_error):
            await task

    monkeypatch.setattr(jev_reranker, "async_score_candidate", score)
    asyncio.run(run())

    assert not sent


def test_stop_after_client_cleanup_prevents_late_score_commit(monkeypatch):
    _enable_key(monkeypatch)
    stop_event = threading.Event()
    papers = [_paper(1), _paper(2)]
    before = copy.deepcopy(papers)
    client_state = {"closed": False}

    class ClosingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            client_state["closed"] = True
            stop_event.set()

    monkeypatch.setattr(
        jev_reranker.httpx, "AsyncClient", lambda **kwargs: ClosingClient()
    )

    async def score(query, candidate, **kwargs):
        return _score(3)

    monkeypatch.setattr(jev_reranker, "async_score_candidate", score)
    result, metadata = asyncio.run(
        jev_reranker.rerank_papers("query", papers, stop_event=stop_event)
    )

    assert metadata["mode"] == "cancelled"
    assert metadata["scored_count"] == 0
    assert client_state["closed"]
    assert papers == before
    assert all(
        actual is expected for actual, expected in zip(result, papers, strict=True)
    )
