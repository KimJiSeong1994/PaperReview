"""Tests for QUERY_SUBMIT / SEARCH_CLICK event emission from search endpoints.

US-014: /api/search must emit QUERY_SUBMIT; /api/search/click must emit SEARCH_CLICK.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Shared mock return values (reuse pattern from test_search.py)
# ---------------------------------------------------------------------------

_SEARCH_AGENT_RESULTS: dict[str, Any] = {
    "arxiv": [
        {
            "title": "A Survey on Machine Learning",
            "authors": ["Author A"],
            "abstract": "This paper surveys...",
            "year": "2024",
            "url": "https://arxiv.org/abs/2401.00001",
            "source": "arxiv",
        }
    ]
}


def _make_query_analyzer_mock() -> MagicMock:
    mock = MagicMock()
    mock.analyze_and_prepare.return_value = {
        "intent": "paper_search",
        "keywords": ["transformer"],
        "improved_query": "transformer survey",
        "search_filters": {},
        "confidence": 0.9,
        "original_query": "transformer",
        "is_academic": True,
        "source_queries": {
            "arxiv": "transformer",
            "dblp": "transformer",
            "google_scholar": "transformer",
            "default": "transformer",
        },
    }
    return mock


def _make_search_agent_mock() -> MagicMock:
    mock = MagicMock()

    async def _async_search(query, filters):  # noqa: ANN001
        return {k: list(v) for k, v in _SEARCH_AGENT_RESULTS.items()}

    mock.async_search_with_filters.side_effect = _async_search
    mock.deduplicator = MagicMock()
    mock.deduplicator.deduplicate.side_effect = lambda papers: papers
    mock.save_papers.return_value = {"new_papers": 1, "duplicates": 0}
    mock.similarity_calculator = MagicMock()
    return mock


@pytest.fixture(autouse=True)
def _patch_search_deps():
    """Patch module-level singletons and suppress cache/disk I/O."""
    with (
        patch("routers.search.query_analyzer", _make_query_analyzer_mock()),
        patch("routers.search.search_agent", _make_search_agent_mock()),
        patch("routers.search.relevance_filter", None),
        patch("routers.search._hybrid_ranker", None),
        patch("routers.search._set_cache", return_value=None),
        patch("routers.search._get_cached_result", return_value=None),
        patch("routers.search.json.dump", return_value=None),
        patch("routers.search.Path.mkdir", return_value=None),
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _expected_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# QUERY_SUBMIT tests
# ---------------------------------------------------------------------------


class TestQuerySubmitEvent:
    """POST /api/search emits QUERY_SUBMIT on success."""

    @pytest.mark.asyncio
    async def test_search_emits_query_submit(self, client: Any, auth_headers: dict) -> None:
        """Authenticated search emits exactly one QUERY_SUBMIT with correct payload."""
        captured: list[Any] = []

        def _capture(event: Any) -> None:
            captured.append(event)

        with patch("routers.search.emit_or_warn", side_effect=_capture):
            resp = await client.post(
                "/api/search",
                json={"query": "transformer", "fast_mode": True, "save_papers": False},
                headers=auth_headers,
            )

        assert resp.status_code == 200, resp.text

        query_submit_events = [
            e for e in captured
            if hasattr(e, "event_type") and e.event_type.value == "query_submit"
        ]
        assert len(query_submit_events) == 1, (
            f"expected 1 query_submit event, got {len(query_submit_events)}; "
            f"all captured: {captured}"
        )

        evt = query_submit_events[0]
        payload = evt.payload

        # Privacy: raw query must not be stored
        assert "transformer" not in str(payload), "raw query must not appear in payload"

        # query_hash must match sha256 prefix
        assert payload["query_hash"] == _expected_hash("transformer")

        # Structural fields
        assert "results_count" in payload
        assert isinstance(payload["results_count"], int)
        assert "ranking_applied" in payload
        assert "elapsed_ms" in payload

    @pytest.mark.asyncio
    async def test_search_no_emit_when_unauthenticated(self, client: Any) -> None:
        """Unauthenticated search (no Authorization header) must NOT emit QUERY_SUBMIT."""
        captured: list[Any] = []

        with patch("routers.search.emit_or_warn", side_effect=lambda e: captured.append(e)):
            resp = await client.post(
                "/api/search",
                json={"query": "transformer", "fast_mode": True, "save_papers": False},
            )

        assert resp.status_code == 200, resp.text
        query_submit_events = [
            e for e in captured
            if hasattr(e, "event_type") and e.event_type.value == "query_submit"
        ]
        assert query_submit_events == [], (
            "unauthenticated search should not emit query_submit events"
        )

    @pytest.mark.asyncio
    async def test_emit_failure_does_not_block_response(
        self, client: Any, auth_headers: dict
    ) -> None:
        """If emit_or_warn raises, the search response must still return 200."""
        with patch("routers.search.emit_or_warn", side_effect=RuntimeError("bus down")):
            resp = await client.post(
                "/api/search",
                json={"query": "transformer", "fast_mode": True, "save_papers": False},
                headers=auth_headers,
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] >= 1


# ---------------------------------------------------------------------------
# SEARCH_CLICK tests
# ---------------------------------------------------------------------------


class TestSearchClickEndpoint:
    """POST /api/search/click emits SEARCH_CLICK."""

    @pytest.mark.asyncio
    async def test_click_emits_event(self, client: Any, auth_headers: dict) -> None:
        """Authenticated click emits SEARCH_CLICK with query_hash and paper_id."""
        captured: list[Any] = []

        with patch("routers.search.emit_or_warn", side_effect=lambda e: captured.append(e)):
            resp = await client.post(
                "/api/search/click",
                json={"query_hash": "abc123def456", "paper_id": "arxiv:2401.00001"},
                headers=auth_headers,
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["tracked"] is True

        click_events = [
            e for e in captured
            if hasattr(e, "event_type") and e.event_type.value == "search_click"
        ]
        assert len(click_events) == 1
        evt = click_events[0]
        assert evt.payload["query_hash"] == "abc123def456"
        assert evt.payload["paper_id"] == "arxiv:2401.00001"
        assert evt.paper_id == "arxiv:2401.00001"

    @pytest.mark.asyncio
    async def test_click_no_emit_when_unauthenticated(self, client: Any) -> None:
        """Unauthenticated click returns tracked=False and does not emit."""
        captured: list[Any] = []

        with patch("routers.search.emit_or_warn", side_effect=lambda e: captured.append(e)):
            resp = await client.post(
                "/api/search/click",
                json={"query_hash": "abc123def456", "paper_id": "arxiv:2401.00001"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["tracked"] is False
        assert captured == []

    @pytest.mark.asyncio
    async def test_click_missing_fields_returns_not_tracked(
        self, client: Any, auth_headers: dict
    ) -> None:
        """Click with empty query_hash or paper_id returns tracked=False."""
        resp = await client.post(
            "/api/search/click",
            json={"query_hash": "", "paper_id": "arxiv:2401.00001"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["tracked"] is False
