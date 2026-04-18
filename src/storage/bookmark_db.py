"""
SQLite-based bookmark storage.

Replaces the former bookmarks.json flat-file approach with a proper
relational database. Supports automatic migration from JSON on first use.
"""

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.events.contracts import assert_valid_username

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/bookmarks.db")


class BookmarkDB:
    """Thread-safe SQLite bookmark store.

    Usage::

        db = BookmarkDB()
        db.upsert(bookmark_dict)
        bookmarks = db.get_all_by_user("alice")
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path or _DEFAULT_DB_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ── Initialisation ────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS bookmarks (
                        id           TEXT PRIMARY KEY,
                        username     TEXT,
                        topic        TEXT,
                        title        TEXT,
                        papers       TEXT,       -- JSON array
                        report       TEXT,
                        notes        TEXT,
                        highlights   TEXT,       -- JSON array
                        share_token  TEXT,
                        citation_tree TEXT,      -- JSON object
                        created_at   TEXT,
                        updated_at   TEXT,
                        metadata     TEXT        -- JSON object for extra fields
                    );

                    CREATE INDEX IF NOT EXISTS idx_bookmarks_username
                        ON bookmarks (username);

                    CREATE INDEX IF NOT EXISTS idx_bookmarks_share_token
                        ON bookmarks (share_token);
                    """
                )
                conn.commit()
                logger.info("[BookmarkDB] Initialised: %s", self._db_path)
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
        """Convert a sqlite3.Row back to a bookmark dict."""
        bm: Dict[str, Any] = {}

        # Scalar fields
        for key in ("id", "username", "topic", "title", "report",
                    "notes", "share_token", "created_at", "updated_at"):
            bm[key] = row[key]

        # JSON fields
        for json_key in ("papers", "highlights", "citation_tree"):
            raw = row[json_key]
            if raw:
                try:
                    bm[json_key] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    bm[json_key] = [] if json_key != "citation_tree" else {}
            else:
                bm[json_key] = [] if json_key != "citation_tree" else None

        # Merge extra metadata back into top-level dict
        metadata_raw = row["metadata"]
        if metadata_raw:
            try:
                meta = json.loads(metadata_raw)
                if isinstance(meta, dict):
                    bm.update(meta)
            except (json.JSONDecodeError, TypeError):
                pass

        # Normalise legacy field: report_markdown alias
        if bm.get("report") is not None and "report_markdown" not in bm:
            bm["report_markdown"] = bm["report"]

        return bm

    @staticmethod
    def _dict_to_row(bm: Dict[str, Any]) -> tuple:
        """Convert a bookmark dict to an INSERT/UPDATE tuple."""
        _known_keys = {
            "id", "username", "topic", "title", "papers", "report",
            "report_markdown", "notes", "highlights", "share_token",
            "citation_tree", "created_at", "updated_at", "metadata",
        }

        bm_id = bm.get("id", "")
        username = bm.get("username") or None
        topic = bm.get("topic") or "General"
        title = bm.get("title", "")

        # papers: accept list or already-serialised string
        papers_raw = bm.get("papers", [])
        if isinstance(papers_raw, list):
            papers_json = json.dumps(papers_raw, ensure_ascii=False)
        else:
            papers_json = str(papers_raw)

        # report: prefer report_markdown alias
        report = bm.get("report_markdown") or bm.get("report") or ""

        notes = bm.get("notes") or None

        highlights_raw = bm.get("highlights", [])
        if isinstance(highlights_raw, list):
            highlights_json = json.dumps(highlights_raw, ensure_ascii=False) if highlights_raw else None
        else:
            highlights_json = str(highlights_raw) if highlights_raw else None

        share_token = bm.get("share_token") or None

        citation_tree_raw = bm.get("citation_tree")
        if citation_tree_raw is not None:
            if isinstance(citation_tree_raw, (dict, list)):
                citation_tree_json = json.dumps(citation_tree_raw, ensure_ascii=False)
            else:
                citation_tree_json = str(citation_tree_raw)
        else:
            citation_tree_json = None

        created_at = bm.get("created_at") or None
        updated_at = bm.get("updated_at") or None

        # Extra fields not in known keys go into metadata
        extra = {k: v for k, v in bm.items() if k not in _known_keys}
        existing_meta = bm.get("metadata")
        if isinstance(existing_meta, dict):
            extra.update(existing_meta)
        metadata_json = json.dumps(extra, ensure_ascii=False, default=str) if extra else None

        return (
            bm_id, username, topic, title, papers_json, report,
            notes, highlights_json, share_token, citation_tree_json,
            created_at, updated_at, metadata_json,
        )

    # ── Public API ────────────────────────────────────────────────────

    def get_all_by_user(self, username: str) -> List[Dict[str, Any]]:
        """Return all bookmarks for a given username, newest first."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM bookmarks WHERE username = ? ORDER BY created_at DESC",
                    (username,),
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
            finally:
                conn.close()

    def get_by_username(self, username: str) -> List[Dict[str, Any]]:
        """Return all bookmarks for *username*, newest first.

        Parameters
        ----------
        username:
            Owner of the bookmarks. Validated via
            :func:`~src.events.contracts.assert_valid_username` before any
            SQL is executed.

        Returns
        -------
        list[dict]
            Zero or more bookmark dicts, ordered by ``created_at DESC``.

        Raises
        ------
        ValueError
            If *username* does not match the safe pattern
            ``^[A-Za-z0-9_\\-]{1,64}$``.
        """
        assert_valid_username(username)
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM bookmarks WHERE username = ? ORDER BY created_at DESC",
                    (username,),
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
            finally:
                conn.close()

    def get_all(self) -> List[Dict[str, Any]]:
        """Return all bookmarks across all users, newest first."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM bookmarks ORDER BY created_at DESC"
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
            finally:
                conn.close()

    def get_by_id(self, bookmark_id: str) -> Optional[Dict[str, Any]]:
        """Return a single bookmark by id, or None if not found."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)
                ).fetchone()
                return self._row_to_dict(row) if row else None
            finally:
                conn.close()

    def get_by_share_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Return a bookmark by its share_token, or None."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM bookmarks WHERE share_token = ?", (token,)
                ).fetchone()
                return self._row_to_dict(row) if row else None
            finally:
                conn.close()

    def upsert(self, bm: Dict[str, Any]) -> None:
        """Insert or replace a bookmark dict."""
        row = self._dict_to_row(bm)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO bookmarks
                        (id, username, topic, title, papers, report,
                         notes, highlights, share_token, citation_tree,
                         created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        username      = COALESCE(excluded.username, bookmarks.username),
                        topic         = COALESCE(excluded.topic, bookmarks.topic),
                        title         = COALESCE(excluded.title, bookmarks.title),
                        papers        = COALESCE(excluded.papers, bookmarks.papers),
                        report        = COALESCE(excluded.report, bookmarks.report),
                        notes         = excluded.notes,
                        highlights    = excluded.highlights,
                        share_token   = excluded.share_token,
                        citation_tree = excluded.citation_tree,
                        updated_at    = excluded.updated_at,
                        metadata      = COALESCE(excluded.metadata, bookmarks.metadata)
                    """,
                    row,
                )
                conn.commit()
            finally:
                conn.close()

    def delete(self, bookmark_id: str) -> bool:
        """Delete a bookmark by id. Returns True if a row was deleted."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
                deleted = conn.execute("SELECT changes()").fetchone()[0]
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

    def delete_by_username(self, username: str) -> int:
        """Delete all bookmarks owned by *username*.

        Parameters
        ----------
        username:
            Owner of the bookmarks. Validated via
            :func:`~src.events.contracts.assert_valid_username` before any
            SQL is executed.

        Returns
        -------
        int
            Number of rows deleted. ``0`` when the user has no bookmarks.

        Raises
        ------
        ValueError
            If *username* does not match the safe pattern
            ``^[A-Za-z0-9_\\-]{1,64}$``.
        """
        assert_valid_username(username)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM bookmarks WHERE username = ?", (username,)
                )
                deleted = conn.execute("SELECT changes()").fetchone()[0]
                conn.commit()
                return int(deleted)
            finally:
                conn.close()

    def count(self) -> int:
        """Return total number of bookmarks."""
        with self._lock:
            conn = self._connect()
            try:
                return conn.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
            finally:
                conn.close()

    # ── Migration ─────────────────────────────────────────────────────

    def migrate_from_json(self, json_path: str) -> int:
        """Import bookmarks from a legacy bookmarks.json file.

        The JSON file is expected to have the structure::

            {"bookmarks": [{...}, {...}, ...]}

        After successful migration the JSON file is renamed to
        ``bookmarks.json.migrated`` to prevent re-import.

        Returns:
            Number of bookmarks imported.
        """
        json_path = Path(json_path)
        if not json_path.exists():
            logger.debug("[BookmarkDB] No JSON file to migrate: %s", json_path)
            return 0

        migrated_marker = json_path.with_suffix(".json.migrated")
        if migrated_marker.exists():
            logger.debug("[BookmarkDB] JSON already migrated (marker exists)")
            return 0

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            bookmarks = data.get("bookmarks", []) if isinstance(data, dict) else data
            if not bookmarks:
                logger.info("[BookmarkDB] JSON file empty, nothing to migrate")
                return 0

            for bm in bookmarks:
                self.upsert(bm)

            logger.info(
                "[BookmarkDB] Migrated %d bookmarks from %s",
                len(bookmarks),
                json_path,
            )

            try:
                os.rename(str(json_path), str(migrated_marker))
                logger.info(
                    "[BookmarkDB] Renamed %s -> %s", json_path, migrated_marker
                )
            except OSError as e:
                logger.warning("[BookmarkDB] Could not rename JSON file: %s", e)

            return len(bookmarks)

        except Exception as e:
            logger.error("[BookmarkDB] Migration failed: %s", e)
            return 0
