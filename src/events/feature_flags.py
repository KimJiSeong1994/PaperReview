"""
Feature flag system with per-user and global DB overrides.

Lookup precedence (highest to lowest):
  1. Per-user DB override  (flag + username match)
  2. Global DB override    (flag match, username IS NULL)
  3. Environment variable  ({FLAG}=true|false)
  4. Default              False

Public surface: is_enabled(), set_override(), and the three flag-name constants.
No get_flag() is exported by design.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flag-name constants
# ---------------------------------------------------------------------------
RUBRIC_MEMORY_ENABLED: str = "RUBRIC_MEMORY_ENABLED"
PROFILE_RANKER_ENABLED: str = "PROFILE_RANKER_ENABLED"
ATLAS_ENABLED: str = "ATLAS_ENABLED"

# ---------------------------------------------------------------------------
# DB path — configurable via env var so tests can isolate
# ---------------------------------------------------------------------------
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "feature_flags.db"

_DDL = """
CREATE TABLE IF NOT EXISTS feature_flags (
    flag        TEXT NOT NULL,
    username    TEXT,
    enabled     INTEGER NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (flag, username)
)
"""


def _db_path() -> Path:
    """Return the active DB path, honouring the FEATURE_FLAGS_DB_PATH env var."""
    env = os.environ.get("FEATURE_FLAGS_DB_PATH")
    return Path(env) if env else _DEFAULT_DB_PATH


@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    """Open a short-lived SQLite connection and ensure the schema exists."""
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), check_same_thread=False)
    try:
        conn.execute(_DDL)
        conn.commit()
        yield conn
    finally:
        conn.close()


def _db_lookup(flag: str, username: str | None) -> bool | None:
    """
    Look up a flag in the DB.

    Uses two explicit queries instead of the ambiguous ``IS ?`` pattern:
      - First, a per-user row (only when *username* is provided).
      - Second, a global row (username IS NULL).

    Returns the stored boolean on a hit, or *None* when no row exists.
    """
    with _connect() as conn:
        # 1. Per-user override
        if username is not None:
            row = conn.execute(
                "SELECT enabled FROM feature_flags WHERE flag = ? AND username = ?",
                (flag, username),
            ).fetchone()
            if row is not None:
                return bool(row[0])

        # 2. Global override (username column is NULL)
        row = conn.execute(
            "SELECT enabled FROM feature_flags WHERE flag = ? AND username IS NULL",
            (flag,),
        ).fetchone()
        if row is not None:
            return bool(row[0])

    return None


def is_enabled(flag: str, username: str | None = None) -> bool:
    """
    Return True if *flag* is enabled, applying the lookup precedence:

    1. Per-user DB override (when *username* is given)
    2. Global DB override
    3. Environment variable ``{flag}`` set to ``"true"`` (case-insensitive)
    4. Default: False

    Parameters
    ----------
    flag:
        One of the module-level flag-name constants (or any custom string).
    username:
        Optional authenticated username for per-user overrides.
    """
    db_result = _db_lookup(flag, username)
    if db_result is not None:
        return db_result

    # Fall back to environment variable
    env_val = os.environ.get(flag, "").strip().lower()
    if env_val in ("true", "1", "yes"):
        return True
    if env_val in ("false", "0", "no"):
        return False

    return False


def set_override(flag: str, enabled: bool, username: str | None = None) -> None:
    """
    Persist a flag override to the DB.

    Parameters
    ----------
    flag:
        Flag name to override.
    enabled:
        Desired state.
    username:
        When provided, the override applies only to that user.
        When *None*, the override is global (applies to all users without
        a per-user row).
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO feature_flags (flag, username, enabled, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(flag, username) DO UPDATE SET
                enabled    = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (flag, username, int(enabled), now),
        )
        conn.commit()
    logger.debug(
        "set_override: flag=%s username=%s enabled=%s", flag, username, enabled
    )
