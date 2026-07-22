"""Focused contract + computation tests for the admin activity report.

Builds tiny throwaway SQLite stores, runs ``build_activity_report`` with a
fixed clock, and asserts the frozen response shape plus a couple of computed
values (CTR math, signups_series sum, review pipeline aggregation).
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from src.analytics import review_store
from src.analytics.activity_report import build_activity_report

# KST 12:00 on 2026-07-22 → 7-day window starts KST midnight 2026-07-16.
NOW = dt.datetime(2026, 7, 22, 3, 0, 0, tzinfo=dt.timezone.utc)


def _iso(y, m, d, h=0) -> str:
    return dt.datetime(y, m, d, h, tzinfo=dt.timezone.utc).isoformat()


def _make_events_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE user_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            event_type TEXT NOT NULL, payload TEXT NOT NULL, paper_id TEXT,
            created_at TEXT NOT NULL, source TEXT DEFAULT 'app')"""
    )
    rows = [
        ("alice", "query_submit", json.dumps({"query_hash": "h1"}), _iso(2026, 7, 20, 1)),
        ("alice", "query_submit", json.dumps({"query_hash": "h1"}), _iso(2026, 7, 20, 2)),
        ("alice", "query_submit", json.dumps({"query_hash": "h2"}), _iso(2026, 7, 21, 1)),
        ("alice", "search_click", json.dumps({}), _iso(2026, 7, 20, 3)),
        ("alice", "bookmark_add", json.dumps({}), _iso(2026, 7, 20, 4)),
        ("alice", "bookmark_add", json.dumps({}), _iso(2026, 7, 21, 4)),
        ("alice", "bookmark_remove", json.dumps({}), _iso(2026, 7, 21, 5)),
        ("alice", "login", json.dumps({}), _iso(2026, 7, 22, 2)),  # today → DAU
        ("bob", "login", json.dumps({}), _iso(2026, 7, 22, 2)),    # today → DAU
        ("carol", "query_submit", json.dumps({"query_hash": "h3"}), _iso(2026, 7, 17, 1)),
    ]
    conn.executemany(
        "INSERT INTO user_events (user_id, event_type, payload, created_at) VALUES (?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def _make_users_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE users (username TEXT PRIMARY KEY, password_hash TEXT,
            role TEXT DEFAULT 'user', created_at TEXT, metadata TEXT)"""
    )
    conn.executemany(
        "INSERT INTO users (username, created_at) VALUES (?, ?)",
        [
            ("alice", _iso(2026, 7, 20)),   # in window
            ("bob", _iso(2026, 7, 17)),     # in window
            ("carol", _iso(2026, 1, 1)),    # out of window
            ("legacy", ""),                 # empty created_at → skipped
        ],
    )
    conn.commit()
    conn.close()


def _make_bookmarks_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE bookmarks (id TEXT PRIMARY KEY, username TEXT, topic TEXT,
            created_at TEXT, updated_at TEXT)"""
    )
    conn.executemany(
        "INSERT INTO bookmarks (id, topic, created_at) VALUES (?, ?, ?)",
        [
            ("b1", "RAG", _iso(2026, 7, 20)),
            ("b2", "RAG", _iso(2026, 7, 21)),
            ("b3", "GNN", _iso(2026, 7, 20)),
            ("b4", "RAG", _iso(2026, 1, 1)),  # out of window
        ],
    )
    conn.commit()
    conn.close()


def _make_reviews_db(path: Path) -> None:
    review_store.ensure_review_db(path)
    conn = sqlite3.connect(path)
    conn.executemany(
        """INSERT INTO review_sessions
           (session_id, username, status, created_at, completed_at,
            num_papers, num_researchers, fast_mode, error)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        [
            # completed full review, 300s duration
            ("review_A", "alice", "completed", _iso(2026, 7, 20, 0),
             dt.datetime(2026, 7, 20, 0, 5, tzinfo=dt.timezone.utc).isoformat(),
             2, 3, 0, None),
            # failed fast review
            ("review_B", "bob", "failed", _iso(2026, 7, 21, 0), None, 1, 3, 1, "boom"),
        ],
    )
    conn.commit()
    conn.close()


def _build(tmp_path: Path, days: int = 7) -> dict:
    events_db = tmp_path / "events.db"
    users_db = tmp_path / "users.db"
    bookmarks_db = tmp_path / "bookmarks.db"
    reviews_db = tmp_path / "reviews.db"
    _make_events_db(events_db)
    _make_users_db(users_db)
    _make_bookmarks_db(bookmarks_db)
    _make_reviews_db(reviews_db)
    return build_activity_report(
        events_db, users_db, bookmarks_db, reviews_db, days=days, now=NOW
    )


def test_contract_shape(tmp_path):
    r = _build(tmp_path)
    for key in (
        "window_days", "generated_at", "growth", "active_users", "search",
        "bookmarks", "reviews", "recent_activity_by_user",
        "metric_definitions", "notes",
    ):
        assert key in r, f"missing top-level key {key}"
    assert r["window_days"] == 7
    assert isinstance(r["notes"], list)
    assert isinstance(r["metric_definitions"], dict)
    for sub in ("dau", "wau", "mau", "stickiness", "active_series", "basis"):
        assert sub in r["active_users"]


def test_growth_signups_sum(tmp_path):
    g = _build(tmp_path)["growth"]
    assert g["total_users"] == 4
    assert g["new_users_in_window"] == 2  # alice + bob (carol old, legacy empty)
    assert sum(s["count"] for s in g["signups_series"]) == g["new_users_in_window"]


def test_search_ctr_math(tmp_path):
    s = _build(tmp_path)["search"]
    assert s["total_queries"] == 4          # alice x3 + carol x1, all within 7d KST window
    assert s["click_through_rate"] == 0.25  # 1 click / 4 queries
    # top query is the repeated hash h1 (count 2), by hash since text isn't stored
    assert s["top_queries"][0] == {"query": "h1", "count": 2}


def test_active_users(tmp_path):
    a = _build(tmp_path)["active_users"]
    assert a["dau"] == 2   # alice + bob logged in "today"
    assert a["mau"] >= 3   # alice, bob, carol all have events in last 30d
    assert 0.0 <= a["stickiness"] <= 1.0


def test_bookmarks(tmp_path):
    b = _build(tmp_path)["bookmarks"]
    assert b["net_in_window"] == 1  # 2 adds - 1 remove
    assert {"topic": "RAG", "count": 2} in b["top_topics"]


def test_reviews_pipeline(tmp_path):
    rv = _build(tmp_path)["reviews"]
    assert rv["started"] == 2
    assert rv["completed"] == 1
    assert rv["failed"] == 1
    assert rv["success_rate"] == 0.5
    assert rv["duration_p50_s"] == 300.0
    assert rv["researcher_hist"] == {"3": 2}
    assert rv["fast_mode_share"] == 0.5
    # full: 0.40 * 3 researchers + fast: 0.05 = 1.25
    assert rv["cost_estimate_usd"] == 1.25
    assert any(f["reason"] == "boom" for f in rv["failure_reasons"])
