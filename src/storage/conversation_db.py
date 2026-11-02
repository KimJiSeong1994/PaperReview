"""SQLite storage for home-assistant conversations and their turns.

Ownership is the exact (username, account_incarnation) pair: a re-registered
account with the same username never sees the previous account's history.
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id                  TEXT PRIMARY KEY,
    username            TEXT NOT NULL,
    account_incarnation TEXT NOT NULL,
    title               TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    archived            INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS turns (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL DEFAULT '',
    blocks_json     TEXT NOT NULL DEFAULT '[]',
    intent          TEXT,
    status          TEXT NOT NULL DEFAULT 'done',
    model           TEXT,
    latency_ms      INTEGER,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_owner
    ON conversations (username, account_incarnation, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_turns_conversation ON turns (conversation_id, seq);
"""


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _turn_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a ``turns`` row to a dict with ``blocks`` decoded."""
    turn = dict(row)
    turn["blocks"] = json.loads(turn.pop("blocks_json") or "[]")
    return turn


class ConversationDB:
    """Thread-safe SQLite store for conversations (BookmarkDB pattern)."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Open a WAL-mode connection with foreign keys and Row factory."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the schema and fail turns orphaned by a previous process."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                # ponytail: assumes a single server process owns the DB; a turn
                # still `running` at startup was cut off by a restart. Move to
                # a heartbeat column if the server ever runs multiple workers.
                conn.execute("UPDATE turns SET status = 'error' WHERE status = 'running'")
                conn.commit()
            finally:
                conn.close()

    def create_conversation(self, username: str, incarnation: str, title: str) -> Dict[str, Any]:
        """Create an empty conversation owned by (username, incarnation)."""
        now = _now()
        conv = {
            "id": uuid4().hex,
            "username": username,
            "account_incarnation": incarnation,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "archived": 0,
        }
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO conversations VALUES (:id, :username, :account_incarnation,"
                    " :title, :created_at, :updated_at, :archived)",
                    conv,
                )
                conn.commit()
            finally:
                conn.close()
        return conv

    def list_conversations(self, username: str, incarnation: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Return non-archived conversations, newest first, with turn stats."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT c.id, c.title, c.updated_at,
                           (SELECT COUNT(*) FROM turns t WHERE t.conversation_id = c.id) AS turn_count,
                           (SELECT t.intent FROM turns t
                             WHERE t.conversation_id = c.id AND t.intent IS NOT NULL
                             ORDER BY t.seq DESC LIMIT 1) AS last_intent
                      FROM conversations c
                     WHERE c.username = ? AND c.account_incarnation = ? AND c.archived = 0
                     ORDER BY c.updated_at DESC
                     LIMIT ?
                    """,
                    (username, incarnation, limit),
                ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]

    def get_conversation(self, conversation_id: str, username: str, incarnation: str) -> Optional[Dict[str, Any]]:
        """Return the conversation with ordered turns, or None if not the caller's."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM conversations WHERE id = ? AND username = ? AND account_incarnation = ?",
                    (conversation_id, username, incarnation),
                ).fetchone()
                if row is None:
                    return None
                turns = conn.execute(
                    "SELECT * FROM turns WHERE conversation_id = ? ORDER BY seq", (conversation_id,)
                ).fetchall()
            finally:
                conn.close()
        conv = dict(row)
        conv["turns"] = [_turn_to_dict(t) for t in turns]
        return conv

    def append_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        blocks: Optional[list] = None,
        intent: Optional[str] = None,
        status: str = "done",
        model: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Append a turn at the next ``seq`` and bump the conversation's ``updated_at``."""
        now = _now()
        turn = {
            "id": uuid4().hex,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "blocks_json": json.dumps(blocks or [], ensure_ascii=False),
            "intent": intent,
            "status": status,
            "model": model,
            "latency_ms": latency_ms,
            "created_at": now,
        }
        with self._lock:
            conn = self._connect()
            try:
                turn["seq"] = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM turns WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO turns (id, conversation_id, seq, role, content, blocks_json, intent,"
                    " status, model, latency_ms, created_at) VALUES (:id, :conversation_id, :seq,"
                    " :role, :content, :blocks_json, :intent, :status, :model, :latency_ms, :created_at)",
                    turn,
                )
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
                )
                conn.commit()
            finally:
                conn.close()
        turn["blocks"] = json.loads(turn.pop("blocks_json"))
        return turn

    def finish_turn(
        self,
        turn_id: str,
        content: str,
        blocks: list,
        intent: Optional[str],
        status: str,
        model: Optional[str],
        latency_ms: Optional[int],
    ) -> None:
        """Write the final state of a (running) turn."""
        now = _now()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE turns SET content = ?, blocks_json = ?, intent = ?, status = ?,"
                    " model = ?, latency_ms = ? WHERE id = ?",
                    (content, json.dumps(blocks, ensure_ascii=False), intent, status, model, latency_ms, turn_id),
                )
                conn.execute(
                    "UPDATE conversations SET updated_at = ?"
                    " WHERE id = (SELECT conversation_id FROM turns WHERE id = ?)",
                    (now, turn_id),
                )
                conn.commit()
            finally:
                conn.close()

    def set_title(self, conversation_id: str, title: str) -> None:
        """Replace the conversation title (the router's natural first-turn title)."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))
                conn.commit()
            finally:
                conn.close()

    def archive(self, conversation_id: str, username: str, incarnation: str) -> bool:
        """Hide a conversation from listings; False when not the caller's."""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE conversations SET archived = 1"
                    " WHERE id = ? AND username = ? AND account_incarnation = ?",
                    (conversation_id, username, incarnation),
                )
                conn.commit()
            finally:
                conn.close()
        return cur.rowcount > 0

    def delete_by_username(self, username: str) -> int:
        """Delete every conversation (all incarnations) of *username*; returns the count."""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM conversations WHERE username = ?", (username,))
                conn.commit()
            finally:
                conn.close()
        return cur.rowcount
