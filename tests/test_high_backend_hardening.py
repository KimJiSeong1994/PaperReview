"""
High-severity backend hardening fixes — regression harness for F-32..F-35.

Pins the following behaviours from ``.omc/reviews/FINAL_AUDIT-2026-04-23.md``:

  * F-32 — admin bookmark delete MUST remove the row from SQLite, not merely
    filter a list in memory.
  * F-33 — unauthenticated callers MUST NOT be able to trigger the external
    reference-collection fan-out endpoints.
  * F-34 — the LLM-hitting mutating endpoints MUST honour per-IP rate limits
    (canary: ``/api/pdf-highlights`` at 10/min).
  * F-35 — the ``httpx.AsyncClient`` singleton in ``routers.pdf_proxy`` MUST
    be closed when the FastAPI lifespan shuts down.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Iterator

import jwt as _pyjwt
import pytest
from fastapi.testclient import TestClient

from tests.conftest import _TEST_JWT_SECRET


# ── Helpers ────────────────────────────────────────────────────────────

def _admin_bearer() -> dict[str, str]:
    """Admin bearer token that matches the test-admin seed in conftest."""
    payload = {
        "sub": "test-admin",
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = _pyjwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user_bearer(username: str = "hbh-user") -> dict[str, str]:
    """User bearer token for a regular (non-admin) caller."""
    payload = {
        "sub": username,
        "role": "user",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = _pyjwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _reset_rate_limiter() -> None:
    """Zero out slowapi's in-memory counters so tests don't pollute each other."""
    from routers.deps import limiter as _limiter

    _limiter._storage.reset()


def _seed_user(username: str, role: str = "user") -> None:
    from routers.deps.storage import _get_user_db

    _get_user_db().upsert(
        username,
        {"password_hash": "x", "role": role, "created_at": ""},
    )


@pytest.fixture
def sync_client(auth_headers: dict) -> Iterator[TestClient]:  # noqa: ARG001 — side-effect seeds test-admin
    """TestClient driven by ASGI — supports lifespan-exercising tests."""
    from api_server import app

    _reset_rate_limiter()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── F-32 — admin bookmark delete is no-op at SQLite layer ──────────────


def test_f32_admin_delete_bookmark_removes_from_sqlite(
    sync_client: TestClient,
) -> None:
    """Admin deletes a bookmark and the row is *actually* gone from SQLite.

    Before the fix, ``routers.admin.admin_delete_bookmark`` filtered a
    Python list and then called ``save_bookmarks`` — which upserts only.
    The filtered row was never removed, so ``BookmarkDB.get_by_id`` kept
    returning it and ``GET /api/admin/bookmarks`` kept listing it.
    """
    from routers.deps.storage import _get_bookmark_db

    db = _get_bookmark_db()
    bm_id = "bm-f32-delete-target"
    db.upsert(
        {
            "id": bm_id,
            "username": "test-admin",
            "title": "f32-target",
            "topic": "test",
            "papers": [],
            "report_markdown": "",
        }
    )
    assert db.get_by_id(bm_id) is not None, "precondition: bookmark seeded"

    resp = sync_client.delete(
        f"/api/admin/bookmarks/{bm_id}", headers=_admin_bearer()
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    # SQLite-layer contract: row is gone.
    assert db.get_by_id(bm_id) is None, (
        "F-32 regression: admin_delete_bookmark left the row in SQLite"
    )

    # API-layer contract: the admin listing no longer shows it.
    list_resp = sync_client.get("/api/admin/bookmarks", headers=_admin_bearer())
    assert list_resp.status_code == 200, list_resp.text
    listed_ids = {b["id"] for b in list_resp.json().get("bookmarks", [])}
    assert bm_id not in listed_ids, (
        "F-32 regression: deleted bookmark still listed by /api/admin/bookmarks"
    )


def test_f32_admin_delete_missing_bookmark_returns_404(
    sync_client: TestClient,
) -> None:
    """Missing bookmark still surfaces as 404 (contract preserved after the fix)."""
    resp = sync_client.delete(
        "/api/admin/bookmarks/bm-f32-does-not-exist",
        headers=_admin_bearer(),
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ── F-33 — unauthenticated reference-collection endpoints ──────────────


def test_f33_collect_references_requires_auth(sync_client: TestClient) -> None:
    """Anonymous POST must NOT trigger the external-API fan-out.

    We accept either 401 (decorator auth block) or 403, but NEVER 200/202:
    a public caller must not reach ``search_agent.collect_references``.
    """
    resp = sync_client.post("/api/collect-references")
    assert resp.status_code in (401, 403), (
        f"F-33 regression: anon /api/collect-references returned "
        f"{resp.status_code} (expected 401 or 403)"
    )


# ── F-34 — rate limit canary on pdf-highlights ─────────────────────────


def test_f34_pdf_highlights_rate_limited_at_10_per_minute(
    sync_client: TestClient,
) -> None:
    """Spam 11 calls to /api/pdf-highlights → the 11th returns 429.

    We use ``/api/pdf-highlights`` as the representative canary for F-34.
    The other decorator-only endpoints (curriculum, lightrag, topology,
    etc.) are covered by the decorator presence itself; we do not duplicate
    the spam test shape for each.

    Note: pdf-highlights reads ``body.text`` before any LLM call; we send
    a too-short body so each allowed call returns 400 (body validation)
    — but slowapi still counts the request and the 11th must be 429.
    """
    _reset_rate_limiter()
    _seed_user("hbh-user")

    too_short_body = {"text": "x", "title": "t"}

    statuses = []
    for _ in range(11):
        resp = sync_client.post(
            "/api/pdf-highlights",
            json=too_short_body,
            headers=_user_bearer("hbh-user"),
        )
        statuses.append(resp.status_code)
        if resp.status_code == 429:
            break

    assert statuses[-1] == 429, (
        f"F-34 regression: 11th /api/pdf-highlights call was {statuses[-1]} "
        f"(expected 429). Sequence: {statuses}"
    )


# ── F-35 — httpx.AsyncClient closed on lifespan shutdown ───────────────


def test_f35_lifespan_shutdown_closes_http_client() -> None:
    """Exiting ``TestClient(app)``'s lifespan context must close the singleton.

    The module-level ``_http_client`` in ``routers.pdf_proxy`` holds a TCP
    pool.  Before the fix, the lifespan shutdown hook forgot to await
    ``close_http_client()`` — SIGTERM on a rolling deploy leaked the
    sockets until the interpreter was reaped.  We trigger the singleton
    via ``_get_http_client`` (a real ``httpx.AsyncClient`` is cheap to
    construct and has no side effects), then exit the lifespan and assert
    the client is closed.
    """
    from api_server import app
    from routers import pdf_proxy

    # Force the singleton into existence so there is something to close.
    loop = asyncio.new_event_loop()
    try:
        client = loop.run_until_complete(pdf_proxy._get_http_client())
    finally:
        loop.close()

    assert client is pdf_proxy._http_client
    assert client.is_closed is False, "precondition: singleton must be open"

    # TestClient's context manager drives FastAPI's lifespan. The shutdown
    # branch (after ``yield`` in ``api_server.lifespan``) runs when the
    # ``with`` block exits.
    with TestClient(app, raise_server_exceptions=False):
        pass  # startup runs; body does nothing; shutdown runs on exit

    # After lifespan shutdown the module-level client must be closed.
    # Our implementation resets ``_http_client`` to ``None`` after
    # ``aclose()``; either state (None, or closed-but-non-None) proves the
    # shutdown branch ran and released the TCP pool.
    post_state = pdf_proxy._http_client
    if post_state is None:
        assert client.is_closed, (
            "F-35 regression: lifespan shutdown nulled the reference but did "
            "not await aclose() on the live client"
        )
    else:
        assert post_state.is_closed, (
            "F-35 regression: lifespan shutdown left _http_client open"
        )
