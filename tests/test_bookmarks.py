"""Tests for bookmark CRUD endpoints."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_bookmarks_file(tmp_path):
    """Use a temp file for bookmarks during tests."""
    bf = tmp_path / "bookmarks.json"
    bf.write_text(json.dumps({"bookmarks": []}))
    with patch("routers.deps.BOOKMARKS_FILE", bf):
        # Also patch the lock to use the temp path
        from filelock import FileLock
        with patch("routers.deps._bookmarks_lock", FileLock(str(bf) + ".lock")):
            yield bf


@pytest.mark.asyncio
async def test_list_bookmarks_empty(client):
    """GET /api/bookmarks returns empty list initially."""
    resp = await client.get("/api/bookmarks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["bookmarks"] == []


@pytest.mark.asyncio
async def test_create_and_get_bookmark(client):
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
    resp = await client.post("/api/bookmarks", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test Bookmark"
    assert data["topic"] == "AI"
    bookmark_id = data["id"]

    # Get bookmark detail
    resp2 = await client.get(f"/api/bookmarks/{bookmark_id}")
    assert resp2.status_code == 200
    detail = resp2.json()
    assert detail["report_markdown"] == "# Test Report\nSome content."


@pytest.mark.asyncio
async def test_delete_bookmark(client):
    """DELETE /api/bookmarks/{id} removes a bookmark."""
    # Create
    resp = await client.post("/api/bookmarks", json={
        "session_id": "s1",
        "title": "To Delete",
        "report_markdown": "content",
    })
    bookmark_id = resp.json()["id"]

    # Delete
    resp2 = await client.delete(f"/api/bookmarks/{bookmark_id}")
    assert resp2.status_code == 200

    # Verify gone
    resp3 = await client.get(f"/api/bookmarks/{bookmark_id}")
    assert resp3.status_code == 404


@pytest.mark.asyncio
async def test_update_bookmark_topic(client):
    """PATCH /api/bookmarks/{id}/topic updates topic."""
    resp = await client.post("/api/bookmarks", json={
        "session_id": "s2",
        "title": "Topic Test",
        "report_markdown": "content",
    })
    bookmark_id = resp.json()["id"]

    resp2 = await client.patch(
        f"/api/bookmarks/{bookmark_id}/topic",
        json={"topic": "New Topic"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["topic"] == "New Topic"


@pytest.mark.asyncio
async def test_bookmark_not_found(client):
    """Operations on non-existent bookmark return 404."""
    resp = await client.get("/api/bookmarks/nonexistent")
    assert resp.status_code == 404

    resp2 = await client.delete("/api/bookmarks/nonexistent")
    assert resp2.status_code == 404
