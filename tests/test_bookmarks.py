"""Tests for bookmark CRUD endpoints."""

import json
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_bookmarks_file(tmp_path):
    """Use a temp file for bookmarks during tests."""
    bf = tmp_path / "bookmarks.json"
    bf.write_text(json.dumps({"bookmarks": []}))
    from filelock import FileLock
    with patch("routers.deps.storage.BOOKMARKS_FILE", bf), \
         patch("routers.deps.storage._bookmarks_lock", FileLock(str(bf) + ".lock")):
        yield bf


@pytest.mark.asyncio
async def test_list_bookmarks_empty(client, auth_headers):
    """GET /api/bookmarks returns empty list initially."""
    resp = await client.get("/api/bookmarks", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["bookmarks"] == []


@pytest.mark.asyncio
async def test_create_and_get_bookmark(client, auth_headers):
    """POST /api/bookmarks creates a bookmark, GET retrieves it."""
    payload = {
        "session_id": "test-session-001",
        "title": "Test Bookmark",
        "query": "machine learning",
        "papers": [{"title": "Paper A"}],
        "report_markdown": "# Test Report\nSome content.",
        "tags": ["ml", "test"],
        "topic": "AI",
    }
    resp = await client.post("/api/bookmarks", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test Bookmark"
    assert data["topic"] == "AI"
    bookmark_id = data["id"]

    # Get bookmark detail
    resp2 = await client.get(f"/api/bookmarks/{bookmark_id}", headers=auth_headers)
    assert resp2.status_code == 200
    detail = resp2.json()
    assert detail["report_markdown"] == "# Test Report\nSome content."


@pytest.mark.asyncio
async def test_delete_bookmark(client, auth_headers):
    """DELETE /api/bookmarks/{id} removes a bookmark."""
    # Create
    resp = await client.post("/api/bookmarks", json={
        "session_id": "s1",
        "title": "To Delete",
        "report_markdown": "content",
    }, headers=auth_headers)
    bookmark_id = resp.json()["id"]

    # Delete
    resp2 = await client.delete(f"/api/bookmarks/{bookmark_id}", headers=auth_headers)
    assert resp2.status_code == 200

    # Verify gone
    resp3 = await client.get(f"/api/bookmarks/{bookmark_id}", headers=auth_headers)
    assert resp3.status_code == 404


@pytest.mark.asyncio
async def test_update_bookmark_topic(client, auth_headers):
    """PATCH /api/bookmarks/{id}/topic updates topic."""
    resp = await client.post("/api/bookmarks", json={
        "session_id": "s2",
        "title": "Topic Test",
        "report_markdown": "content",
    }, headers=auth_headers)
    bookmark_id = resp.json()["id"]

    resp2 = await client.patch(
        f"/api/bookmarks/{bookmark_id}/topic",
        json={"topic": "New Topic"},
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["topic"] == "New Topic"


@pytest.mark.asyncio
async def test_bookmark_not_found(client, auth_headers):
    """Operations on non-existent bookmark return 404."""
    resp = await client.get("/api/bookmarks/nonexistent", headers=auth_headers)
    assert resp.status_code == 404

    resp2 = await client.delete("/api/bookmarks/nonexistent", headers=auth_headers)
    assert resp2.status_code == 404


# ── RT2: POST /api/bookmarks must be rate-limited ─────────────────────

@pytest.mark.asyncio
async def test_bookmarks_post_rate_limited(client, auth_headers):
    """POST /api/bookmarks must honour the 30/minute cap (B10)."""
    from routers.deps import limiter as real_limiter

    # Reset counters from prior tests.
    real_limiter._storage.reset()

    payload = {
        "session_id": "s-rl",
        "title": "rl",
        "papers": [],
        "report_markdown": "x",
        "topic": "T",
    }

    last_status = None
    for i in range(31):
        resp = await client.post("/api/bookmarks", json=payload, headers=auth_headers)
        last_status = resp.status_code
        if resp.status_code == 429:
            break

    assert last_status == 429, (
        f"Expected 429 within 31 requests to /api/bookmarks, last status was {last_status}"
    )


# ── RT4: body-size cap rejects oversized report_markdown ───────────────

@pytest.mark.asyncio
async def test_body_size_cap_rejects_large_report(client, auth_headers):
    """POST /api/bookmarks with a 1 MB report must be rejected by Pydantic.

    Cap is 512 KB — 1 MB is definitively over.
    """
    from routers.deps import limiter as real_limiter

    real_limiter._storage.reset()

    big_report = "x" * (1024 * 1024)  # 1 MB — exceeds 512 KB cap
    payload = {
        "session_id": "s-big",
        "title": "big",
        "papers": [],
        "report_markdown": big_report,
        "topic": "T",
    }

    resp = await client.post("/api/bookmarks", json=payload, headers=auth_headers)

    # FastAPI / Pydantic → 422 for validation failure (413 also acceptable
    # if a reverse proxy enforces the cap).
    assert resp.status_code in (413, 422), (
        f"Expected 413 or 422 for 1MB body, got {resp.status_code}: {resp.text[:200]}"
    )
