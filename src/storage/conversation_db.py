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
from typing import Any, Dict, List, Optional, Tuple
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
CREATE INDEX IF NOT EXISTS idx_turns_created ON turns (created_at);
"""

# Content of an assistant turn superseded by a new user message (routers/conversations.py);
# the admin stats tell a cancel apart from a failure by this text.
CANCELLED_TEXT = "중단됨"

# Outcome of an assistant turn. status='error' mixes three cases: a real failure
# (latency recorded), a cancel (CANCELLED_TEXT) and a turn cut off by a restart.
_OUTCOME_SQL = """CASE WHEN t.status = 'running' THEN 'running'
     WHEN t.status = 'done' THEN 'done'
     WHEN t.latency_ms IS NOT NULL THEN 'failed'
     WHEN t.content = :cancel_text THEN 'cancelled'
     ELSE 'interrupted' END"""


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

    # ── Admin aggregates: counts, timestamps and enum values only; never content, title or blocks ──

    def _read(self, sql: str, params: Any = ()) -> List[sqlite3.Row]:
        with self._lock:
            conn = self._connect()
            try:
                return conn.execute(sql, params).fetchall()
            finally:
                conn.close()

    def admin_turn_stats(self, since: str) -> Dict[str, Any]:
        """Aggregates only: totals, outcome×intent counts, done-turn latencies by intent, KST daily rows.

        Never returns content, title or blocks (content is only compared to CANCELLED_TEXT in SQL).
        """
        params = {"since": since, "cancel_text": CANCELLED_TEXT}
        totals = self._read(
            """
            SELECT (SELECT COUNT(*) FROM conversations WHERE created_at >= :since) AS conversations,
                   (SELECT COUNT(*) FROM turns WHERE role = 'user' AND created_at >= :since) AS user_turns,
                   (SELECT COUNT(DISTINCT c.username || '|' || c.account_incarnation)
                      FROM turns t JOIN conversations c ON c.id = t.conversation_id
                     WHERE t.role = 'user' AND t.created_at >= :since) AS active_users
            """,
            params,
        )[0]
        outcomes = self._read(
            f"""
            SELECT t.intent AS intent, {_OUTCOME_SQL} AS outcome, COUNT(*) AS n
              FROM turns t WHERE t.role = 'assistant' AND t.created_at >= :since
             GROUP BY 1, 2
            """,
            params,
        )
        latencies = self._read(
            """
            SELECT intent, latency_ms FROM turns
             WHERE role = 'assistant' AND status = 'done' AND latency_ms IS NOT NULL
               AND intent IS NOT NULL AND created_at >= :since
            """,
            params,
        )
        daily = self._read(
            f"""
            SELECT date(t.created_at, '+9 hours') AS date,
                   COUNT(DISTINCT CASE WHEN t.role = 'user' THEN t.conversation_id END) AS conversations,
                   SUM(t.role = 'user') AS user_turns,
                   COUNT(DISTINCT CASE WHEN t.role = 'user'
                                       THEN c.username || '|' || c.account_incarnation END) AS active_users,
                   SUM(t.role = 'assistant' AND {_OUTCOME_SQL} IN ('failed', 'interrupted')) AS failed
              FROM turns t JOIN conversations c ON c.id = t.conversation_id
             WHERE t.created_at >= :since
             GROUP BY 1
            """,
            params,
        )
        return {
            "conversations": totals["conversations"],
            "user_turns": totals["user_turns"],
            "active_users": totals["active_users"],
            "outcomes": [(r["intent"], r["outcome"], r["n"]) for r in outcomes],
            "latencies": [(r["intent"], r["latency_ms"]) for r in latencies],
            "daily": [dict(r) for r in daily],
        }

    def review_starts_since(self, since: str) -> List[Dict[str, Optional[str]]]:
        """[{session_id, mode}] from review_started blocks of assistant turns created since *since*."""
        rows = self._read(
            """
            SELECT json_extract(b.value, '$.session_id') AS session_id, json_extract(b.value, '$.mode') AS mode
              FROM turns t, json_each(t.blocks_json) b
             WHERE t.role = 'assistant' AND t.created_at >= ?
               AND json_extract(b.value, '$.type') = 'review_started'
            """,
            (since,),
        )
        return [dict(r) for r in rows]

    def user_activity_days(self, until: str) -> List[Dict[str, Any]]:
        """Retained user-message activity per owner/KST day, without message text.

        Read history before the window too: otherwise existing users would be
        mistaken for newly activated accounts when the window changes.
        """
        rows = self._read(
            """
            SELECT c.username, c.account_incarnation,
                   date(t.created_at, '+9 hours') AS date,
                   MIN(julianday(t.created_at)) AS first_jd,
                   COUNT(*) AS messages
              FROM turns t JOIN conversations c ON c.id = t.conversation_id
             WHERE t.role = 'user' AND julianday(t.created_at) <= julianday(?)
             GROUP BY c.username, c.account_incarnation, date(t.created_at, '+9 hours')
            """,
            (until,),
        )
        return [dict(row) for row in rows]

    def first_conversation_by_owner(self) -> Dict[Tuple[str, str], str]:
        """(username, incarnation) -> MIN(created_at)."""
        rows = self._read(
            "SELECT username, account_incarnation, MIN(created_at) FROM conversations GROUP BY 1, 2"
        )
        return {(r[0], r[1]): r[2] for r in rows}

    def counts_by_owner(self) -> Dict[Tuple[str, str], Tuple[int, str]]:
        """(username, incarnation) -> (conversation_count, MAX(updated_at)); archived included."""
        rows = self._read(
            "SELECT username, account_incarnation, COUNT(*), MAX(updated_at) FROM conversations GROUP BY 1, 2"
        )
        return {(r[0], r[1]): (r[2], r[3]) for r in rows}

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
