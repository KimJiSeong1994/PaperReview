"""
Idempotent backfill script: reads bookmarks.db and inserts historical
events into events.db.

For each bookmark row the script emits:
  * BOOKMARK_ADD   — always (one per bookmark)
  * HIGHLIGHT_CREATE — one per entry in the ``highlights`` JSON array
  * REVIEW_CREATE  — one if the ``report`` field is non-empty

The script is idempotent: a ``dedup_key`` is stored inside every
payload's JSON so that a second run can detect already-inserted rows
via ``json_extract(payload, '$.dedup_key')``.

Usage::

    python scripts/backfill_events.py [options]

Options
-------
--dry-run             Count events; do not insert.
--bookmarks-db PATH   Path to bookmarks.db (default: data/bookmarks.db).
--events-db PATH      Path to events.db  (default: data/events.db).
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on the path when run directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.events.event_types import EventType, UserEvent
from src.events.migrations import ensure_events_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_BOOKMARKS_DB = _REPO_ROOT / "data" / "bookmarks.db"
_DEFAULT_EVENTS_DB = _REPO_ROOT / "data" / "events.db"
_FALLBACK_USERNAME = "unknown"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_bookmarks(path: Path) -> sqlite3.Connection:
    """Return a read-only connection to *bookmarks.db*."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _open_events(path: Path) -> sqlite3.Connection:
    """Return a read-write connection to *events.db*."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _already_backfilled(events_conn: sqlite3.Connection, dedup_key: str) -> bool:
    """Return True if a backfill row with *dedup_key* already exists."""
    row = events_conn.execute(
        "SELECT 1 FROM user_events WHERE source = 'backfill' "
        "AND json_extract(payload, '$.dedup_key') = ?",
        (dedup_key,),
    ).fetchone()
    return row is not None


def _insert_event(events_conn: sqlite3.Connection, event: UserEvent) -> None:
    """INSERT a single *event* into user_events (no commit)."""
    payload_json = json.dumps(event.payload, ensure_ascii=False)
    created_at_iso = event.created_at.isoformat()
    events_conn.execute(
        """
        INSERT INTO user_events
            (user_id, event_type, payload, paper_id, created_at, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event.user_id,
            event.event_type.value,
            payload_json,
            event.paper_id,
            created_at_iso,
            event.source,
        ),
    )


# ---------------------------------------------------------------------------
# Core backfill logic
# ---------------------------------------------------------------------------


def _build_bookmark_add(bm_row: sqlite3.Row) -> UserEvent:
    """Construct a BOOKMARK_ADD UserEvent from a bookmark row."""
    bm_id: str = bm_row["id"] or ""
    username: str = bm_row["username"] or _FALLBACK_USERNAME
    topic: str = bm_row["topic"] or ""
    created_at_str: str | None = bm_row["created_at"]

    created_at = (
        datetime.fromisoformat(created_at_str)
        if created_at_str
        else datetime.now(timezone.utc)
    )
    # Ensure timezone-awareness.
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return UserEvent(
        user_id=username,
        event_type=EventType.BOOKMARK_ADD,
        payload={
            "dedup_key": f"bookmark:{bm_id}",
            "bookmark_id": bm_id,
            "topic": topic,
        },
        paper_id=None,
        created_at=created_at,
        source="backfill",
    )


def _build_highlight_creates(bm_row: sqlite3.Row) -> list[UserEvent]:
    """Construct HIGHLIGHT_CREATE events from the highlights JSON array."""
    bm_id: str = bm_row["id"] or ""
    username: str = bm_row["username"] or _FALLBACK_USERNAME
    topic: str = bm_row["topic"] or ""
    highlights_raw: str | None = bm_row["highlights"]
    created_at_str: str | None = bm_row["created_at"]

    if not highlights_raw:
        return []

    try:
        highlights: list = json.loads(highlights_raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "backfill: could not parse highlights JSON for bookmark %s", bm_id
        )
        return []

    if not isinstance(highlights, list):
        return []

    created_at = (
        datetime.fromisoformat(created_at_str)
        if created_at_str
        else datetime.now(timezone.utc)
    )
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    events: list[UserEvent] = []
    for idx, hl in enumerate(highlights):
        dedup_key = f"highlight:{bm_id}:{idx}"
        # Keep payload small — only a few identifying fields.
        hl_payload: dict = {
            "dedup_key": dedup_key,
            "bookmark_id": bm_id,
            "topic": topic,
            "highlight_index": idx,
        }
        if isinstance(hl, dict):
            # Include at most the text snippet to stay well under 8 KB.
            snippet = str(hl.get("text", ""))[:500]
            if snippet:
                hl_payload["text_snippet"] = snippet

        events.append(
            UserEvent(
                user_id=username,
                event_type=EventType.HIGHLIGHT_CREATE,
                payload=hl_payload,
                paper_id=None,
                created_at=created_at,
                source="backfill",
            )
        )

    return events


def _build_review_create(bm_row: sqlite3.Row) -> UserEvent | None:
    """Construct a REVIEW_CREATE event if the bookmark has a non-empty report."""
    bm_id: str = bm_row["id"] or ""
    username: str = bm_row["username"] or _FALLBACK_USERNAME
    topic: str = bm_row["topic"] or ""
    report: str | None = bm_row["report"]
    created_at_str: str | None = bm_row["created_at"]

    if not report or not report.strip():
        return None

    created_at = (
        datetime.fromisoformat(created_at_str)
        if created_at_str
        else datetime.now(timezone.utc)
    )
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return UserEvent(
        user_id=username,
        event_type=EventType.REVIEW_CREATE,
        payload={
            "dedup_key": f"review:{bm_id}",
            "bookmark_id": bm_id,
            "topic": topic,
        },
        paper_id=None,
        created_at=created_at,
        source="backfill",
    )


def run_backfill(
    bookmarks_db: Path,
    events_db: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    """Execute the backfill.

    Parameters
    ----------
    bookmarks_db:
        Path to ``bookmarks.db``.
    events_db:
        Path to ``events.db``.  Will be created / migrated as needed.
    dry_run:
        If ``True``, count events but do not INSERT.

    Returns
    -------
    dict[str, int]
        Keys: ``bookmark_add``, ``highlight_create``, ``review_create``,
        ``skipped`` (already present), ``total``.
    """
    ensure_events_db(events_db)

    bm_conn = _open_bookmarks(bookmarks_db)
    ev_conn = _open_events(events_db)

    counts: dict[str, int] = {
        "bookmark_add": 0,
        "highlight_create": 0,
        "review_create": 0,
        "skipped": 0,
        "total": 0,
    }

    try:
        rows = bm_conn.execute(
            "SELECT * FROM bookmarks ORDER BY created_at ASC"
        ).fetchall()

        logger.info("backfill: found %d bookmark(s) in %s", len(rows), bookmarks_db)

        for bm_row in rows:
            # --- BOOKMARK_ADD ---
            ba_event = _build_bookmark_add(bm_row)
            dedup_ba = ba_event.payload["dedup_key"]
            if _already_backfilled(ev_conn, dedup_ba):
                logger.debug("backfill: skip (dup) %s", dedup_ba)
                counts["skipped"] += 1
            else:
                if not dry_run:
                    _insert_event(ev_conn, ba_event)
                counts["bookmark_add"] += 1
                counts["total"] += 1

            # --- HIGHLIGHT_CREATE ---
            for hl_event in _build_highlight_creates(bm_row):
                dedup_hl = hl_event.payload["dedup_key"]
                if _already_backfilled(ev_conn, dedup_hl):
                    logger.debug("backfill: skip (dup) %s", dedup_hl)
                    counts["skipped"] += 1
                else:
                    if not dry_run:
                        _insert_event(ev_conn, hl_event)
                    counts["highlight_create"] += 1
                    counts["total"] += 1

            # --- REVIEW_CREATE ---
            rc_event = _build_review_create(bm_row)
            if rc_event is not None:
                dedup_rc = rc_event.payload["dedup_key"]
                if _already_backfilled(ev_conn, dedup_rc):
                    logger.debug("backfill: skip (dup) %s", dedup_rc)
                    counts["skipped"] += 1
                else:
                    if not dry_run:
                        _insert_event(ev_conn, rc_event)
                    counts["review_create"] += 1
                    counts["total"] += 1

        if not dry_run:
            ev_conn.commit()
            logger.info("backfill: committed %d event(s) to %s", counts["total"], events_db)

    finally:
        bm_conn.close()
        ev_conn.close()

    return counts


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backfill historical events from bookmarks.db into events.db.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Count events without inserting.",
    )
    p.add_argument(
        "--bookmarks-db",
        default=str(_DEFAULT_BOOKMARKS_DB),
        metavar="PATH",
        help=f"Path to bookmarks.db (default: {_DEFAULT_BOOKMARKS_DB})",
    )
    p.add_argument(
        "--events-db",
        default=str(_DEFAULT_EVENTS_DB),
        metavar="PATH",
        help=f"Path to events.db (default: {_DEFAULT_EVENTS_DB})",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    args = _build_parser().parse_args(argv)
    bookmarks_db = Path(args.bookmarks_db)
    events_db = Path(args.events_db)

    if not bookmarks_db.exists():
        logger.error("backfill: bookmarks DB not found: %s", bookmarks_db)
        sys.exit(1)

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    logger.info("backfill: starting (%s) bookmarks=%s events=%s", mode, bookmarks_db, events_db)

    counts = run_backfill(
        bookmarks_db=bookmarks_db,
        events_db=events_db,
        dry_run=args.dry_run,
    )

    # Final summary line to stdout (as required by spec).
    print(
        f"[backfill {mode}] "
        f"bookmark_add={counts['bookmark_add']} "
        f"highlight_create={counts['highlight_create']} "
        f"review_create={counts['review_create']} "
        f"skipped={counts['skipped']} "
        f"total_new={counts['total']}"
    )


if __name__ == "__main__":
    main()
