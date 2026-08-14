"""Regression tests for /api/deep-search-stream SSE behavior.

These tests lock in the endpoint contract, the emitted progress order, and the
terminal envelope so the UI does not regress to a silent-close failure mode.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _parse_sse(body: str) -> list[dict[str, Any]]:
    """Parse SSE text into ``{"event": ..., "data": ...}`` records."""
    events: list[dict[str, Any]] = []
    current_event: str | None = None
    current_data: list[str] = []

    def _flush() -> None:
        nonlocal current_event, current_data
        if current_event is None:
            return
        payload: Any = None
        data_text = "\n".join(current_data).strip()
        if data_text:
            payload = json.loads(data_text)
        events.append({"event": current_event, "data": payload})
        current_event = None
        current_data = []

    for line in body.splitlines():
        if not line:
            _flush()
            continue
        if line.startswith("event: "):
            current_event = line[len("event: ") :]
            continue
        if line.startswith("data: "):
            current_data.append(line[len("data: ") :])

    _flush()
    return events


def _make_query_analyzer_mock() -> MagicMock:
    mock = MagicMock()
    mock.analyze_query.return_value = {
        "intent": "paper_search",
        "keywords": ["transformer"],
        "confidence": 0.9,
    }
    mock.classify_difficulty.return_value = "medium"
    return mock


def _make_search_agent_mock() -> MagicMock:
    mock = MagicMock()
    mock.save_papers.return_value = {"new_papers": 1, "duplicates": 0}
    # Deep search deduplicates through the agent. A bare MagicMock would return
    # a mock whose len() is 0 and which iterates empty, silently emptying the
    # result set — so the mock has to behave like the real collaborator here.
    mock.deduplicator.deduplicate.side_effect = lambda papers, **_kw: list(papers)
    return mock


@pytest.fixture(autouse=True)
def _patch_search_deps():
    with (
        patch("routers.search.query_analyzer", _make_query_analyzer_mock()),
        patch("routers.search.search_agent", _make_search_agent_mock()),
        patch("routers.search.get_openai_client", return_value=None),
    ):
        yield


def _deep_search_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "query": "transformer retrieval",
        "max_results": 5,
        "context": "",
        "save_papers": False,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_deep_search_stream_smoke(client: Any) -> None:
    """The stream endpoint must return SSE with the expected buffering headers."""
    fake_react_result = {
        "papers": [],
        "metadata": {"turns_used": 1, "turns_history": []},
    }

    with (
        patch(
            "app.SearchAgent.react_search_agent.ReActSearchAgent.search",
            new=AsyncMock(return_value=fake_react_result),
        ),
        patch(
            "app.QueryAgent.rubric_evaluator.RubricEvaluator.evaluate",
            new=AsyncMock(
                return_value={
                    "overall_score": 0.8,
                    "diversity": 3,
                    "thoroughness": 3,
                    "thoughtfulness": 3,
                    "relevance": 3,
                }
            ),
        ),
    ):
        resp = await client.post("/api/deep-search-stream", json=_deep_search_payload())

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["connection"] == "keep-alive"
    assert resp.headers["x-accel-buffering"] == "no"


@pytest.mark.asyncio
async def test_deep_search_stream_emits_expected_event_order(client: Any) -> None:
    """The stream must emit the expected progress events in order."""
    fake_react_result = {
        "papers": [{"title": "Paper A", "abstract": "A"}],
        "metadata": {
            "turns_used": 2,
            "turns_history": [{"turn": 1, "gaps": ["coverage gap"]}],
        },
    }

    with (
        patch(
            "app.SearchAgent.react_search_agent.ReActSearchAgent.search",
            new=AsyncMock(return_value=fake_react_result),
        ),
        patch(
            "app.QueryAgent.rubric_evaluator.RubricEvaluator.evaluate",
            new=AsyncMock(
                return_value={
                    "overall_score": 0.8,
                    "diversity": 3,
                    "thoroughness": 3,
                    "thoughtfulness": 3,
                    "relevance": 3,
                }
            ),
        ),
    ):
        resp = await client.post("/api/deep-search-stream", json=_deep_search_payload())

    events = _parse_sse(resp.text)
    names = [evt["event"] for evt in events]
    assert names == [
        "turn_start",
        "query_analysis",
        "turn_start",
        "papers_found",
        "gap_analysis",
        "turn_start",
        "evaluation",
        "complete",
    ], f"unexpected SSE event order: {names!r}"

    assert events[0]["data"] == {"turn": 0, "phase": "query_analysis"}
    assert events[1]["data"]["intent"] == "paper_search"
    assert events[2]["data"]["phase"] == "search"
    assert events[5]["data"] == {"turn": 3, "phase": "evaluation"}
    assert events[-1]["event"] == "complete"
    assert events[-1]["data"]["total"] == 1
    assert events[-1]["data"]["papers"][0]["title"] == "Paper A"


@pytest.mark.asyncio
async def test_deep_search_stream_ends_with_error_on_failure(client: Any) -> None:
    """A midstream failure must end with a terminal error envelope."""
    with (
        patch(
            "app.SearchAgent.react_search_agent.ReActSearchAgent.search",
            new=AsyncMock(side_effect=RuntimeError("simulated deep search failure")),
        ),
        patch(
            "app.QueryAgent.rubric_evaluator.RubricEvaluator.evaluate",
            new=AsyncMock(return_value={}),
        ),
    ):
        resp = await client.post("/api/deep-search-stream", json=_deep_search_payload())

    events = _parse_sse(resp.text)
    assert events, f"expected SSE events, got body: {resp.text!r}"
    assert events[-1]["event"] == "error", f"expected terminal error event, got {events[-1]!r}"
    assert "simulated deep search failure" in events[-1]["data"]["message"]
