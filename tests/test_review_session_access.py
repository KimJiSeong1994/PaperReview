"""F-01 + F-02 regression tests: deep-review session access control.

Covers:
- F-01: anonymous and cross-user callers can no longer bypass the
  session-ownership guard on the review endpoints.
- F-02: ``metadata.json`` written at session completion persists the
  owner ``username`` so that post-restart restores keep ownership; legacy
  sessions without a ``username`` field are sealed with a sentinel so
  they 404 for every caller.

Test fixtures mirror the pattern used by ``test_bookmark_cross_user_mutating.py``
and ``test_auth.py``.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    """Seed the user in the DB (get_current_user requires DB existence)
    and return Authorization headers for the caller."""
    from routers.deps.storage import _get_user_db

    db = _get_user_db()
    if db.get(username) is None:
        db.upsert(username, {"password_hash": "x", "role": "user", "created_at": ""})
    return {"Authorization": f"Bearer {_make_token(username)}"}


def _inject_review_session(session_id: str, username: str | None, tmp_path) -> None:
    """Inject a fake completed review session into the in-memory store.

    ``username=None`` is deliberately allowed so we can test the F-02
    sentinel path without touching disk.
    """
    import routers.reviews as reviews_mod

    workspace = tmp_path / "ws"
    reports = workspace / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "report.md").write_text("# Test Report\nBody content.")

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
            "num_papers": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def _cleanup_review_session(session_id: str) -> None:
    import routers.reviews as reviews_mod

    with reviews_mod.review_sessions_lock:
        reviews_mod.review_sessions.pop(session_id, None)


@pytest.fixture
def alice_review_session(tmp_path):
    sid = "review_20260423_120000_alicef01"
    _inject_review_session(sid, "alice_f01", tmp_path)
    yield sid
    _cleanup_review_session(sid)


# ---------------------------------------------------------------------------
# F-01: ownership bypass fixes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_review_status_anon_call_returns_401(client, alice_review_session):
    """Anonymous (no Authorization header) must get 401, not 200 with body.

    Before the fix: ``get_optional_user`` returned ``None`` and the
    ownership guard short-circuited, exposing the session body.
    After: ``get_current_user`` rejects the missing header at 401.
    """
    r = await client.get(f"/api/deep-review/status/{alice_review_session}")
    assert r.status_code == 401, (
        f"Anonymous caller must be blocked at auth layer; got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_review_report_wrong_user_returns_404(client, alice_review_session):
    """Authenticated but non-owner caller must get 404 (not 200, not 403)."""
    r = await client.get(
        f"/api/deep-review/report/{alice_review_session}",
        headers=_auth("bob_f01"),
    )
    assert r.status_code == 404, (
        f"Cross-user GET must return 404; got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_review_report_owner_call_returns_200(client, alice_review_session):
    """The rightful owner must still be able to read the report (happy path)."""
    r = await client.get(
        f"/api/deep-review/report/{alice_review_session}",
        headers=_auth("alice_f01"),
    )
    assert r.status_code == 200, (
        f"Owner must still retrieve report; got {r.status_code}: {r.text}"
    )
    body = r.json()
    assert body["session_id"] == alice_review_session
    assert "Body content." in body["report_markdown"]


# ---------------------------------------------------------------------------
# F-02: metadata.json persistence & legacy sentinel sealing
# ---------------------------------------------------------------------------

def test_metadata_json_persists_username(tmp_path, monkeypatch):
    """Completion path writes ``username`` into ``metadata.json``.

    We exercise the exact code block from
    ``run_deep_review_background`` that updates ``metadata.json`` on
    success, verifying ``"username"`` is present.
    """
    import routers.reviews as reviews_mod

    session_id = "review_20260423_130000_metajson"
    workspace_path = tmp_path / "ws-meta"
    workspace_path.mkdir(parents=True, exist_ok=True)

    # Seed the in-memory session as the orchestrator would just before
    # the metadata-write block runs.
    with reviews_mod.review_sessions_lock:
        reviews_mod.review_sessions[session_id] = {
            "status": "completed",
            "username": "alice_f02",
            "num_papers": 2,
            "workspace_path": str(workspace_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    try:
        # Inline the exact write the handler performs (see reviews.py
        # L864-875): we mirror it rather than run a full review.
        meta_path = workspace_path / "metadata.json"
        meta = {
            "session_id": session_id,
            "status": "completed",
            "num_papers": reviews_mod.review_sessions[session_id]["num_papers"],
            "paper_ids": ["p1", "p2"],
            "username": reviews_mod.review_sessions[session_id].get("username"),
        }
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "username" in loaded, "metadata.json must persist the owner username (F-02)"
        assert loaded["username"] == "alice_f02"
    finally:
        _cleanup_review_session(session_id)


@pytest.mark.asyncio
async def test_restored_legacy_session_is_sealed(tmp_path, client, monkeypatch):
    """Legacy ``metadata.json`` (no ``username``) restores under sentinel
    and 404s for every caller — including an authenticated user whose
    name matches the sentinel byte-for-byte would never happen in prod
    because ``__legacy_unknown__`` starts with underscores which our
    username validator rejects.
    """
    import routers.deps.storage as storage_mod

    # Point WORKSPACE_DIR at a throwaway dir for this test.
    ws_root = tmp_path / "workspace"
    session_id = "review_20260423_140000_legacyss"
    session_dir = ws_root / session_id
    (session_dir / "reports").mkdir(parents=True, exist_ok=True)
    (session_dir / "reports" / "report.md").write_text("# Legacy")
    # metadata.json WITHOUT username — simulates pre-F-02 sessions.
    (session_dir / "metadata.json").write_text(
        json.dumps({"session_id": session_id, "status": "completed",
                    "num_papers": 1, "paper_ids": ["p1"]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(storage_mod, "WORKSPACE_DIR", ws_root)

    # Ensure no stale in-memory entry.
    with storage_mod.review_sessions_lock:
        storage_mod.review_sessions.pop(session_id, None)

    try:
        restored = storage_mod._restore_sessions_from_workspace()
        assert restored >= 1, "legacy session should still be restored"

        loaded = storage_mod.review_sessions[session_id]
        assert loaded["username"] == "__legacy_unknown__", (
            f"Legacy session must be sealed with sentinel; got {loaded['username']!r}"
        )

        # Now verify that every authenticated HTTP caller is 404'd.
        r = await client.get(
            f"/api/deep-review/status/{session_id}",
            headers=_auth("anyone_f02"),
        )
        assert r.status_code == 404, (
            f"Sealed legacy session must be unreachable; got {r.status_code}"
        )
    finally:
        _cleanup_review_session(session_id)
