"""
Tests for the GDPR unified delete endpoint: DELETE /api/me/all (US-007).

Test cases
----------
test_delete_all_requires_auth           — no auth token → 401
test_delete_all_success_returns_audit_hash — all 6 stages complete; audit log line appended
test_delete_all_partial_failure_reports_stages — one stage error → deleted=False, partial_failures listed
test_delete_all_rate_limited            — 4th request in the same day → 429
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

# ── Path setup ────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Minimal env before app import
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key-for-testing")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-only")
os.environ.setdefault("APP_PASSWORD", "test-admin-password")
os.environ.setdefault("APP_USERNAME", "test-admin")

_TEST_JWT_SECRET = os.environ["JWT_SECRET"]

USERNAME = "testuser"


def _make_token(username: str = USERNAME) -> str:
    """Create a valid JWT for tests."""
    from datetime import datetime, timedelta, timezone

    payload = {
        "sub": username,
        "role": "user",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")


def _auth(username: str = USERNAME) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(username)}"}


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_dbs(tmp_path: Path):
    """Create minimal SQLite DBs and patch all path constants in routers.me.

    The bookmark DB is created via the storage-layer singleton so that the
    GDPR stage 4 path (which now routes through ``_get_bookmark_db``) and the
    test verification read/write the *same* file.
    """
    # events.db
    events_db = tmp_path / "events.db"
    conn = sqlite3.connect(str(events_db))
    conn.execute(
        """CREATE TABLE user_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            paper_id TEXT,
            created_at TEXT NOT NULL,
            source TEXT DEFAULT 'app'
        )"""
    )
    conn.execute(
        "INSERT INTO user_events (user_id, event_type, payload, created_at) VALUES (?,?,?,?)",
        (USERNAME, "SEARCH", "{}", "2024-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    # profile.db
    profile_db = tmp_path / "profile.db"
    conn = sqlite3.connect(str(profile_db))
    conn.execute("CREATE TABLE user_rubric (username TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO user_rubric (username) VALUES (?)", (USERNAME,))
    conn.commit()
    conn.close()

    # bookmarks.db — point the storage-layer singleton at a tmp path so the
    # GDPR endpoint and the test share one canonical DB.
    bookmarks_json = tmp_path / "bookmarks.json"
    bookmarks_db = bookmarks_json.with_suffix(".db")

    from routers.deps import storage as _storage
    from src.storage.bookmark_db import BookmarkDB

    # Reset the per-test singleton cache so the next _get_bookmark_db()
    # picks up the patched path.
    _storage._bookmark_dbs.clear()

    # Seed one bookmark through the real schema so verification SELECTs work.
    _seed_db = BookmarkDB(db_path=bookmarks_db)
    _seed_db.upsert(
        {
            "id": "bm_001",
            "username": USERNAME,
            "title": "Test bookmark",
            "created_at": "2024-01-01T00:00:00",
        }
    )

    audit_log = tmp_path / ".gdpr_audit.jsonl"

    with (
        patch("routers.me.EVENTS_DB_PATH", events_db),
        patch("routers.me.PROFILE_DB_PATH", profile_db),
        patch("routers.deps.storage.BOOKMARKS_FILE", bookmarks_json),
        patch("routers.me._EMBEDDINGS_USERS_DIR", tmp_path / "embeddings" / "users"),
        patch("routers.me._GDPR_AUDIT_LOG", audit_log),
    ):
        yield {
            "events_db": events_db,
            "profile_db": profile_db,
            "bookmarks_db": bookmarks_db,
            "audit_log": audit_log,
            "tmp_path": tmp_path,
        }

    # Teardown: clear the singleton cache so the next test does not reuse
    # a handle pointing at a tmp_path that is about to disappear.
    _storage._bookmark_dbs.clear()


@pytest.fixture()
def client():
    """Synchronous TestClient backed by the real app."""
    # Import app after env is set
    from api_server import app

    # Disable rate limit storage to avoid cross-test bleed for most tests;
    # the rate-limit test uses a fresh client with its own counter.
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Tests ─────────────────────────────────────────────────────────────

def test_delete_all_requires_auth(client: TestClient):
    """DELETE /api/me/all without a token must return 401."""
    resp = client.delete("/api/me/all")
    assert resp.status_code == 401, resp.text


def test_delete_all_success_returns_audit_hash(
    client: TestClient, tmp_dbs: dict
):
    """All 6 stages succeed; response has deleted=True and correct audit_hash."""
    resp = client.delete("/api/me/all", headers=_auth())
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert data["deleted"] is True
    assert data["partial_failures"] == []

    expected_hash = hashlib.sha256(USERNAME.encode()).hexdigest()
    assert data["audit_hash"] == expected_hash

    # Verify audit log was written
    audit_log: Path = tmp_dbs["audit_log"]
    assert audit_log.exists(), "audit log file should be created"
    lines = audit_log.read_text().strip().splitlines()
    assert len(lines) >= 1
    record = json.loads(lines[-1])
    assert record["audit_hash"] == expected_hash
    assert record["partial_failures"] == []

    # Verify events_db row deleted
    conn = sqlite3.connect(str(tmp_dbs["events_db"]))
    rows = conn.execute(
        "SELECT COUNT(*) FROM user_events WHERE user_id = ?", (USERNAME,)
    ).fetchone()[0]
    conn.close()
    assert rows == 0, "user_events rows should have been deleted"

    # Verify bookmarks row deleted
    conn = sqlite3.connect(str(tmp_dbs["bookmarks_db"]))
    rows = conn.execute(
        "SELECT COUNT(*) FROM bookmarks WHERE username = ?", (USERNAME,)
    ).fetchone()[0]
    conn.close()
    assert rows == 0, "bookmark rows should have been deleted"


def test_delete_all_partial_failure_reports_stages(
    tmp_dbs: dict,
):
    """When events_db stage raises, deleted=False and 'events_db' in partial_failures."""
    from api_server import app

    def _bad_connect(path, **kwargs):
        if "events" in str(path):
            raise RuntimeError("simulated events_db failure")
        return sqlite3.connect(path, **kwargs)

    with (
        patch("routers.me.EVENTS_DB_PATH", tmp_dbs["events_db"]),
        patch("routers.me.PROFILE_DB_PATH", tmp_dbs["profile_db"]),
        patch("routers.deps.storage.BOOKMARKS_FILE", tmp_dbs["bookmarks_db"].with_suffix(".json")),
        patch("routers.me._EMBEDDINGS_USERS_DIR", tmp_dbs["tmp_path"] / "embeddings" / "users"),
        patch("routers.me._GDPR_AUDIT_LOG", tmp_dbs["audit_log"]),
        patch("routers.me.sqlite3.connect", side_effect=_bad_connect),
        TestClient(app) as c,
    ):
        resp = c.delete("/api/me/all", headers=_auth())

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["deleted"] is False
    assert "events_db" in data["partial_failures"]


def test_delete_all_rate_limited(tmp_dbs: dict):
    """The 4th request in the same day must return 429.

    Strategy: reset the shared limiter storage (in-memory) before the test so
    that request counts from prior tests don't bleed in. The decorator closure
    holds a reference to the real limiter, so we reset that limiter's storage
    directly rather than swapping the limiter object.
    """
    from api_server import app
    from routers.deps import limiter as real_limiter

    # Flush all rate-limit counters accumulated by prior tests.
    real_limiter._storage.reset()

    with (
        patch("routers.me.EVENTS_DB_PATH", tmp_dbs["events_db"]),
        patch("routers.me.PROFILE_DB_PATH", tmp_dbs["profile_db"]),
        patch("routers.deps.storage.BOOKMARKS_FILE", tmp_dbs["bookmarks_db"].with_suffix(".json")),
        patch("routers.me._EMBEDDINGS_USERS_DIR", tmp_dbs["tmp_path"] / "embeddings" / "users"),
        patch("routers.me._GDPR_AUDIT_LOG", tmp_dbs["audit_log"]),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            # Requests 1–3 must not be rate-limited
            for i in range(3):
                resp = c.delete("/api/me/all", headers=_auth())
                assert resp.status_code != 429, (
                    f"Request {i+1} should not be rate-limited yet, got {resp.status_code}"
                )

            # Request 4 must be 429
            resp = c.delete("/api/me/all", headers=_auth())
            assert resp.status_code == 429, (
                f"Expected 429 on 4th request, got {resp.status_code}: {resp.text}"
            )


def test_rate_limit_keyed_by_user_not_ip(tmp_dbs: dict):
    """Same user from two different IPs counts against the same quota.

    After 3 requests from one IP the 4th request from a *different* IP
    (but the same JWT sub) must also return 429.
    """
    from api_server import app
    from routers.deps import limiter as real_limiter

    real_limiter._storage.reset()

    with (
        patch("routers.me.EVENTS_DB_PATH", tmp_dbs["events_db"]),
        patch("routers.me.PROFILE_DB_PATH", tmp_dbs["profile_db"]),
        patch("routers.deps.storage.BOOKMARKS_FILE", tmp_dbs["bookmarks_db"].with_suffix(".json")),
        patch("routers.me._EMBEDDINGS_USERS_DIR", tmp_dbs["tmp_path"] / "embeddings" / "users"),
        patch("routers.me._GDPR_AUDIT_LOG", tmp_dbs["audit_log"]),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            # Requests 1–3 from "IP 1.2.3.4"
            for i in range(3):
                resp = c.delete(
                    "/api/me/all",
                    headers={**_auth(), "X-Forwarded-For": "1.2.3.4"},
                )
                assert resp.status_code != 429, (
                    f"Request {i+1} should not be rate-limited yet"
                )

            # Request 4 from a *different* IP but same JWT sub — still 429.
            resp = c.delete(
                "/api/me/all",
                headers={**_auth(), "X-Forwarded-For": "9.9.9.9"},
            )
            assert resp.status_code == 429, (
                f"4th request (different IP, same user) should be 429, got {resp.status_code}"
            )


def test_rate_limit_separates_users(tmp_dbs: dict):
    """User alice and user bob each have their own independent 3/day quota."""
    from api_server import app
    from routers.deps import limiter as real_limiter

    real_limiter._storage.reset()

    with (
        patch("routers.me.EVENTS_DB_PATH", tmp_dbs["events_db"]),
        patch("routers.me.PROFILE_DB_PATH", tmp_dbs["profile_db"]),
        patch("routers.deps.storage.BOOKMARKS_FILE", tmp_dbs["bookmarks_db"].with_suffix(".json")),
        patch("routers.me._EMBEDDINGS_USERS_DIR", tmp_dbs["tmp_path"] / "embeddings" / "users"),
        patch("routers.me._GDPR_AUDIT_LOG", tmp_dbs["audit_log"]),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            # Exhaust alice's quota
            for i in range(3):
                resp = c.delete("/api/me/all", headers=_auth("alice"))
                assert resp.status_code != 429, f"alice request {i+1} should not be limited"

            # alice's 4th must be 429
            assert c.delete("/api/me/all", headers=_auth("alice")).status_code == 429

            # bob still has a fresh quota — his 1st request must succeed
            resp = c.delete("/api/me/all", headers=_auth("bob"))
            assert resp.status_code != 429, (
                f"bob's first request should not be rate-limited; got {resp.status_code}"
            )


def test_invalid_username_does_not_leak_pii_to_log(tmp_dbs: dict, caplog):
    """Raw username must never appear in log output when assert_valid_username raises."""
    from api_server import app

    bad_username = "evil<script>xss</script>user"

    with (
        patch("routers.me.EVENTS_DB_PATH", tmp_dbs["events_db"]),
        patch("routers.me.PROFILE_DB_PATH", tmp_dbs["profile_db"]),
        patch("routers.deps.storage.BOOKMARKS_FILE", tmp_dbs["bookmarks_db"].with_suffix(".json")),
        patch("routers.me._EMBEDDINGS_USERS_DIR", tmp_dbs["tmp_path"] / "embeddings" / "users"),
        patch("routers.me._GDPR_AUDIT_LOG", tmp_dbs["audit_log"]),
        # Force assert_valid_username to raise so we exercise the log path
        patch(
            "routers.me.assert_valid_username",
            side_effect=ValueError("invalid username"),
        ),
    ):
        with caplog.at_level(logging.DEBUG, logger="routers.me"):
            with TestClient(app, raise_server_exceptions=True) as c:
                resp = c.delete("/api/me/all", headers=_auth(bad_username))

    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] is False
    assert "username_invalid" in data["partial_failures"]

    # Raw username must not appear anywhere in the captured log records
    all_log_text = " ".join(r.getMessage() for r in caplog.records)
    assert bad_username not in all_log_text, (
        "Raw username leaked into log output — PII violation"
    )


def test_audit_log_write_failure_flags_partial(tmp_dbs: dict):
    """When audit log write raises, deleted=False and 'audit_log' in partial_failures."""
    from api_server import app

    with (
        patch("routers.me.EVENTS_DB_PATH", tmp_dbs["events_db"]),
        patch("routers.me.PROFILE_DB_PATH", tmp_dbs["profile_db"]),
        patch("routers.deps.storage.BOOKMARKS_FILE", tmp_dbs["bookmarks_db"].with_suffix(".json")),
        patch("routers.me._EMBEDDINGS_USERS_DIR", tmp_dbs["tmp_path"] / "embeddings" / "users"),
        patch("routers.me._GDPR_AUDIT_LOG", tmp_dbs["audit_log"]),
        # Make _append_audit_log raise to simulate a disk/permission error
        patch(
            "routers.me._append_audit_log",
            side_effect=OSError("disk full"),
        ),
    ):
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.delete("/api/me/all", headers=_auth())

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["deleted"] is False, "deleted must be False when audit_log stage fails"
    assert "audit_log" in data["partial_failures"], (
        f"'audit_log' missing from partial_failures: {data['partial_failures']}"
    )


# ── RT1: GDPR actually deletes bookmarks end-to-end ────────────────────

def test_gdpr_actually_deletes_bookmarks(tmp_path: Path, monkeypatch):
    """Live-simulated end-to-end: register → create 3 bookmarks → DELETE /api/me/all
    → 0 rows remain in the real BookmarkDB.

    Regression test for RT1: ``routers/me.py`` previously opened a parallel
    sqlite3 connection against an env-derived path that could diverge from the
    storage-layer singleton. This test goes through the live HTTP stack so
    that any future divergence is caught.
    """
    # Steer the storage layer at an isolated tmp bookmark DB before app import.
    from routers.deps import storage as _storage
    from routers.deps import limiter as real_limiter

    bookmarks_json = tmp_path / "bookmarks.json"
    bookmarks_db_path = bookmarks_json.with_suffix(".db")

    # Reset singletons so the patched path takes effect.
    _storage._bookmark_dbs.clear()
    real_limiter._storage.reset()

    monkeypatch.setattr(_storage, "BOOKMARKS_FILE", bookmarks_json)

    # Also steer the other GDPR paths so we never touch real data.
    events_db = tmp_path / "events.db"
    profile_db = tmp_path / "profile.db"
    # Create minimal schemas to keep stages 1 & 3 as no-ops (files exist but
    # tables may be absent → no error in current logic).
    sqlite3.connect(str(events_db)).close()
    sqlite3.connect(str(profile_db)).close()

    from api_server import app
    username = "dave_rt1"

    with (
        patch("routers.me.EVENTS_DB_PATH", events_db),
        patch("routers.me.PROFILE_DB_PATH", profile_db),
        patch("routers.me._EMBEDDINGS_USERS_DIR", tmp_path / "embeddings" / "users"),
        patch("routers.me._GDPR_AUDIT_LOG", tmp_path / ".gdpr_audit.jsonl"),
    ):
        with TestClient(app, raise_server_exceptions=True) as c:
            headers = {"Authorization": f"Bearer {_make_token(username)}"}

            # Create 3 bookmarks via the live API.
            for i in range(3):
                resp = c.post(
                    "/api/bookmarks",
                    headers=headers,
                    json={
                        "session_id": f"s{i}",
                        "title": f"t{i}",
                        "papers": [],
                        "report_markdown": "x",
                        "topic": "T",
                    },
                )
                assert resp.status_code == 200, f"create {i} failed: {resp.text}"

            # Verify via the same singleton the server uses.
            db = _storage._get_bookmark_db()
            before = len(db.get_by_username(username))
            assert before == 3, f"expected 3 bookmarks, got {before}"

            # Fire GDPR delete-all.
            resp = c.delete("/api/me/all", headers=headers)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert "bookmarks" not in data["partial_failures"], (
                f"bookmarks stage reported partial failure: {data['partial_failures']}"
            )

            # 0 rows must remain for this user in the canonical DB.
            after = len(db.get_by_username(username))
            assert after == 0, (
                f"Expected 0 bookmarks after GDPR, got {after} "
                f"(DB path: {bookmarks_db_path})"
            )


# ── RT3: _user_key_func must never leak the raw username ──────────────

def test_user_key_func_returns_opaque_hash():
    """``_user_key_func`` must return ``"u:<hex16>"`` — never the raw JWT sub.

    slowapi logs the key verbatim on 429. Leaking the username here would
    violate the "hash-only logging" policy.
    """
    from unittest.mock import MagicMock

    from routers.me import _user_key_func

    # Build a fake Request with an Authorization header.
    token = _make_token("alice_secret")
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}"}
    req.client = MagicMock(host="127.0.0.1")

    key = _user_key_func(req)

    assert isinstance(key, str)
    assert key.startswith("u:"), f"key must start with 'u:', got {key!r}"
    assert "alice_secret" not in key, (
        f"raw username leaked into rate-limit key: {key!r}"
    )
    # Prefix is fixed length (16 hex chars) → total 18.
    assert len(key) == 2 + 16, f"unexpected key length: {len(key)}"

    # Deterministic per-user (stable rate-limit semantics).
    key2 = _user_key_func(req)
    assert key == key2
