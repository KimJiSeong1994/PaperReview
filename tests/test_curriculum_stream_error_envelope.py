"""Regression tests for curriculum generation SSE terminal-event guarantee.

These tests lock in the contract that the ``POST /api/curricula/generate-stream``
endpoint ALWAYS emits a terminal SSE event (``{"done": True, ...}`` or
``{"error": ...}``) before the stream closes. Previously, a crash inside the
pipeline or a falsy-curriculum "done" signal could end the stream silently,
leading the FE to surface the cryptic "스트림이 중단되었습니다" error to users.
"""

import json
from typing import AsyncGenerator
from unittest.mock import patch

import pytest


def _parse_sse_events(body: str) -> list[dict]:
    """Parse an SSE response body into a list of JSON data payloads.

    Ignores comment/keepalive lines (those starting with ``:``) and any
    non-data lines, matching the FE parser at web-ui/src/api/curriculum.ts.
    """
    events: list[dict] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[len("data: "):]))
            except json.JSONDecodeError:
                # Malformed lines are ignored (consistent with FE behavior)
                continue
    return events


class _FakePipeline:
    """Test double that replays a scripted sequence of events or raises."""

    def __init__(self, events=None, raise_after=None):
        self._events = events or []
        self._raise_after = raise_after  # yield N events, then raise RuntimeError

    def __call__(self, *_args, **_kwargs):
        # Mimic the real CurriculumPipeline(client) -> instance with .generate()
        return self

    async def generate(self, **_kwargs) -> AsyncGenerator[dict, None]:
        for i, event in enumerate(self._events):
            if self._raise_after is not None and i == self._raise_after:
                raise RuntimeError("simulated mid-stream pipeline crash")
            yield event
        if self._raise_after is not None and self._raise_after >= len(self._events):
            raise RuntimeError("simulated post-stream pipeline crash")


@pytest.mark.asyncio
async def test_stream_emits_error_envelope_on_midstream_exception(client, auth_headers):
    """When the pipeline raises mid-stream, the SSE stream MUST end with a
    ``data: {"error": ...}`` envelope — never close silently.
    """
    fake = _FakePipeline(
        events=[
            {"step": 1, "step_name": "structure", "progress": 0, "message": "starting"},
            {"step": 1, "step_name": "structure", "progress": 100, "message": "done s1"},
        ],
        raise_after=2,
    )

    with patch(
        "routers.curriculum_pipeline.CurriculumPipeline",
        new=lambda _client: fake,
    ):
        resp = await client.post(
            "/api/curricula/generate-stream",
            headers=auth_headers,
            json={
                "topic": "test topic",
                "difficulty": "intermediate",
                "num_modules": 5,
            },
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(resp.text)
    assert events, f"Expected at least one SSE event; got body: {resp.text!r}"

    terminal = events[-1]
    assert "error" in terminal, (
        f"Stream ended WITHOUT an error envelope after a mid-stream crash. "
        f"Last event: {terminal!r}. This is the regression that surfaces "
        f"'스트림이 중단되었습니다' to end users."
    )
    assert "Pipeline error" in terminal["error"]


@pytest.mark.asyncio
async def test_stream_emits_error_on_done_without_curriculum(client, auth_headers):
    """If the pipeline signals done with a falsy curriculum, the stream MUST
    surface an explicit error instead of closing silently on the branch that
    falls through validation.
    """
    fake = _FakePipeline(events=[
        {"step": 1, "step_name": "structure", "progress": 100, "message": "ok"},
        {"done": True, "curriculum": None},
    ])

    with patch(
        "routers.curriculum_pipeline.CurriculumPipeline",
        new=lambda _client: fake,
    ):
        resp = await client.post(
            "/api/curricula/generate-stream",
            headers=auth_headers,
            json={
                "topic": "test topic",
                "difficulty": "intermediate",
                "num_modules": 5,
            },
        )

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    terminal = events[-1]
    # Must be a terminal envelope — either success (won't be, curriculum is
    # None) or an explicit error. Never an intermediate progress event.
    assert "error" in terminal or terminal.get("done") is True, (
        f"Last event must be terminal ({{'error':...}} or {{'done':True,...}}). "
        f"Got: {terminal!r}"
    )
    assert "error" in terminal, (
        f"Empty curriculum should surface as an error, not a silent close. "
        f"Got: {terminal!r}"
    )


@pytest.mark.asyncio
async def test_stream_forwards_pipeline_internal_error_as_terminal(client, auth_headers):
    """The pipeline's own step-level error event (yielded before an internal
    ``return``) must be forwarded and treated as terminal by the endpoint.
    """
    fake = _FakePipeline(events=[
        {"step": 1, "step_name": "structure", "progress": 0, "message": "starting"},
        {"error": "Structure generation failed: mock failure", "step": 1},
    ])

    with patch(
        "routers.curriculum_pipeline.CurriculumPipeline",
        new=lambda _client: fake,
    ):
        resp = await client.post(
            "/api/curricula/generate-stream",
            headers=auth_headers,
            json={
                "topic": "test topic",
                "difficulty": "intermediate",
                "num_modules": 5,
            },
        )

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    terminal = events[-1]
    assert "error" in terminal, f"Expected terminal error envelope; got: {terminal!r}"
    assert "Structure generation failed" in terminal["error"]
