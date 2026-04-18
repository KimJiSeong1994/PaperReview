"""
Tests for BookmarkDB.get_by_username().

Covers: matching rows, validation rejection, empty result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sys
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.storage.bookmark_db import BookmarkDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_db(db: BookmarkDB, rows: list[dict]) -> None:
    """Upsert *rows* into *db* for fixture setup."""
    for row in rows:
        db.upsert(row)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_by_username_returns_only_matching_rows(tmp_path: Path) -> None:
    """get_by_username must return only rows whose username matches."""
    db = BookmarkDB(db_path=tmp_path / "bookmarks.db")
    _seed_db(db, [
        {
            "id": "bm_alice_1",
            "username": "alice",
            "topic": "ML",
            "created_at": "2024-01-01T00:00:00",
        },
        {
            "id": "bm_alice_2",
            "username": "alice",
            "topic": "NLP",
            "created_at": "2024-01-02T00:00:00",
        },
        {
            "id": "bm_bob_1",
            "username": "bob",
            "topic": "Vision",
            "created_at": "2024-01-03T00:00:00",
        },
    ])

    result = db.get_by_username("alice")

    assert len(result) == 2, f"Expected 2 rows for alice, got {len(result)}"
    usernames = {r["username"] for r in result}
    assert usernames == {"alice"}, "All returned rows must belong to alice"

    ids = [r["id"] for r in result]
    assert "bm_bob_1" not in ids, "Bob's bookmark must not appear in alice's results"


def test_get_by_username_rejects_invalid_username(tmp_path: Path) -> None:
    """get_by_username must raise ValueError for usernames with unsafe characters."""
    db = BookmarkDB(db_path=tmp_path / "bookmarks.db")

    with pytest.raises(ValueError, match="Invalid username"):
        db.get_by_username("../etc/passwd")

    with pytest.raises(ValueError, match="Invalid username"):
        db.get_by_username("")

    with pytest.raises(ValueError, match="Invalid username"):
        db.get_by_username("alice@example.com")


def test_get_by_username_empty_when_no_match(tmp_path: Path) -> None:
    """get_by_username returns an empty list when no bookmarks match."""
    db = BookmarkDB(db_path=tmp_path / "bookmarks.db")
    _seed_db(db, [
        {
            "id": "bm_only",
            "username": "alice",
            "topic": "AI",
            "created_at": "2024-01-01T00:00:00",
        },
    ])

    result = db.get_by_username("nobody")

    assert result == [], f"Expected empty list, got {result}"
