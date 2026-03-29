"""
SQLite-based user storage.

Replaces the former users.json flat-file approach with a proper
relational database. Supports automatic migration from JSON on first use.
"""

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/users.db")


class UserDB:
    """Thread-safe SQLite user store.

    Usage::

        db = UserDB()
        db.upsert("alice", {"password_hash": "...", "role": "user"})
        users = db.get_all()
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path or _DEFAULT_DB_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ── Initialisation ────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create the users table if it does not exist."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        username      TEXT PRIMARY KEY,
                        password_hash TEXT,
                        role          TEXT DEFAULT 'user',
                        created_at    TEXT,
                        metadata      TEXT    -- JSON object for extra fields
                    );
                    """
                )
                conn.commit()
                logger.info("[UserDB] Initialised: %s", self._db_path)
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Open a new SQLite connection with WAL mode."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a sqlite3.Row to a user data dict (without username key)."""
        user: Dict[str, Any] = {}
        for key in ("password_hash", "role", "created_at"):
            user[key] = row[key]

        metadata_raw = row["metadata"]
        if metadata_raw:
            try:
                meta = json.loads(metadata_raw)
                if isinstance(meta, dict):
                    user.update(meta)
            except (json.JSONDecodeError, TypeError):
                pass

        return user

    # ── Public API ────────────────────────────────────────────────────

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Return all users as a {username: data} dict."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM users ORDER BY username"
                ).fetchall()
                return {row["username"]: self._row_to_dict(row) for row in rows}
            finally:
                conn.close()

    def get(self, username: str) -> Optional[Dict[str, Any]]:
        """Return user data dict for a given username, or None."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM users WHERE username = ?", (username,)
                ).fetchone()
                return self._row_to_dict(row) if row else None
            finally:
                conn.close()

    def upsert(self, username: str, data: Dict[str, Any]) -> None:
        """Insert or replace a user record.

        Args:
            username: The primary key.
            data: Dict with keys: password_hash, role, created_at, and any extras.
        """
        _known_keys = {"password_hash", "role", "created_at", "metadata"}

        password_hash = data.get("password_hash") or None
        role = data.get("role") or "user"
        created_at = data.get("created_at") or None

        extra = {k: v for k, v in data.items() if k not in _known_keys}
        existing_meta = data.get("metadata")
        if isinstance(existing_meta, dict):
            extra.update(existing_meta)
        metadata_json = json.dumps(extra, ensure_ascii=False, default=str) if extra else None

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO users (username, password_hash, role, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET
                        password_hash = COALESCE(excluded.password_hash, users.password_hash),
                        role          = COALESCE(excluded.role, users.role),
                        created_at    = COALESCE(excluded.created_at, users.created_at),
                        metadata      = COALESCE(excluded.metadata, users.metadata)
                    """,
                    (username, password_hash, role, created_at, metadata_json),
                )
                conn.commit()
            finally:
                conn.close()

    def delete(self, username: str) -> bool:
        """Delete a user by username. Returns True if a row was deleted."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM users WHERE username = ?", (username,))
                deleted = conn.execute("SELECT changes()").fetchone()[0]
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

    def count(self) -> int:
        """Return total number of users."""
        with self._lock:
            conn = self._connect()
            try:
                return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            finally:
                conn.close()

    # ── Migration ─────────────────────────────────────────────────────

    def migrate_from_json(self, json_path: str) -> int:
        """Import users from a legacy users.json file.

        The JSON file is expected to have the structure::

            {"username": {"password_hash": "...", "role": "user", ...}, ...}

        After successful migration the JSON file is renamed to
        ``users.json.migrated`` to prevent re-import.

        Returns:
            Number of users imported.
        """
        json_path = Path(json_path)
        if not json_path.exists():
            logger.debug("[UserDB] No JSON file to migrate: %s", json_path)
            return 0

        migrated_marker = json_path.with_suffix(".json.migrated")
        if migrated_marker.exists():
            logger.debug("[UserDB] JSON already migrated (marker exists)")
            return 0

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict) or not data:
                logger.info("[UserDB] JSON file empty or invalid, nothing to migrate")
                return 0

            for username, user_data in data.items():
                if isinstance(user_data, dict):
                    self.upsert(username, user_data)

            logger.info(
                "[UserDB] Migrated %d users from %s", len(data), json_path
            )

            try:
                os.rename(str(json_path), str(migrated_marker))
                logger.info("[UserDB] Renamed %s -> %s", json_path, migrated_marker)
            except OSError as e:
                logger.warning("[UserDB] Could not rename JSON file: %s", e)

            return len(data)

        except Exception as e:
            logger.error("[UserDB] Migration failed: %s", e)
            return 0
