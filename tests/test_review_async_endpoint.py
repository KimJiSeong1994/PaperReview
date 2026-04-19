"""US-008 — async LLM endpoints must not starve the FastAPI threadpool.

Before US-008, ``create_paper_review`` and ``auto_highlight_bookmark`` were
plain ``def`` functions. FastAPI routes sync handlers through a fixed
threadpool (default 40 workers). When 40+ concurrent review requests each
block on a 10-30 s LLM call, the threadpool is fully occupied and other
sync endpoints (pdf-proxy, admin, etc.) queue behind them, effectively
stalling the service.

The conversion to ``async def`` + ``run_in_threadpool(generate_paper_review)``
means each request holds an asyncio slot (cheap, ~1 KB) while the LLM call
rents a threadpool worker only for the duration of the network I/O. Non-LLM
sync endpoints continue to get workers immediately.

These tests guard two invariants:

1. Both endpoints are ``async def`` (structural check via
   :func:`inspect.iscoroutinefunction`).
2. ``create_paper_review`` invokes ``generate_paper_review`` via
   ``run_in_threadpool`` — verified by a spy that confirms the exact call
   site rather than an indirect latency measurement.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from filelock import FileLock
from starlette.concurrency import run_in_threadpool


# ---------------------------------------------------------------------------
# Structural guarantees — endpoints are async
# ---------------------------------------------------------------------------


def test_create_paper_review_is_async():
    """Regression: ``create_paper_review`` must be a coroutine function."""
    from routers.paper_reviews import create_paper_review

    assert inspect.iscoroutinefunction(create_paper_review), (
        "create_paper_review must be async def so the LLM call is offloaded "
        "via run_in_threadpool instead of occupying a threadpool worker for "
        "the whole request lifetime."
    )


def test_auto_highlight_bookmark_is_async():
    """Regression: ``auto_highlight_bookmark`` must be a coroutine function."""
    from routers.bookmarks import auto_highlight_bookmark

    assert inspect.iscoroutinefunction(auto_highlight_bookmark), (
        "auto_highlight_bookmark must be async def so the LLM call is "
        "offloaded via run_in_threadpool and does not starve the threadpool."
    )


# ---------------------------------------------------------------------------
# Spy test — run_in_threadpool is actually called with generate_paper_review
# ---------------------------------------------------------------------------


_BOOKMARK_ID = "bm-async-test-001"
_USERNAME = "test-admin"

_PAPER = {
    "title": "Attention Is All You Need",
    "authors": ["Vaswani et al."],
    "year": "2017",
    "abstract": "We propose a new architecture called the Transformer.",
}

_REVIEW_MOCK = {
    "summary": "Test summary",
    "strengths": [
        {"point": "Good", "evidence": "Section 3.", "significance": "medium"}
    ],
    "weaknesses": [
        {"point": "Limited", "evidence": "Section 4.", "severity": "minor"}
    ],
    "methodology_assessment": {
        "rigor": 4, "novelty": 3, "reproducibility": 3, "commentary": "Solid"
    },
    "key_contributions": ["Novel"],
    "questions_for_authors": ["How?"],
    "overall_score": 7,
    "confidence": 4,
    "detailed_review_markdown": "## Summary\nShort stub review body for async concurrency test.",
    "created_at": "2024-01-01T00:00:00Z",
    "model": "gpt-4.1",
    "input_type": "abstract",
}


@pytest.fixture
def bookmarks_file(tmp_path):
    """Provide a temp bookmarks.json patched into storage for the duration of the test."""
    bf = tmp_path / "bookmarks.json"
    bf.write_text(
        json.dumps(
            {
                "bookmarks": [
                    {
                        "id": _BOOKMARK_ID,
                        "username": _USERNAME,
                        "title": "Async Test Bookmark",
                        "papers": [_PAPER.copy()],
                    }
                ]
            }
        )
    )
    with patch("routers.deps.storage.BOOKMARKS_FILE", bf):
        with patch(
            "routers.deps.storage._bookmarks_lock",
            FileLock(str(bf) + ".lock"),
        ):
            yield bf


@pytest.mark.asyncio
async def test_create_paper_review_uses_run_in_threadpool(
    client, auth_headers, bookmarks_file
):
    """Verify generate_paper_review is invoked via run_in_threadpool (not directly).

    Strategy: replace ``routers.paper_reviews.run_in_threadpool`` with a spy
    that wraps the real implementation.  After one successful POST to the
    review endpoint, we assert that:

    1. The spy was called at least once.
    2. The first positional argument (the callable) is ``generate_paper_review``
       — confirming the LLM call is dispatched through the threadpool rather
       than called synchronously on the event loop.

    This is more reliable than the previous latency-based /health probe
    because it does not depend on threadpool timing or the number of
    concurrent requests; it directly inspects the call site.
    """
    spy_calls: list = []

    async def spy_run_in_threadpool(func, *args, **kwargs):
        spy_calls.append(func)
        return await run_in_threadpool(func, *args, **kwargs)

    with patch(
        "routers.paper_reviews.run_in_threadpool",
        side_effect=spy_run_in_threadpool,
    ), patch(
        "routers.paper_reviews.generate_paper_review",
        return_value=dict(_REVIEW_MOCK),
    ), patch(
        "routers.paper_reviews.generate_highlights",
        return_value=[],
    ), patch(
        "routers.paper_reviews.get_openai_client",
        return_value=MagicMock(),
    ):
        resp = await client.post(
            f"/api/bookmarks/{_BOOKMARK_ID}/papers/0/review",
            json={"review_mode": "fast"},
            headers=auth_headers,
            timeout=15.0,
        )

    assert resp.status_code == 200, f"Unexpected status: {resp.status_code} — {resp.text}"
    assert len(spy_calls) >= 1, "run_in_threadpool was not invoked at all"

    # The first call to run_in_threadpool should be the patched generate_paper_review mock.
    # We check by name (MagicMock carries the patch target name) to confirm the
    # correct callable is being dispatched, not some other function.
    first_fn = spy_calls[0]
    fn_name = getattr(first_fn, "_mock_name", None) or getattr(first_fn, "__name__", repr(first_fn))
    assert "generate_paper_review" in fn_name, (
        f"Expected run_in_threadpool to be called with generate_paper_review "
        f"as first arg, got {first_fn!r} (name={fn_name!r})"
    )
