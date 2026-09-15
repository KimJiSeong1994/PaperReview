"""
Tests for BookmarkDB read paths: get_by_username(), get_all() and
get_by_share_token().

Covers: matching rows, validation rejection, empty result, the report-free
projection both list methods accept via ``include_reports=False``, and the
share_token column the indexed share lookup reads.
"""

from __future__ import annotations

import sqlite3
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


# ---------------------------------------------------------------------------
# Share token: the indexed column is derived from the `share` metadata
# ---------------------------------------------------------------------------


def _raw_share_token(db: BookmarkDB, bookmark_id: str):
    """Read the share_token column straight out of SQLite."""
    conn = sqlite3.connect(str(db._db_path))
    try:
        row = conn.execute(
            "SELECT share_token FROM bookmarks WHERE id = ?", (bookmark_id,)
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _shared_row(token: str = "sh_token_abc") -> dict:
    return {
        "id": "bm_shared",
        "username": "alice",
        "topic": "ML",
        "created_at": "2024-01-01T00:00:00",
        "share": {
            "token": token,
            "created_at": "2024-01-01T00:00:00",
            "expires_at": "2099-01-01T00:00:00",
        },
    }


def test_upsert_fills_the_share_token_column_from_the_share_metadata(
    tmp_path: Path,
) -> None:
    """Sharing writes `share.token`; the indexed column has to follow it.

    Nothing else writes the column, so if upsert does not derive it the index
    stays empty and every lookup falls back to a scan.
    """
    db = BookmarkDB(db_path=tmp_path / "bookmarks.db")
    _seed_db(db, [_shared_row()])

    assert _raw_share_token(db, "bm_shared") == "sh_token_abc"

    found = db.get_by_share_token("sh_token_abc")
    assert found is not None, "indexed lookup must find the shared bookmark"
    assert found["id"] == "bm_shared"
    assert found["share"]["expires_at"] == "2099-01-01T00:00:00"


def test_dropping_the_share_metadata_clears_the_token_column(tmp_path: Path) -> None:
    """Revoking deletes `share`; the column must not keep the live token."""
    db = BookmarkDB(db_path=tmp_path / "bookmarks.db")
    _seed_db(db, [_shared_row()])

    revoked = _shared_row()
    del revoked["share"]
    _seed_db(db, [revoked])

    assert _raw_share_token(db, "bm_shared") is None
    assert db.get_by_share_token("sh_token_abc") is None


def test_unshared_bookmarks_are_not_reachable_by_an_empty_token(
    tmp_path: Path,
) -> None:
    """A NULL column must not answer to "" or to a missing token."""
    db = BookmarkDB(db_path=tmp_path / "bookmarks.db")
    _seed_db(db, [
        {"id": "bm_private", "username": "alice", "created_at": "2024-01-01T00:00:00"},
    ])

    assert db.get_by_share_token("") is None
    assert db.get_by_share_token(None) is None


def test_get_by_share_token_uses_the_index(tmp_path: Path) -> None:
    """The lookup must hit idx_bookmarks_share_token, not scan the table."""
    db = BookmarkDB(db_path=tmp_path / "bookmarks.db")
    _seed_db(db, [_shared_row()])

    conn = sqlite3.connect(str(db._db_path))
    try:
        plan = " ".join(
            str(r) for r in conn.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM bookmarks WHERE share_token = ?",
                ("sh_token_abc",),
            ).fetchall()
        )
    finally:
        conn.close()

    assert "idx_bookmarks_share_token" in plan, f"not an index lookup: {plan}"


# ---------------------------------------------------------------------------
# Backfill: tokens that predate the column live only in `metadata`
# ---------------------------------------------------------------------------


def _legacy_shared_db(tmp_path: Path) -> Path:
    """A db whose shared bookmark has its token only in the metadata blob."""
    db_path = tmp_path / "bookmarks.db"
    db = BookmarkDB(db_path=db_path)
    _seed_db(db, [_shared_row()])

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE bookmarks SET share_token = NULL")
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_backfill_fills_tokens_that_live_only_in_metadata(tmp_path: Path) -> None:
    """Links shared before the column existed must keep working."""
    db_path = _legacy_shared_db(tmp_path)

    db = BookmarkDB(db_path=db_path)

    assert _raw_share_token(db, "bm_shared") == "sh_token_abc"
    found = db.get_by_share_token("sh_token_abc")
    assert found is not None, "backfilled token must be findable via the index"
    assert found["share"]["token"] == "sh_token_abc", "metadata `share` must survive"


def test_backfill_is_idempotent(tmp_path: Path) -> None:
    """Every process start runs it; the second run must change nothing."""
    db_path = _legacy_shared_db(tmp_path)

    BookmarkDB(db_path=db_path)
    db = BookmarkDB(db_path=db_path)

    assert _raw_share_token(db, "bm_shared") == "sh_token_abc"
    assert db.get_by_share_token("sh_token_abc") is not None


def test_backfill_leaves_rows_that_already_have_a_token_alone(tmp_path: Path) -> None:
    """Only NULL columns are filled — a populated one is never rewritten."""
    db_path = tmp_path / "bookmarks.db"
    db = BookmarkDB(db_path=db_path)
    _seed_db(db, [_shared_row()])

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE bookmarks SET share_token = 'sh_already_set'")
        conn.commit()
    finally:
        conn.close()

    db2 = BookmarkDB(db_path=db_path)

    assert _raw_share_token(db2, "bm_shared") == "sh_already_set"


def test_backfill_ignores_bookmarks_that_were_never_shared(tmp_path: Path) -> None:
    """No `share` in metadata means the column stays NULL."""
    db_path = tmp_path / "bookmarks.db"
    db = BookmarkDB(db_path=db_path)
    _seed_db(db, [
        {
            "id": "bm_private",
            "username": "alice",
            "created_at": "2024-01-01T00:00:00",
            "tags": ["ml"],
        },
    ])

    db2 = BookmarkDB(db_path=db_path)

    assert _raw_share_token(db2, "bm_private") is None
