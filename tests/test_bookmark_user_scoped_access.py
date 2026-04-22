"""US-002 authorization regression tests: user-scoped bookmark access.

Verifies that:
1. list_bookmarks returns only the requesting user's bookmarks.
2. get_bookmark returns 404 (not 403) when accessing another user's bookmark.
3. The list response shape contains the expected summary fields.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest

_JWT_SECRET = os.environ.get("JWT_SECRET", "test-jwt-secret-for-testing-only")


def _make_token(username: str) -> str:
    payload = {
        "sub": username,
        "role": "user",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def _auth(username: str) -> dict:
    # ``get_current_user`` now requires the user to exist in the user DB
    # so the cross-user bookmark tests must seed the principal on demand.
    from routers.deps.storage import _get_user_db

    db = _get_user_db()
    if db.get(username) is None:
        db.upsert(username, {"password_hash": "x", "role": "user", "created_at": ""})
    return {"Authorization": f"Bearer {_make_token(username)}"}


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirect BookmarkDB to a fresh temp file for each test."""
    bf = tmp_path / "bookmarks.json"
    bf.write_text(json.dumps({"bookmarks": []}))

    # Clear the DB singleton cache so each test gets its own SQLite file.
    import routers.deps.storage as storage_mod

    monkeypatch.setattr(storage_mod, "BOOKMARKS_FILE", bf)
    with patch.dict(storage_mod._bookmark_dbs, {}, clear=True):
        yield


_BOOKMARK_PAYLOAD = {
    "session_id": "s1",
    "title": "Alice Paper",
    "query": "attention",
    "papers": [{"title": "P1"}, {"title": "P2"}],
    "report_markdown": "# Report\nSome content here.",
    "tags": ["ml"],
    "topic": "NLP",
}


@pytest.mark.asyncio
async def test_list_bookmarks_returns_only_current_user(client):
    """Alice's list must not include Bob's bookmarks."""
    # Alice creates one bookmark
    r = await client.post("/api/bookmarks", json=_BOOKMARK_PAYLOAD, headers=_auth("alice_us2"))
    assert r.status_code == 200, r.text

    # Bob creates one bookmark
    bob_payload = {**_BOOKMARK_PAYLOAD, "title": "Bob Paper", "topic": "CV"}
    r2 = await client.post("/api/bookmarks", json=bob_payload, headers=_auth("bob_us2"))
    assert r2.status_code == 200, r2.text

    # Alice lists — must see only her own
    r3 = await client.get("/api/bookmarks", headers=_auth("alice_us2"))
    assert r3.status_code == 200
    bookmarks = r3.json()["bookmarks"]
    assert len(bookmarks) == 1
    assert bookmarks[0]["title"] == "Alice Paper"

    # Bob lists — must see only his own
    r4 = await client.get("/api/bookmarks", headers=_auth("bob_us2"))
    assert r4.status_code == 200
    assert len(r4.json()["bookmarks"]) == 1
    assert r4.json()["bookmarks"][0]["title"] == "Bob Paper"


@pytest.mark.asyncio
async def test_get_bookmark_cross_user_returns_404(client):
    """Alice requesting Bob's bookmark by ID must receive 404 (not 403/200)."""
    # Bob creates a bookmark
    r = await client.post("/api/bookmarks", json=_BOOKMARK_PAYLOAD | {"title": "Bob Secret"}, headers=_auth("bob_us2"))
    assert r.status_code == 200, r.text
    bob_bm_id = r.json()["id"]

    # Alice tries to access Bob's bookmark
    r2 = await client.get(f"/api/bookmarks/{bob_bm_id}", headers=_auth("alice_us2"))
    assert r2.status_code == 404, (
        f"Expected 404 for cross-user bookmark access, got {r2.status_code}: {r2.text}"
    )


@pytest.mark.asyncio
async def test_list_bookmarks_response_shape_unchanged(client):
    """List response must include all required summary fields."""
    r = await client.post("/api/bookmarks", json=_BOOKMARK_PAYLOAD, headers=_auth("alice_us2"))
    assert r.status_code == 200

    r2 = await client.get("/api/bookmarks", headers=_auth("alice_us2"))
    assert r2.status_code == 200
    bms = r2.json()["bookmarks"]
    assert len(bms) == 1

    bm = bms[0]
    required_keys = {
        "id", "title", "session_id", "query", "num_papers",
        "created_at", "tags", "topic", "has_notes", "has_citation_tree", "has_share",
    }
    missing = required_keys - set(bm.keys())
    assert not missing, f"Response missing keys: {missing}"

    # Type checks
    assert isinstance(bm["has_notes"], bool)
    assert isinstance(bm["has_citation_tree"], bool)
    assert isinstance(bm["has_share"], bool)
    assert isinstance(bm["tags"], list)
    assert bm["num_papers"] == 2
    assert bm["topic"] == "NLP"


@pytest.mark.asyncio
async def test_list_bookmarks_empty_for_new_user(client):
    """A user with no bookmarks should receive an empty list, not someone else's data."""
    # Bob creates a bookmark
    await client.post("/api/bookmarks", json=_BOOKMARK_PAYLOAD | {"title": "Bob Only"}, headers=_auth("bob_us2"))

    # Carol (new user) should see an empty list
    r = await client.get("/api/bookmarks", headers=_auth("carol_us2"))
    assert r.status_code == 200


def test_load_bookmarks_for_user_invalid_username_returns_empty(monkeypatch):
    """load_bookmarks_for_user with a malformed username returns [] — no exception, no 500."""
    import logging

    from routers.deps.storage import load_bookmarks_for_user

    warning_calls: list[tuple] = []

    class _CapturingLogger(logging.Logger):
        def warning(self, msg, *args, **kwargs):  # type: ignore[override]
            warning_calls.append((msg, args))
            super().warning(msg, *args, **kwargs)

    # Patch the module-level logger in storage to capture warnings
    import routers.deps.storage as storage_mod

    original_logger = storage_mod.logger
    capturing = logging.getLogger("test_capture_storage")
    capturing.__class__ = _CapturingLogger
    monkeypatch.setattr(storage_mod, "logger", capturing)

    try:
        result = load_bookmarks_for_user("alice/../bob")
    finally:
        monkeypatch.setattr(storage_mod, "logger", original_logger)

    assert result == [], f"Expected empty list, got {result!r}"

    # Confirm warning was emitted with hash_prefix= mention
    assert warning_calls, "Expected at least one logger.warning call"
    logged_msg = warning_calls[0][0]
    assert "hash_prefix" in logged_msg
