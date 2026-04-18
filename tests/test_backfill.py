"""
Tests for scripts/backfill_events.py.

All tests use tmp_path for both DBs and seed fixtures instead of real data.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

# Ensure project root is importable (mirrors conftest.py approach)
import sys
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.backfill_events import run_backfill
from src.events.migrations import ensure_events_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_bookmarks_db(path: Path, rows: list[dict]) -> None:
    """Create a minimal bookmarks.db with *rows*."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE bookmarks (
            id           TEXT PRIMARY KEY,
            username     TEXT,
            topic        TEXT,
            title        TEXT,
            papers       TEXT,
            report       TEXT,
            notes        TEXT,
            highlights   TEXT,
            share_token  TEXT,
            citation_tree TEXT,
            created_at   TEXT,
            updated_at   TEXT,
            metadata     TEXT
        )
        """
    )
    for row in rows:
        conn.execute(
            """
            INSERT INTO bookmarks
                (id, username, topic, title, papers, report, notes,
                 highlights, share_token, citation_tree, created_at,
                 updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("id", "bm_001"),
                row.get("username", "alice"),
                row.get("topic", "AI"),
                row.get("title", ""),
                row.get("papers", None),
                row.get("report", None),
                row.get("notes", None),
                row.get("highlights", None),
                row.get("share_token", None),
                row.get("citation_tree", None),
                row.get("created_at", "2024-01-01T00:00:00"),
                row.get("updated_at", None),
                row.get("metadata", None),
            ),
        )
    conn.commit()
    conn.close()


def _count_events(events_db: Path) -> int:
    """Return total rows in user_events."""
    conn = sqlite3.connect(str(events_db))
    n = conn.execute("SELECT COUNT(*) FROM user_events").fetchone()[0]
    conn.close()
    return n


def _fetch_events(events_db: Path) -> list[dict]:
    """Return all rows from user_events as dicts."""
    conn = sqlite3.connect(str(events_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM user_events").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dry_run_does_not_insert(tmp_path: Path) -> None:
    """--dry-run must count events but not insert any rows."""
    bm_db = tmp_path / "bookmarks.db"
    ev_db = tmp_path / "events.db"

    _create_bookmarks_db(bm_db, [
        {"id": "bm_1", "username": "alice", "topic": "ML", "report": "some report"},
    ])

    counts = run_backfill(bm_db, ev_db, dry_run=True)

    assert _count_events(ev_db) == 0, "dry-run must not insert any rows"
    assert counts["total"] > 0, "dry-run should still count events"


def test_backfill_is_idempotent(tmp_path: Path) -> None:
    """Running backfill twice must not duplicate rows."""
    bm_db = tmp_path / "bookmarks.db"
    ev_db = tmp_path / "events.db"

    _create_bookmarks_db(bm_db, [
        {
            "id": "bm_2",
            "username": "bob",
            "topic": "NLP",
            "report": "report text",
            "highlights": json.dumps([{"text": "note A"}, {"text": "note B"}]),
        },
    ])

    counts1 = run_backfill(bm_db, ev_db, dry_run=False)
    after_first = _count_events(ev_db)

    counts2 = run_backfill(bm_db, ev_db, dry_run=False)
    after_second = _count_events(ev_db)

    assert after_first == after_second, (
        f"Second run inserted extra rows: first={after_first} second={after_second}"
    )
    assert counts2["total"] == 0, "Second run should report 0 new events"
    assert counts2["skipped"] > 0, "Second run should report skipped (dup) events"


def test_bookmark_add_event_shape(tmp_path: Path) -> None:
    """After backfill, each bookmark_add row must have dedup_key and topic."""
    bm_db = tmp_path / "bookmarks.db"
    ev_db = tmp_path / "events.db"

    _create_bookmarks_db(bm_db, [
        {"id": "bm_shape", "username": "carol", "topic": "Vision"},
    ])

    run_backfill(bm_db, ev_db, dry_run=False)

    rows = _fetch_events(ev_db)
    ba_rows = [r for r in rows if r["event_type"] == "bookmark_add"]
    assert len(ba_rows) == 1

    payload = json.loads(ba_rows[0]["payload"])
    assert "dedup_key" in payload, "payload must contain dedup_key"
    assert payload["dedup_key"] == "bookmark:bm_shape"
    assert "topic" in payload, "payload must contain topic"
    assert payload["topic"] == "Vision"
    assert ba_rows[0]["source"] == "backfill"


def test_highlights_generate_events(tmp_path: Path) -> None:
    """A bookmark with 3 highlights must produce 3 highlight_create events."""
    bm_db = tmp_path / "bookmarks.db"
    ev_db = tmp_path / "events.db"

    highlights = [
        {"text": "highlight one"},
        {"text": "highlight two"},
        {"text": "highlight three"},
    ]
    _create_bookmarks_db(bm_db, [
        {
            "id": "bm_hl",
            "username": "dave",
            "topic": "RL",
            "highlights": json.dumps(highlights),
        },
    ])

    run_backfill(bm_db, ev_db, dry_run=False)

    rows = _fetch_events(ev_db)
    hl_rows = [r for r in rows if r["event_type"] == "highlight_create"]
    assert len(hl_rows) == 3, f"Expected 3 highlight_create events, got {len(hl_rows)}"

    dedup_keys = {json.loads(r["payload"])["dedup_key"] for r in hl_rows}
    assert dedup_keys == {
        "highlight:bm_hl:0",
        "highlight:bm_hl:1",
        "highlight:bm_hl:2",
    }
