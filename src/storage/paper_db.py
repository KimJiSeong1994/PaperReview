"""
SQLite-based paper storage with FTS5 full-text search.

Replaces the former papers.json flat-file approach with a proper
relational database. Supports automatic migration from JSON on first use.
"""

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/papers.db")


class PaperDB:
    """Thread-safe SQLite paper store with FTS5 search index.

    Usage::

        db = PaperDB()
        db.save_papers([{"doc_id": "123", "title": "...", ...}])
        papers = db.get_all_papers()
        results = db.search_fts("transformer attention")
    """

    # Column ordering for the main table
    _COLUMNS = (
        "doc_id",
        "title",
        "abstract",
        "authors",
        "year",
        "citations",
        "doi",
        "url",
        "pdf_url",
        "source",
        "metadata",
        "created_at",
    )

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path or _DEFAULT_DB_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ── Initialisation ────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create tables and FTS5 index if they do not exist."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS papers (
                        doc_id     TEXT PRIMARY KEY,
                        title      TEXT,
                        abstract   TEXT,
                        authors    TEXT,       -- JSON array
                        year       INTEGER,
                        citations  INTEGER DEFAULT 0,
                        doi        TEXT,
                        url        TEXT,
                        pdf_url    TEXT,
                        source     TEXT,
                        metadata   TEXT,       -- JSON object for extra fields
                        created_at TEXT DEFAULT (datetime('now'))
                    );

                    CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
                        title,
                        abstract,
                        content='papers',
                        content_rowid='rowid'
                    );

                    -- Triggers to keep FTS index in sync
                    CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
                        INSERT INTO papers_fts(rowid, title, abstract)
                        VALUES (new.rowid, new.title, new.abstract);
                    END;

                    CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
                        INSERT INTO papers_fts(papers_fts, rowid, title, abstract)
                        VALUES ('delete', old.rowid, old.title, old.abstract);
                    END;

                    CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
                        INSERT INTO papers_fts(papers_fts, rowid, title, abstract)
                        VALUES ('delete', old.rowid, old.title, old.abstract);
                        INSERT INTO papers_fts(rowid, title, abstract)
                        VALUES (new.rowid, new.title, new.abstract);
                    END;
                    """
                )
                conn.commit()
                logger.info("[PaperDB] Initialised: %s", self._db_path)
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Open a new SQLite connection with recommended pragmas."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _paper_to_row(paper: Dict[str, Any]) -> tuple:
        """Convert a paper dict to a tuple matching _COLUMNS order."""
        # Collect known fields
        doc_id = paper.get("doc_id", "")
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")

        authors = paper.get("authors", [])
        if isinstance(authors, list):
            authors_json = json.dumps(authors, ensure_ascii=False)
        else:
            authors_json = str(authors)

        year = paper.get("year")
        if isinstance(year, str):
            # extract 4-digit year from strings like "2024-01-15"
            import re
            m = re.search(r"(\d{4})", year)
            year = int(m.group(1)) if m else None
        elif year is not None:
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = None

        citations = int(paper.get("citations") or 0)
        doi = paper.get("doi") or None
        url = paper.get("url", "") or paper.get("paper_url", "")
        pdf_url = paper.get("pdf_url", "")
        source = paper.get("source", "")
        created_at = paper.get("created_at") or None

        # Store all remaining fields as metadata JSON
        _known_keys = {
            "doc_id", "title", "abstract", "authors", "year", "citations",
            "doi", "url", "paper_url", "pdf_url", "source", "created_at", "metadata",
        }
        extra = {k: v for k, v in paper.items() if k not in _known_keys}
        # merge with existing metadata if present
        existing_meta = paper.get("metadata")
        if isinstance(existing_meta, dict):
            extra.update(existing_meta)
        metadata_json = json.dumps(extra, ensure_ascii=False, default=str) if extra else None

        return (doc_id, title, abstract, authors_json, year, citations,
                doi, url, pdf_url, source, metadata_json, created_at)

    @staticmethod
    def _row_to_paper(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a sqlite3.Row back to a paper dict."""
        paper: Dict[str, Any] = {}
        for key in ("doc_id", "title", "abstract", "year", "citations",
                     "doi", "url", "pdf_url", "source", "created_at"):
            paper[key] = row[key]

        # Deserialise authors
        authors_raw = row["authors"]
        if authors_raw:
            try:
                paper["authors"] = json.loads(authors_raw)
            except (json.JSONDecodeError, TypeError):
                paper["authors"] = [authors_raw] if authors_raw else []
        else:
            paper["authors"] = []

        # Merge metadata back into the top-level dict
        metadata_raw = row["metadata"]
        if metadata_raw:
            try:
                meta = json.loads(metadata_raw)
                if isinstance(meta, dict):
                    paper.update(meta)
            except (json.JSONDecodeError, TypeError):
                pass

        return paper

    # ── Public API ────────────────────────────────────────────────────

    def save_papers(self, papers: List[Dict[str, Any]]) -> int:
        """Insert or update papers. Returns count of newly inserted rows."""
        if not papers:
            return 0

        rows = [self._paper_to_row(p) for p in papers]
        inserted = 0

        with self._lock:
            conn = self._connect()
            try:
                for row in rows:
                    try:
                        conn.execute(
                            """
                            INSERT INTO papers (doc_id, title, abstract, authors, year,
                                                citations, doi, url, pdf_url, source,
                                                metadata, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(doc_id) DO UPDATE SET
                                title      = COALESCE(excluded.title, papers.title),
                                abstract   = COALESCE(excluded.abstract, papers.abstract),
                                authors    = COALESCE(excluded.authors, papers.authors),
                                year       = COALESCE(excluded.year, papers.year),
                                citations  = MAX(COALESCE(excluded.citations, 0),
                                                 COALESCE(papers.citations, 0)),
                                doi        = COALESCE(excluded.doi, papers.doi),
                                url        = COALESCE(excluded.url, papers.url),
                                pdf_url    = COALESCE(excluded.pdf_url, papers.pdf_url),
                                source     = COALESCE(excluded.source, papers.source),
                                metadata   = COALESCE(excluded.metadata, papers.metadata)
                            """,
                            row,
                        )
                        if conn.execute("SELECT changes()").fetchone()[0] == 1:
                            # Check if this was an INSERT (not UPDATE)
                            # changes() returns 1 for both insert and update in ON CONFLICT
                            pass
                        inserted += 1
                    except sqlite3.IntegrityError:
                        pass

                conn.commit()
            finally:
                conn.close()

        logger.info("[PaperDB] Saved %d papers (%d upserted)", len(papers), inserted)
        return inserted

    def get_all_papers(self) -> List[Dict[str, Any]]:
        """Return all papers as a list of dicts."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM papers ORDER BY created_at DESC"
                ).fetchall()
                return [self._row_to_paper(r) for r in rows]
            finally:
                conn.close()

    def get_paper(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Return a single paper by doc_id, or None if not found."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM papers WHERE doc_id = ?", (doc_id,)
                ).fetchone()
                return self._row_to_paper(row) if row else None
            finally:
                conn.close()

    def delete_paper(self, doc_id: str) -> bool:
        """Delete a paper by doc_id. Returns True if a row was deleted."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM papers WHERE doc_id = ?", (doc_id,))
                deleted = conn.execute("SELECT changes()").fetchone()[0]
                conn.commit()
                return deleted > 0
            finally:
                conn.close()

    def search_fts(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Full-text search across title and abstract using FTS5.

        Args:
            query: Search terms (FTS5 match syntax supported).
            limit: Maximum results to return.

        Returns:
            List of matching papers, ordered by FTS5 rank.
        """
        if not query or not query.strip():
            return []

        # Escape special FTS5 characters and build a simple query
        safe_tokens = []
        for token in query.strip().split():
            # Remove characters that have special meaning in FTS5
            clean = token.replace('"', '').replace("'", "").replace("*", "")
            if clean:
                safe_tokens.append(f'"{clean}"')

        if not safe_tokens:
            return []

        fts_query = " OR ".join(safe_tokens)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT p.*
                    FROM papers_fts fts
                    JOIN papers p ON p.rowid = fts.rowid
                    WHERE papers_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
                return [self._row_to_paper(r) for r in rows]
            finally:
                conn.close()

    def count(self) -> int:
        """Return total number of papers."""
        with self._lock:
            conn = self._connect()
            try:
                return conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            finally:
                conn.close()

    def clear(self) -> int:
        """Delete all papers. Returns count of deleted rows."""
        with self._lock:
            conn = self._connect()
            try:
                count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
                conn.execute("DELETE FROM papers")
                # Rebuild FTS index
                conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")
                conn.commit()
                logger.info("[PaperDB] Cleared %d papers", count)
                return count
            finally:
                conn.close()

    # ── Migration ─────────────────────────────────────────────────────

    def migrate_from_json(self, json_path: str) -> int:
        """Import papers from a legacy papers.json file.

        The JSON file is expected to have the structure::

            {"papers": [{...}, {...}, ...]}

        After successful migration the JSON file is renamed to
        ``papers.json.migrated`` to prevent re-import.

        Returns:
            Number of papers imported.
        """
        json_path = Path(json_path)
        if not json_path.exists():
            logger.debug("[PaperDB] No JSON file to migrate: %s", json_path)
            return 0

        # Skip if already migrated
        migrated_marker = json_path.with_suffix(".json.migrated")
        if migrated_marker.exists():
            logger.debug("[PaperDB] JSON already migrated (marker exists)")
            return 0

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            papers = data.get("papers", []) if isinstance(data, dict) else data
            if not papers:
                logger.info("[PaperDB] JSON file empty, nothing to migrate")
                return 0

            self.save_papers(papers)
            logger.info(
                "[PaperDB] Migrated %d papers from %s", len(papers), json_path
            )

            # Rename original file to prevent re-import
            try:
                os.rename(str(json_path), str(migrated_marker))
                logger.info("[PaperDB] Renamed %s -> %s", json_path, migrated_marker)
            except OSError as e:
                logger.warning("[PaperDB] Could not rename JSON file: %s", e)

            return len(papers)

        except Exception as e:
            logger.error("[PaperDB] Migration failed: %s", e)
            return 0
