"""US-006 regression tests: 403→404 migration for mutating endpoints.

Verifies that cross-user access to mutating endpoints returns 404 (not 403),
preventing bookmark/session ID existence enumeration via status code leakage.

Covers:
- PATCH /api/bookmarks/{id}/topic     (bookmarks.py line ~307)
- PATCH /api/bookmarks/{id}/title     (bookmarks.py line ~326)
- PATCH /api/bookmarks/{id}/notes     (bookmarks.py line ~349)
- POST  /api/bookmarks/{id}/auto-highlight (bookmarks.py line ~426, already safe)
- GET   /api/deep-review/status/{id}  (reviews.py line ~970)
- GET   /api/deep-review/report/{id}  (reviews.py line ~997)
- GET   /api/deep-review/verification/{id} (reviews.py line ~1049)
- POST  /api/deep-review/visualize/{id}    (reviews.py line ~1133)
"""

import json
import os
from datetime import datetime, timedelta, timezone

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
    return {"Authorization": f"Bearer {_make_token(username)}"}


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirect BookmarkDB to a fresh temp file for each test."""
    from unittest.mock import patch

    bf = tmp_path / "bookmarks.json"
    bf.write_text(json.dumps({"bookmarks": []}))

    import routers.deps.storage as storage_mod

    monkeypatch.setattr(storage_mod, "BOOKMARKS_FILE", bf)
    with patch.dict(storage_mod._bookmark_dbs, {}, clear=True):
        yield


_BOOKMARK_PAYLOAD = {
    "session_id": "sess-001",
    "title": "Bob Paper",
    "query": "transformers",
    "papers": [{"title": "P1"}, {"title": "P2"}],
    "report_markdown": "# Report\nContent.",
    "tags": ["nlp"],
    "topic": "NLP",
}


async def _bob_creates_bookmark(client) -> str:
    """Helper: bob creates a bookmark and returns its ID."""
    r = await client.post("/api/bookmarks", json=_BOOKMARK_PAYLOAD, headers=_auth("bob_us6"))
    assert r.status_code == 200, f"Bob bookmark creation failed: {r.text}"
    return r.json()["id"]


# ---------------------------------------------------------------------------
# bookmarks.py — PATCH /topic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_topic_cross_user_returns_404(client):
    """Alice PATCHing bob's bookmark topic must return 404, not 403."""
    bm_id = await _bob_creates_bookmark(client)

    r = await client.patch(
        f"/api/bookmarks/{bm_id}/topic",
        json={"topic": "hacked"},
        headers=_auth("alice_us6"),
    )
    assert r.status_code == 404, (
        f"Expected 404 for cross-user PATCH /topic, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_patch_topic_own_bookmark_still_200(client):
    """Bob PATCHing his own bookmark topic must still return 200."""
    bm_id = await _bob_creates_bookmark(client)

    r = await client.patch(
        f"/api/bookmarks/{bm_id}/topic",
        json={"topic": "Updated Topic"},
        headers=_auth("bob_us6"),
    )
    assert r.status_code == 200, (
        f"Expected 200 for own PATCH /topic, got {r.status_code}: {r.text}"
    )
    assert r.json()["topic"] == "Updated Topic"


# ---------------------------------------------------------------------------
# bookmarks.py — PATCH /title
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_title_cross_user_returns_404(client):
    """Alice PATCHing bob's bookmark title must return 404, not 403."""
    bm_id = await _bob_creates_bookmark(client)

    r = await client.patch(
        f"/api/bookmarks/{bm_id}/title",
        json={"title": "hacked title"},
        headers=_auth("alice_us6"),
    )
    assert r.status_code == 404, (
        f"Expected 404 for cross-user PATCH /title, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_patch_title_own_bookmark_still_200(client):
    """Bob PATCHing his own bookmark title must still return 200."""
    bm_id = await _bob_creates_bookmark(client)

    r = await client.patch(
        f"/api/bookmarks/{bm_id}/title",
        json={"title": "Updated Title"},
        headers=_auth("bob_us6"),
    )
    assert r.status_code == 200, (
        f"Expected 200 for own PATCH /title, got {r.status_code}: {r.text}"
    )
    assert r.json()["title"] == "Updated Title"


# ---------------------------------------------------------------------------
# bookmarks.py — PATCH /notes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_notes_cross_user_returns_404(client):
    """Alice PATCHing bob's bookmark notes must return 404, not 403."""
    bm_id = await _bob_creates_bookmark(client)

    r = await client.patch(
        f"/api/bookmarks/{bm_id}/notes",
        json={"notes": "hacked notes"},
        headers=_auth("alice_us6"),
    )
    assert r.status_code == 404, (
        f"Expected 404 for cross-user PATCH /notes, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_patch_notes_own_bookmark_still_200(client):
    """Bob PATCHing his own bookmark notes must still return 200."""
    bm_id = await _bob_creates_bookmark(client)

    r = await client.patch(
        f"/api/bookmarks/{bm_id}/notes",
        json={"notes": "my research notes"},
        headers=_auth("bob_us6"),
    )
    assert r.status_code == 200, (
        f"Expected 200 for own PATCH /notes, got {r.status_code}: {r.text}"
    )
    assert r.json()["notes"] == "my research notes"


# ---------------------------------------------------------------------------
# reviews.py — deep-review session endpoints (cross-user access)
# These use in-memory review_sessions, not bookmark storage.
# We inject a fake session owned by bob and try to access as alice.
# ---------------------------------------------------------------------------

def _inject_review_session(session_id: str, username: str, tmp_path) -> None:
    """Inject a fake completed review session into the in-memory store."""
    import routers.reviews as reviews_mod

    workspace = tmp_path / "ws"
    reports = workspace / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    report_file = reports / "report.md"
    report_file.write_text("# Test Report\nContent here.")

    verifications = workspace / "verifications"
    verifications.mkdir(parents=True, exist_ok=True)

    with reviews_mod.review_sessions_lock:
        reviews_mod.review_sessions[session_id] = {
            "session_id": session_id,
            "username": username,
            "status": "completed",
            "progress": "100%",
            "report_available": True,
            "error": None,
            "verification_stats": None,
            "workspace_path": str(workspace),
            "num_papers": 2,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def _cleanup_review_session(session_id: str) -> None:
    """Remove injected session from in-memory store."""
    import routers.reviews as reviews_mod

    with reviews_mod.review_sessions_lock:
        reviews_mod.review_sessions.pop(session_id, None)


@pytest.fixture
def bob_review_session(tmp_path):
    """Inject a fake bob-owned review session, clean up after test."""
    sid = "test-session-bob-us6"
    _inject_review_session(sid, "bob_us6", tmp_path)
    yield sid
    _cleanup_review_session(sid)


@pytest.mark.asyncio
async def test_deep_review_status_cross_user_returns_404(client, bob_review_session):
    """Alice accessing bob's deep-review status must return 404, not 403."""
    r = await client.get(
        f"/api/deep-review/status/{bob_review_session}",
        headers=_auth("alice_us6"),
    )
    assert r.status_code == 404, (
        f"Expected 404 for cross-user GET /deep-review/status, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_deep_review_status_own_session_still_200(client, bob_review_session):
    """Bob accessing his own deep-review status must still return 200."""
    r = await client.get(
        f"/api/deep-review/status/{bob_review_session}",
        headers=_auth("bob_us6"),
    )
    assert r.status_code == 200, (
        f"Expected 200 for own GET /deep-review/status, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_deep_review_report_cross_user_returns_404(client, bob_review_session):
    """Alice accessing bob's deep-review report must return 404, not 403."""
    r = await client.get(
        f"/api/deep-review/report/{bob_review_session}",
        headers=_auth("alice_us6"),
    )
    assert r.status_code == 404, (
        f"Expected 404 for cross-user GET /deep-review/report, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_deep_review_report_own_session_still_200(client, bob_review_session):
    """Bob accessing his own deep-review report must still return 200."""
    r = await client.get(
        f"/api/deep-review/report/{bob_review_session}",
        headers=_auth("bob_us6"),
    )
    assert r.status_code == 200, (
        f"Expected 200 for own GET /deep-review/report, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_deep_review_verification_cross_user_returns_404(client, bob_review_session):
    """Alice accessing bob's deep-review verification detail must return 404, not 403."""
    r = await client.get(
        f"/api/deep-review/verification/{bob_review_session}",
        headers=_auth("alice_us6"),
    )
    assert r.status_code == 404, (
        f"Expected 404 for cross-user GET /deep-review/verification, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_deep_review_verification_own_session_still_200(client, bob_review_session):
    """Bob accessing his own deep-review verification detail must still return 200."""
    r = await client.get(
        f"/api/deep-review/verification/{bob_review_session}",
        headers=_auth("bob_us6"),
    )
    assert r.status_code == 200, (
        f"Expected 200 for own GET /deep-review/verification, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_deep_review_visualize_cross_user_returns_404(client, bob_review_session):
    """Alice POSTing to bob's deep-review visualize must return 404, not 403."""
    r = await client.post(
        f"/api/deep-review/visualize/{bob_review_session}",
        headers=_auth("alice_us6"),
    )
    assert r.status_code == 404, (
        f"Expected 404 for cross-user POST /deep-review/visualize, got {r.status_code}: {r.text}"
    )


# ---------------------------------------------------------------------------
# share.py — POST /api/bookmarks/{id}/share (cross-user)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_share_post_cross_user_returns_404(client):
    """Alice attempting POST /bookmarks/{bob_id}/share must return 404, not 403."""
    bm_id = await _bob_creates_bookmark(client)

    r = await client.post(
        f"/api/bookmarks/{bm_id}/share",
        json={"expires_in_days": 7},
        headers=_auth("alice_us6"),
    )
    assert r.status_code == 404, (
        f"Expected 404 for cross-user POST /share, got {r.status_code}: {r.text}"
    )

    # Confirm bob's bookmark has no share link set (alice's attempt must be a no-op)
    r_bob = await client.get(f"/api/bookmarks/{bm_id}", headers=_auth("bob_us6"))
    assert r_bob.status_code == 200
    assert "share" not in r_bob.json(), "Alice's failed share attempt must not mutate bob's bookmark"


# ---------------------------------------------------------------------------
# share.py — DELETE /api/bookmarks/{id}/share (cross-user)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_share_delete_cross_user_returns_404(client):
    """Alice attempting DELETE /bookmarks/{bob_id}/share must return 404, not 403."""
    bm_id = await _bob_creates_bookmark(client)

    # Bob creates a share link first
    r_share = await client.post(
        f"/api/bookmarks/{bm_id}/share",
        json={"expires_in_days": 7},
        headers=_auth("bob_us6"),
    )
    assert r_share.status_code == 200, f"Bob share creation failed: {r_share.text}"
    token = r_share.json()["token"]

    # Alice tries to revoke it
    r = await client.delete(
        f"/api/bookmarks/{bm_id}/share",
        headers=_auth("alice_us6"),
    )
    assert r.status_code == 404, (
        f"Expected 404 for cross-user DELETE /share, got {r.status_code}: {r.text}"
    )

    # Bob's share token must still be intact
    r_pub = await client.get(f"/api/shared/{token}")
    assert r_pub.status_code == 200, "Bob's share link must survive alice's failed revocation attempt"
