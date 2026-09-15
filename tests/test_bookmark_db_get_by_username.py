"""
Tests for BookmarkDB read paths: get_by_username() and get_all().

Covers: matching rows, validation rejection, empty result, and the
report-free projection both methods accept via ``include_reports=False``.
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


# ---------------------------------------------------------------------------
# Report-free projection (include_reports=False)
# ---------------------------------------------------------------------------


_BIG_REPORT = "x" * 200_000


def _seeded_db(tmp_path: Path) -> BookmarkDB:
    """A db holding one fat-report bookmark plus a sibling row."""
    db = BookmarkDB(db_path=tmp_path / "bookmarks.db")
    _seed_db(db, [
        {
            "id": "bm_fat",
            "username": "alice",
            "topic": "ML",
            "title": "Fat report",
            "papers": [{"title": "P1"}],
            "notes": "note",
            "report": _BIG_REPORT,
            "created_at": "2024-01-02T00:00:00",
            "num_papers": 1,
        },
        {
            "id": "bm_thin",
            "username": "alice",
            "topic": "NLP",
            "title": "Thin",
            "created_at": "2024-01-01T00:00:00",
        },
    ])
    return db


def _trace_sql(db: BookmarkDB, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture every statement the db executes on its own connections."""
    seen: list[str] = []
    original = db._connect

    def traced():
        conn = original()
        conn.set_trace_callback(seen.append)
        return conn

    monkeypatch.setattr(db, "_connect", traced)
    return seen


@pytest.mark.parametrize("call", ["get_all", "get_by_username"])
def test_projection_never_selects_the_report_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, call: str
) -> None:
    """include_reports=False must omit `report` from SQL, not pop it in Python.

    Popping after ``SELECT *`` still lifts the body out of SQLite, which is the
    cost this projection exists to avoid — so assert on the statement itself.
    """
    db = _seeded_db(tmp_path)
    seen = _trace_sql(db, monkeypatch)

    rows = (
        db.get_all(include_reports=False)
        if call == "get_all"
        else db.get_by_username("alice", include_reports=False)
    )

    selects = [sql for sql in seen if sql.lstrip().upper().startswith("SELECT")]
    assert selects, "expected at least one SELECT to be traced"
    for sql in selects:
        columns = sql.split("SELECT", 1)[1].split("FROM", 1)[0]
        assert "*" not in columns, f"still a star-select: {sql}"
        assert "report" not in columns, f"report column still selected: {sql}"
    for row in rows:
        assert "report" not in row
        assert "report_markdown" not in row


@pytest.mark.parametrize("call", ["get_all", "get_by_username"])
def test_default_still_returns_report_body(tmp_path: Path, call: str) -> None:
    """Callers that render the report (chat, share detail) still get it."""
    db = _seeded_db(tmp_path)

    rows = db.get_all() if call == "get_all" else db.get_by_username("alice")

    fat = next(r for r in rows if r["id"] == "bm_fat")
    assert fat["report"] == _BIG_REPORT
    assert fat["report_markdown"] == _BIG_REPORT


@pytest.mark.parametrize("call", ["get_all", "get_by_username"])
def test_projection_matches_full_read_on_every_other_field(
    tmp_path: Path, call: str
) -> None:
    """The two paths agree on order and on every field except the report."""
    db = _seeded_db(tmp_path)

    if call == "get_all":
        full, summary = db.get_all(), db.get_all(include_reports=False)
    else:
        full = db.get_by_username("alice")
        summary = db.get_by_username("alice", include_reports=False)

    assert [r["id"] for r in full] == [r["id"] for r in summary]
    for full_row, summary_row in zip(full, summary):
        expected = {
            k: v for k, v in full_row.items()
            if k not in ("report", "report_markdown")
        }
        assert summary_row == expected
