"""
Admin-initiated account deletion (DELETE /api/admin/users/{username}).

The admin endpoint was previously a stub that only removed the row from
``users.db`` and the victim's bookmarks JSON — other storage layers
(events.db, profile.db, embeddings, papers attribution, blog, curricula,
review sessions) were left behind, so "deleted" users kept showing up in
various feeds and their JWT remained usable until natural expiry.

This module pins the new contract:

* full cascade via :func:`routers.deps.user_deletion.delete_user_cascade`;
* self-deletion blocked (HTTP 400);
* last-admin guard (HTTP 409) to avoid locking the admin panel;
* invalid username format rejected (HTTP 400) before any FS touch;
* unknown user → 404;
* non-admin caller → 403;
* the victim's JWT stops working immediately (HTTP 401 from
  ``get_current_user``) — i.e. the client can no longer list bookmarks
  after deletion.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import jwt as _pyjwt
import pytest
from fastapi.testclient import TestClient
from filelock import FileLock

# Env must be primed before any app import.
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-only")
os.environ.setdefault("APP_PASSWORD", "test-admin-password")
os.environ.setdefault("APP_USERNAME", "test-admin")

_JWT_SECRET = os.environ["JWT_SECRET"]


def _token(username: str, role: str = "user") -> str:
    from routers.deps.storage import _get_user_db

    user = _get_user_db().get(username)
    assert user is not None
    payload = {
        "sub": username,
        "account_incarnation": user["account_incarnation"],
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return _pyjwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def _bearer(username: str, role: str = "user") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(username, role)}"}


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch) -> Iterator[dict[str, Path]]:
    """Redirect every cascade-relevant path to ``tmp_path``.

    We patch ``routers.deps.user_deletion.X`` directly so the cascade
    reads the isolated paths regardless of what env vars were captured
    at import time.
    """
    events_db = tmp_path / "events.db"
    profile_db = tmp_path / "profile.db"
    embeddings_dir = tmp_path / "embeddings" / "users"
    audit_log = tmp_path / ".gdpr_audit.jsonl"
    monkeypatch.setenv("EVENTS_DB_PATH", str(events_db))
    from routers.deps.storage import _get_user_db
    from src.recommendation_state import RecommendationState

    RecommendationState.initialize(events_db, authority=_get_user_db())

    with (
        patch("routers.deps.user_deletion.EVENTS_DB_PATH", events_db),
        patch("routers.deps.user_deletion.PROFILE_DB_PATH", profile_db),
        patch("routers.deps.user_deletion.EMBEDDINGS_USERS_DIR", embeddings_dir),
        patch("routers.deps.user_deletion.GDPR_AUDIT_LOG", audit_log),
        patch("routers.deps.user_deletion.BLOG_POSTS_FILE", tmp_path / "blog.json"),
        patch(
            "routers.deps.user_deletion.BLOG_POSTS_LOCK",
            FileLock(str(tmp_path / "blog.lock")),
        ),
        patch("routers.deps.user_deletion.CURRICULA_DIR", tmp_path / "curricula"),
        patch("routers.deps.user_deletion.PAPERS_FILE", tmp_path / "papers.json"),
        patch(
            "routers.deps.user_deletion.RECOMMENDATIONS_DIR",
            tmp_path / "recommendations",
        ),
        patch(
            "routers.deps.user_deletion.RECOMMENDATION_CANDIDATES_DIR",
            tmp_path / "candidates",
        ),
    ):
        yield {
            "events_db": events_db,
            "profile_db": profile_db,
            "embeddings_dir": embeddings_dir,
            "audit_log": audit_log,
            "tmp_path": tmp_path,
        }


def _seed_user(username: str, role: str = "user") -> None:
    """Explicitly create or CAS-update an isolated account."""
    from routers.deps.storage import _get_user_db

    db = _get_user_db()
    user = db.get(username)
    data = {"password_hash": "x", "role": role, "created_at": ""}
    if user is None:
        db.create_account(username, data)
    else:
        db.upsert(username, data, expected_incarnation=user["account_incarnation"])


def _reset_rate_limiter() -> None:
    """``@limiter.limit("10/hour")`` persists across tests — clear it."""
    from routers.deps import limiter as _limiter

    _limiter._storage.reset()


@pytest.fixture
def client(tmp_env: dict, auth_headers: dict) -> Iterator[TestClient]:  # noqa: ARG001 — auth_headers side-effect seeds test-admin
    from api_server import app

    _reset_rate_limiter()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── Tests ─────────────────────────────────────────────────────────────


def test_admin_deletes_other_user_cascade_succeeds(
    client: TestClient, tmp_env: dict
) -> None:
    """Admin deletes an unrelated user; the cascade wipes their row + bookmarks."""
    from routers.deps.storage import _get_bookmark_db, _get_user_db

    _seed_user("victim")
    # Seed one bookmark so stage 4 (bookmarks) has something to remove.
    _get_bookmark_db().upsert(
        {
            "id": "bm-victim-1",
            "username": "victim",
            "title": "Victim's Paper",
            "topic": "test",
            "papers": [],
            "report": "",
        }
    )
    assert _get_user_db().get("victim") is not None
    assert _get_bookmark_db().get_by_username("victim"), (
        "precondition: victim owns at least one bookmark"
    )

    resp = client.delete(
        "/api/admin/users/victim", headers=_bearer("test-admin", "admin")
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["partial_failures"] == []
    # sha256 digest = 64 hex chars — proof-of-delete without retaining PII.
    assert isinstance(body["audit_hash"], str) and len(body["audit_hash"]) == 64

    # DB row gone.
    assert _get_user_db().get("victim") is None
    # Bookmarks gone.
    assert _get_bookmark_db().get_by_username("victim") == []
    # Audit log line was written.
    assert tmp_env["audit_log"].exists()


def test_admin_cannot_delete_self_via_admin_endpoint(client: TestClient) -> None:
    """Self-delete must go through DELETE /api/me/all, not the admin route."""
    resp = client.delete(
        "/api/admin/users/test-admin", headers=_bearer("test-admin", "admin")
    )
    assert resp.status_code == 400
    assert "own account" in resp.json()["detail"].lower()


def test_curriculum_stage_survives_appledouble_and_bad_encoding(
    client: TestClient, tmp_env: dict
) -> None:
    """Ignore sidecars, but retain reservations for unreadable owner documents."""
    from routers.deps import user_deletion as _ud
    from routers.deps.storage import _get_user_db

    _seed_user("curri_victim")

    # Point stage 7 at an isolated tmp dir so we don't mutate real data.
    curri_dir = tmp_env["tmp_path"] / "curricula_with_sidecars"
    curri_dir.mkdir(parents=True, exist_ok=True)

    # 1) A valid JSON owned by the victim — must be anonymized.
    good = curri_dir / "good.json"
    good.write_text(
        '{"curricula": [{"owner": "curri_victim", "title": "X"}]}',
        encoding="utf-8",
    )
    # 2) AppleDouble sidecar — binary, starts with Mac ``\x00\x05\x16\x07`` magic.
    sidecar = curri_dir / "._good.json"
    sidecar.write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 33 + b"\xcf\xff\xfe")
    # 3) Legit .json with cp949-encoded Korean (common on Windows exports).
    bad_enc = curri_dir / "z_bad_encoding.json"
    bad_enc.write_bytes('{"owner": "curri_victim", "note": "한글"}'.encode("cp949"))

    with patch("routers.deps.user_deletion.CURRICULA_DIR", curri_dir):
        resp = client.delete(
            "/api/admin/users/curri_victim",
            headers=_bearer("test-admin", "admin"),
        )

    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert "curriculum_anonymize" in body["partial_failures"], body
    assert body["success"] is False and body["retryable"] is True, body
    assert _get_user_db().get_lifecycle("curri_victim")["state"] == "cleanup_pending"
    # Victim is gone from the DB; good.json is anonymized.
    assert _get_user_db().get("curri_victim") is None
    assert "curri_victim" not in good.read_text(encoding="utf-8")
    # The sentinel lives in good.json.
    prefix = _ud.ANONYMIZED_SENTINEL_PREFIX
    assert prefix in good.read_text(encoding="utf-8")
    # Repair the actual owner document; the hidden sidecar remains ignored.
    bad_enc.write_text('{"owner": "curri_victim"}', encoding="utf-8")
    with patch("routers.deps.user_deletion.CURRICULA_DIR", curri_dir):
        retry = client.delete(
            "/api/admin/users/curri_victim", headers=_bearer("test-admin", "admin")
        )
    assert retry.status_code == 200 and retry.json()["success"] is True
    assert sidecar.exists()


def test_last_admin_guard_triggers_409(tmp_env: dict) -> None:
    """Exercise the defensive last-admin branch without bypassing actor auth."""
    import asyncio
    import inspect

    from fastapi import Response
    from starlette.requests import Request

    from routers.admin import delete_user
    from routers.deps.storage import _get_user_db
    from routers.deps.auth import AuthenticatedPrincipal
    from src.storage.user_db import _UserTransaction

    db = _get_user_db()
    target = db.create_account("sole_admin", {"role": "admin", "created_at": ""})
    caller = db.create_account("caller_admin", {"role": "admin"})
    principal = AuthenticatedPrincipal("caller_admin", caller["account_incarnation"])

    # slowapi's limiter insists on a real starlette.requests.Request —
    # build one from a minimal ASGI scope.
    req = Request(
        scope={
            "type": "http",
            "method": "DELETE",
            "path": "/api/admin/users/sole_admin",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 0),
        }
    )

    # With two genuinely active admins the guard cannot normally fire.
    # Inject the defensive count condition, not a forged authenticated actor.
    response = Response()
    with patch.object(_UserTransaction, "get_all", return_value={"sole_admin": target}):
        result = asyncio.run(
            inspect.unwrap(delete_user)(
                request=req,
                username="sole_admin",
                response=response,
                admin=principal,
            )
        )

    assert response.status_code == 409
    assert result["partial_failures"] == ["last_admin"]
    assert db.get("sole_admin") == target


def test_invalid_username_returns_400(client: TestClient) -> None:
    """A malformed path segment is rejected before any FS access."""
    # Spaces break the safe regex; the endpoint must 400 without touching disk.
    resp = client.delete(
        "/api/admin/users/evil%20user", headers=_bearer("test-admin", "admin")
    )
    assert resp.status_code == 400
    assert "invalid username" in resp.json()["detail"].lower()


def test_unknown_user_returns_404(client: TestClient) -> None:
    resp = client.delete(
        "/api/admin/users/nobody_here",
        headers=_bearer("test-admin", "admin"),
    )
    assert resp.status_code == 404


def test_non_admin_caller_forbidden(client: TestClient) -> None:
    """A valid user JWT without admin role gets 403, not 401."""
    _seed_user("plain_user", role="user")
    _seed_user("victim2", role="user")
    resp = client.delete(
        "/api/admin/users/victim2", headers=_bearer("plain_user", "user")
    )
    assert resp.status_code == 403


def test_deleted_users_jwt_becomes_unusable(client: TestClient) -> None:
    """After the cascade the victim's own token must be rejected (HTTP 401)."""
    _seed_user("disappear_me")

    # Preserve the original JWT rather than attempting to mint after deletion.
    victim_headers = _bearer("disappear_me", "user")
    # Pre-check: victim can hit a protected route with their own token.
    pre = client.get("/api/bookmarks", headers=victim_headers)
    assert pre.status_code == 200, pre.text

    # Admin wipes the account.
    resp = client.delete(
        "/api/admin/users/disappear_me",
        headers=_bearer("test-admin", "admin"),
    )
    assert resp.status_code == 200, resp.text

    # Same token, same endpoint — now rejected because the DB-existence
    # check in ``get_current_user`` fails for a user that no longer exists.
    post = client.get("/api/bookmarks", headers=victim_headers)
    assert post.status_code == 401
    assert (
        "deleted" in post.json()["detail"].lower()
        or "disabled" in post.json()["detail"].lower()
    )
