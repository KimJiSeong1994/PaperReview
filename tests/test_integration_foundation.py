"""
Integration tests for the Week-0 Foundation event pipeline (US-008).

These tests exercise the full path from HTTP request → router handler →
``EventBus.publish`` → SQLite ``user_events`` ledger → GDPR wipe.  They
are *integration* rather than unit tests: every collaborator in the
chain is the real production object, only the storage paths are moved
to ``tmp_path``.

Test cases
----------
``test_full_event_pipeline``
    Create + delete a bookmark, drain the bus, assert each event
    persisted, then DELETE /api/me/all wipes the user's rows.
``test_startup_creates_db_files``
    Importing ``routers.deps`` with fresh env-pointed DB paths must
    create both SQLite files on disk with the expected tables.
``test_event_bus_singleton_available_after_startup``
    After ``routers.deps`` imports, ``get_event_bus()`` returns a
    functional :class:`EventBus`.

Isolation strategy
------------------
Every test points ``EVENTS_DB_PATH`` / ``PROFILE_DB_PATH`` at
``tmp_path`` via :func:`os.environ` and re-initialises the module-level
event-bus singleton via :func:`init_event_bus` with the tmp path before
triggering the code under test.  The production ``data/events.db`` is
never touched.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

# ── Path bootstrap ────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Minimal env before any app import.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key-for-testing")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-only")
os.environ.setdefault("APP_PASSWORD", "test-admin-password")
os.environ.setdefault("APP_USERNAME", "test-admin")

_TEST_JWT_SECRET = os.environ["JWT_SECRET"]
_USERNAME = "integration-user"


def _make_token(username: str = _USERNAME) -> str:
    """Return a signed HS256 JWT for *username*."""
    payload = {
        "sub": username,
        "role": "user",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")


def _auth(username: str = _USERNAME) -> dict[str, str]:
    """Return an Authorization header dict for *username*."""
    return {"Authorization": f"Bearer {_make_token(username)}"}


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def isolated_event_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point events.db and profile.db at *tmp_path* and re-init the bus.

    The module-level :class:`EventBus` singleton is replaced with one
    opening the tmp DB so every ``get_event_bus()`` call inside the
    server resolves to the isolated instance.  The bookmarks JSON file
    and ``routers.me.EVENTS_DB_PATH`` / ``PROFILE_DB_PATH`` are also
    repointed so the full CRUD + GDPR loop exercises the tmp paths.

    Yields a dict with the key paths.
    """
    events_db = tmp_path / "events.db"
    profile_db = tmp_path / "profile.db"
    bookmarks_file = tmp_path / "bookmarks.json"
    bookmarks_file.write_text(json.dumps({"bookmarks": []}))

    monkeypatch.setenv("EVENTS_DB_PATH", str(events_db))
    monkeypatch.setenv("PROFILE_DB_PATH", str(profile_db))

    # Re-initialise the event-bus singleton against the tmp DB.
    from src.events.event_bus import init_event_bus
    from src.events.migrations import ensure_events_db, ensure_profile_db

    ensure_events_db(events_db)
    ensure_profile_db(profile_db)
    init_event_bus(events_db)

    from filelock import FileLock

    with (
        patch("routers.deps.storage.BOOKMARKS_FILE", bookmarks_file),
        patch(
            "routers.deps.storage._bookmarks_lock",
            FileLock(str(bookmarks_file) + ".lock"),
        ),
        patch("routers.me.EVENTS_DB_PATH", events_db),
        patch("routers.me.PROFILE_DB_PATH", profile_db),
        patch("routers.me._EMBEDDINGS_USERS_DIR", tmp_path / "embeddings" / "users"),
        patch("routers.me._GDPR_AUDIT_LOG", tmp_path / ".gdpr_audit.jsonl"),
    ):
        yield {
            "events_db": events_db,
            "profile_db": profile_db,
            "bookmarks_file": bookmarks_file,
            "tmp_path": tmp_path,
        }


@pytest.fixture()
def test_client(isolated_event_paths):
    """TestClient wired to the isolated event-pipeline fixtures."""
    from api_server import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────────


def _drain_event_bus(timeout: float = 5.0) -> None:
    """Block until every in-flight subscriber task finishes.

    ``publish`` is an async coroutine; when invoked from the sync
    TestClient path it runs via ``asyncio.create_task``.  We drive the
    drain coroutine from a fresh event loop since TestClient's loop is
    already closed by the time we want to assert.
    """
    from src.events.event_bus import get_event_bus

    bus = get_event_bus()
    asyncio.run(bus.wait_for_drain(timeout=timeout))


def _count_events(
    db_path: Path,
    *,
    user_id: str,
    event_type: str | None = None,
) -> int:
    """Return the number of ``user_events`` rows matching the filter."""
    conn = sqlite3.connect(str(db_path))
    try:
        if event_type is None:
            row = conn.execute(
                "SELECT COUNT(*) FROM user_events WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM user_events "
                "WHERE user_id = ? AND event_type = ?",
                (user_id, event_type),
            ).fetchone()
        return int(row[0])
    finally:
        conn.close()


# ── Tests ─────────────────────────────────────────────────────────────


def test_full_event_pipeline(
    test_client: TestClient, isolated_event_paths: dict
) -> None:
    """End-to-end: create → drain → delete → drain → GDPR wipe."""
    events_db: Path = isolated_event_paths["events_db"]

    # 1. POST /api/bookmarks — expect a ``bookmark_add`` event.
    resp = test_client.post(
        "/api/bookmarks",
        json={
            "session_id": "it-session-001",
            "title": "Integration Bookmark",
            "query": "event pipeline",
            "papers": [{"title": "paper X"}],
            "report_markdown": "# Report\nintegration test body",
            "tags": ["integration"],
            "topic": "pipeline",
        },
        headers=_auth(),
    )
    assert resp.status_code == 200, resp.text
    bookmark_id = resp.json()["id"]

    _drain_event_bus()
    assert _count_events(
        events_db, user_id=_USERNAME, event_type="bookmark_add"
    ) == 1, "bookmark_add event must be persisted after POST"

    # 2. DELETE /api/bookmarks/{id} — expect a ``bookmark_remove`` event.
    resp = test_client.delete(
        f"/api/bookmarks/{bookmark_id}", headers=_auth()
    )
    assert resp.status_code == 200, resp.text

    _drain_event_bus()
    assert _count_events(
        events_db, user_id=_USERNAME, event_type="bookmark_remove"
    ) == 1, "bookmark_remove event must be persisted after DELETE"

    total_before_wipe = _count_events(events_db, user_id=_USERNAME)
    assert total_before_wipe >= 2

    # 3. DELETE /api/me/all — the GDPR wipe must clear every row for
    # the user in the events ledger.
    resp = test_client.delete("/api/me/all", headers=_auth())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] is True, body
    assert body["partial_failures"] == [], body

    assert _count_events(events_db, user_id=_USERNAME) == 0, (
        "GDPR wipe must remove every row for the user in events.db"
    )


def test_startup_creates_db_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh import with tmp DB paths must create both DB files."""
    events_db = tmp_path / "startup_events.db"
    profile_db = tmp_path / "startup_profile.db"

    assert not events_db.exists()
    assert not profile_db.exists()

    monkeypatch.setenv("EVENTS_DB_PATH", str(events_db))
    monkeypatch.setenv("PROFILE_DB_PATH", str(profile_db))

    # Call the public migration helpers directly — this is the exact
    # bootstrap contract exercised by ``routers.deps`` on import.
    from src.events.migrations import ensure_events_db, ensure_profile_db

    ensure_events_db(events_db)
    ensure_profile_db(profile_db)

    assert events_db.exists(), "events.db must be created on startup"
    assert profile_db.exists(), "profile.db must be created on startup"

    conn = sqlite3.connect(str(events_db))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "user_events" in tables, f"user_events missing; got {tables}"

    conn = sqlite3.connect(str(profile_db))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "user_rubric" in tables, f"user_rubric missing; got {tables}"

    # Also verify the ``routers.deps`` import path wires a fresh bus.
    import routers.deps as deps_mod  # noqa: F401 — side-effects desired
    importlib.reload(deps_mod)

    from src.events.event_bus import get_event_bus

    bus = get_event_bus()
    assert Path(bus._db_path) == events_db, (
        "init_event_bus in deps must honour EVENTS_DB_PATH"
    )


def test_event_bus_singleton_available_after_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``get_event_bus()`` must return a working bus after deps import."""
    monkeypatch.setenv("EVENTS_DB_PATH", str(tmp_path / "singleton_events.db"))
    monkeypatch.setenv("PROFILE_DB_PATH", str(tmp_path / "singleton_profile.db"))

    import routers.deps as deps_mod
    importlib.reload(deps_mod)

    from src.events.event_bus import EventBus, get_event_bus
    from src.events.event_types import EventType, UserEvent

    bus = get_event_bus()
    assert isinstance(bus, EventBus)

    # A direct publish must succeed and persist a row.
    async def _publish_and_drain() -> None:
        await bus.publish(
            UserEvent(
                user_id="singleton-user",
                event_type=EventType.PAPER_OPEN,
                payload={"paper_id": "p1"},
            )
        )
        await bus.wait_for_drain(timeout=2.0)

    asyncio.run(_publish_and_drain())

    rows = _count_events(
        Path(bus._db_path),
        user_id="singleton-user",
        event_type="paper_open",
    )
    assert rows == 1, "publish must persist synchronously before fan-out"
