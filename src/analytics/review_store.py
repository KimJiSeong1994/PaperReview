"""Durable deep-review session ledger for admin activity metrics.

The live deep-review lifecycle keeps sessions in an in-memory dict (24h TTL,
lost on restart). This module adds a small SQLite table so pipeline metrics
(duration, success rate, researcher histogram, failure reasons, cost proxy)
survive restarts and the TTL. It is strictly additive — the in-memory dict
still drives live polling; every write here is best-effort and never raises
into the request/background path.

``created_at`` / ``completed_at`` are stored as UTC-aware ISO-8601 (matching
events.db) so window comparisons and duration math are correct. Best-effort
backfill from ``data/workspace/review_*/metadata.json`` populates historical
rows where a timestamp exists (those legacy rows have no duration/researcher
metadata, so those fields stay NULL).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
REVIEWS_DB_PATH = Path(os.getenv("REVIEWS_DB_PATH", str(DATA_DIR / "reviews.db")))
WORKSPACE_DIR = DATA_DIR / "workspace"

_DDL = """
CREATE TABLE IF NOT EXISTS review_sessions (
    session_id      TEXT PRIMARY KEY,
    username        TEXT,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    completed_at    TEXT,
    num_papers      INTEGER,
    num_researchers INTEGER,
    fast_mode       INTEGER,
    error           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER
)
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_review_db(db_path: Path = REVIEWS_DB_PATH) -> None:
    """Idempotently create the review_sessions table."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_DDL)
        conn.commit()
    finally:
        conn.close()


def record_started(
    session_id: str,
    username: str | None,
    num_papers: int,
    num_researchers: int,
    fast_mode: bool,
    db_path: Path = REVIEWS_DB_PATH,
) -> None:
    """Insert a row when a review starts. Best-effort; never raises."""
    try:
        conn = _connect(db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO review_sessions
                    (session_id, username, status, created_at, num_papers,
                     num_researchers, fast_mode)
                VALUES (?, ?, 'processing', ?, ?, ?, ?)
                """,
                (
                    session_id,
                    username,
                    datetime.now(timezone.utc).isoformat(),
                    num_papers,
                    num_researchers,
                    1 if fast_mode else 0,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # pragma: no cover — durability must never break a review
        logger.exception("review_store.record_started failed for %s", session_id)


def record_finished(
    session_id: str,
    status: str,
    error: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    db_path: Path = REVIEWS_DB_PATH,
) -> None:
    """Update terminal status + completed_at (+error/tokens). Best-effort."""
    try:
        conn = _connect(db_path)
        try:
            conn.execute(
                """
                UPDATE review_sessions
                   SET status = ?, completed_at = ?, error = ?,
                       input_tokens = ?, output_tokens = ?
                 WHERE session_id = ?
                """,
                (
                    status,
                    datetime.now(timezone.utc).isoformat(),
                    error,
                    input_tokens,
                    output_tokens,
                    session_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # pragma: no cover
        logger.exception("review_store.record_finished failed for %s", session_id)


def backfill_from_workspace(
    db_path: Path = REVIEWS_DB_PATH, workspace_dir: Path = WORKSPACE_DIR
) -> int:
    """Best-effort import of completed sessions from workspace metadata.json.

    Only rows with a ``created_at`` timestamp are imported. Legacy metadata has
    no duration/researcher/fast_mode fields, so those stay NULL. Existing rows
    are never overwritten (INSERT OR IGNORE). Never raises; returns count.
    """
    if not workspace_dir.exists():
        return 0
    inserted = 0
    try:
        conn = _connect(db_path)
        try:
            for session_dir in workspace_dir.iterdir():
                if not session_dir.is_dir() or not session_dir.name.startswith("review_"):
                    continue
                meta_file = session_dir / "metadata.json"
                if not meta_file.exists():
                    continue
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                created_at = meta.get("created_at")
                if not created_at:
                    continue  # cannot place it on the timeline — skip silently
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO review_sessions
                        (session_id, username, status, created_at, num_papers)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        session_dir.name,
                        meta.get("username"),
                        meta.get("status", "completed"),
                        created_at,
                        meta.get("num_papers"),
                    ),
                )
                inserted += cur.rowcount or 0
            conn.commit()
        finally:
            conn.close()
    except Exception:  # pragma: no cover
        logger.exception("review_store.backfill_from_workspace failed")
        return inserted
    if inserted:
        logger.info("review_store: backfilled %d review sessions from workspace", inserted)
    return inserted


def load_sessions_since(start_utc: str, db_path: Path = REVIEWS_DB_PATH) -> list[dict[str, Any]]:
    """Return review_sessions rows with ``created_at >= start_utc`` as dicts."""
    try:
        conn = _connect(db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM review_sessions WHERE created_at >= ? ORDER BY created_at",
                (start_utc,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:  # pragma: no cover
        logger.exception("review_store.load_sessions_since failed")
        return []


# ── Initialise + best-effort backfill on import (mirrors storage.py pattern) ──
try:  # pragma: no cover — bootstrap side effect, must never break import
    ensure_review_db()
    backfill_from_workspace()
except Exception:
    logger.exception("review_store bootstrap failed")


__all__ = [
    "REVIEWS_DB_PATH",
    "ensure_review_db",
    "record_started",
    "record_finished",
    "backfill_from_workspace",
    "load_sessions_since",
]
