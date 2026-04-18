"""
SQLite schema migrations for the event-driven lock-in infrastructure.

Two data-stores are provisioned here:

* ``events.db`` — append-only ``user_events`` ledger consumed by the
  :class:`~src.events.event_bus.EventBus`. Schema matches
  ``99-final-impl.md`` §2.2 exactly.
* ``profile.db`` — placeholder ``user_rubric`` table owned by the Rubric
  story. Only the primary key column is created here; the full schema is
  added by downstream migrations when the rubric feature is implemented.

Both helpers are idempotent and safe to call on every startup. They enable
SQLite WAL journaling for concurrent reads during writes, set
``synchronous=NORMAL`` for a good durability/throughput balance, and
enforce foreign keys.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

# Authority: 99-final-impl.md §2.2 / 99-final-roadmap.md §2.2
_EVENTS_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS user_events (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      TEXT NOT NULL,
        event_type   TEXT NOT NULL,
        payload      TEXT NOT NULL,
        paper_id     TEXT,
        created_at   TEXT NOT NULL,
        source       TEXT DEFAULT 'app'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_user_time
        ON user_events(user_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_type
        ON user_events(event_type)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_paper
        ON user_events(paper_id) WHERE paper_id IS NOT NULL
    """,
)

# Minimal placeholder — the Rubric story owns the full schema.
_PROFILE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS user_rubric (
        username TEXT PRIMARY KEY
    )
    """,
)


# ---------------------------------------------------------------------------
# Pragmas
# ---------------------------------------------------------------------------


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Enable WAL, NORMAL sync, and foreign keys on *conn*."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")


def _ensure_db(db_path: Path, statements: tuple[str, ...]) -> None:
    """Create *db_path*'s parent directory and run *statements* idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        _apply_pragmas(conn)
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_events_db(db_path: Path) -> None:
    """
    Create (or upgrade) the events database at *db_path*.

    The following objects are created when missing:

    * ``user_events`` table
    * ``idx_events_user_time`` — covering ``(user_id, created_at)`` for
      per-user timeline queries.
    * ``idx_events_type`` — for event-type analytics.
    * ``idx_events_paper`` — partial index (``WHERE paper_id IS NOT NULL``)
      that accelerates paper-scoped lookups without bloating the index.

    The function is idempotent: calling it on an already-migrated DB is a
    no-op.

    Parameters
    ----------
    db_path:
        Target ``events.db`` path. Parent directories are created as
        needed.
    """
    _ensure_db(db_path, _EVENTS_DDL)
    logger.debug("ensure_events_db: migrated %s", db_path)


def ensure_profile_db(db_path: Path) -> None:
    """
    Create the profile database placeholder at *db_path*.

    Only the minimal ``user_rubric`` primary-key column is provisioned
    here; the full schema (weights, timestamps, versions) is added by the
    Rubric story's migrations. This exists so the rest of the system can
    open the DB at startup without racing the first rubric write.

    Parameters
    ----------
    db_path:
        Target ``profile.db`` path. Parent directories are created as
        needed.
    """
    _ensure_db(db_path, _PROFILE_DDL)
    logger.debug("ensure_profile_db: migrated %s", db_path)


__all__ = ["ensure_events_db", "ensure_profile_db"]
