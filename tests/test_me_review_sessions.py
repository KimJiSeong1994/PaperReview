"""GET /api/me/review-sessions — owner-only listing for the home screen."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import me
from routers.deps.auth import AuthenticatedPrincipal, get_authenticated_principal
from routers.deps.storage import _LEGACY_SESSION_OWNER_SENTINEL
from src.storage.user_db import UserDB


def _session(username, incarnation, created_at, **extra):
    base = {
        "status": "completed",
        "paper_ids": ["p1", "p2"],
        "papers_data": [{"title": "First paper", "doi": "x"}, {"title": "Second"}],
        "num_papers": 2,
        "workspace_path": "/tmp/should-not-leak",
        "created_at": created_at,
        "username": username,
    }
    if incarnation is not None:
        base["account_incarnation"] = incarnation
    base.update(extra)
    return base


@pytest.fixture
def harness(tmp_path, monkeypatch):
    users = UserDB(tmp_path / "users.db")
    alice_inc = users.create_account("alice", {})["account_incarnation"]
    bob_inc = users.create_account("bob", {})["account_incarnation"]
    monkeypatch.setattr(me, "_get_user_db", lambda: users)
    sessions = {
        "review_old": _session("alice", alice_inc, "2026-10-29T10:00:00", status="processing",
                               progress="검증 단계 2/3", papers_data=[]),
        "review_new": _session("alice", alice_inc, "2026-10-31T09:00:00"),
        "review_bob": _session("bob", bob_inc, "2026-10-31T12:00:00"),
        "review_legacy": _session(_LEGACY_SESSION_OWNER_SENTINEL, None, "2026-10-31T13:00:00"),
        "review_reregistered": _session("alice", "stale-incarnation", "2026-10-31T14:00:00"),
    }
    monkeypatch.setattr(me, "review_sessions", sessions)

    app = FastAPI()
    app.include_router(me.router)
    app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(
        "alice", alice_inc
    )
    anonymous = FastAPI()
    anonymous.include_router(me.router)
    return TestClient(app), TestClient(anonymous)


def test_lists_only_callers_sessions_newest_first(harness):
    client, _ = harness
    body = client.get("/api/me/review-sessions").json()
    assert body["total"] == 2
    assert [s["session_id"] for s in body["sessions"]] == ["review_new", "review_old"]
    newest, oldest = body["sessions"]
    assert newest["title"] == "First paper" and newest["status"] == "completed"
    assert oldest["title"] is None and oldest["progress"] == "검증 단계 2/3"
    assert newest["num_papers"] == 2
    for session in body["sessions"]:
        assert "papers_data" not in session and "workspace_path" not in session
        assert "username" not in session


def test_foreign_legacy_and_reregistered_sessions_are_excluded(harness):
    client, _ = harness
    ids = {s["session_id"] for s in client.get("/api/me/review-sessions").json()["sessions"]}
    assert ids.isdisjoint({"review_bob", "review_legacy", "review_reregistered"})


def test_unauthenticated_is_401(harness):
    _, anonymous = harness
    assert anonymous.get("/api/me/review-sessions").status_code == 401


def test_limit_is_validated_and_applied(harness):
    client, _ = harness
    # limit=0 is rejected (422) rather than clamped, like other Query(ge=1) params.
    assert client.get("/api/me/review-sessions", params={"limit": 0}).status_code == 422
    assert client.get("/api/me/review-sessions", params={"limit": 21}).status_code == 422
    body = client.get("/api/me/review-sessions", params={"limit": 1}).json()
    assert len(body["sessions"]) == 1 and body["total"] == 2
