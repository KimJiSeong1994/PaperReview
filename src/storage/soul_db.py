"""Per-account "soul": an editable USER.md profile plus durable MEMORY.md notes.

Mirrors the OpenClaw/Hermes workspace memory model in-app. Ownership is the
exact (username, account_incarnation) pair, like conversations.
"""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

MAX_MEMORIES = 60
MAX_USER_MD = 2000
MAX_MEMORY_TEXT = 200
MEMORY_KINDS = ("preference", "topic", "paper", "fact")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS souls (
    username            TEXT NOT NULL,
    account_incarnation TEXT NOT NULL,
    user_md             TEXT NOT NULL DEFAULT '',
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (username, account_incarnation)
);
CREATE TABLE IF NOT EXISTS memories (
    id                     TEXT PRIMARY KEY,
    username               TEXT NOT NULL,
    account_incarnation    TEXT NOT NULL,
    kind                   TEXT NOT NULL CHECK (kind IN ('preference', 'topic', 'paper', 'fact')),
    text                   TEXT NOT NULL,
    source_conversation_id TEXT,
    created_at             TEXT NOT NULL,
    last_used_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_owner
    ON memories (username, account_incarnation, last_used_at DESC);
"""

_KIND_LABELS = {"preference": "선호", "topic": "관심 주제", "paper": "논문", "fact": "사실"}


def _now() -> str:
    """Current UTC time as ISO-8601 (microseconds keep same-second writes ordered)."""
    return datetime.now(timezone.utc).isoformat()


_PROMPT_TAGS = ("<user_memory>", "</user_memory>", "<papers>", "</papers>")


def sanitize(text: str) -> str:
    """Strip prompt-delimiter tags and any angle brackets from stored text."""
    for tag in _PROMPT_TAGS:
        text = text.replace(tag, "")
    return text.replace("<", "").replace(">", "")


def normalize_memory(text: str) -> str:
    """Dedupe key: lowercase with whitespace collapsed."""
    return " ".join(str(text).lower().split())


def render_markdown(soul: Dict[str, Any]) -> str:
    """Render a soul as ``# USER.md`` + ``# MEMORY.md`` markdown."""
    user_md = soul.get("user_md", "").strip() or "(비어 있음)"
    lines = [f"- [{_KIND_LABELS.get(m['kind'], m['kind'])}] {m['text']}" for m in soul.get("memories", [])]
    return f"# USER.md\n\n{user_md}\n\n# MEMORY.md\n\n" + ("\n".join(lines) or "(비어 있음)")


class SoulDB:
    """Thread-safe SQLite store for USER.md profiles and memories (BookmarkDB pattern)."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Open a WAL-mode connection with Row factory."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.row_factory = sqlite3.Row
        return conn

    def get_soul(self, username: str, incarnation: str) -> Dict[str, Any]:
        """Return ``{user_md, memories}`` (memories most recently used first)."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT user_md FROM souls WHERE username = ? AND account_incarnation = ?",
                    (username, incarnation),
                ).fetchone()
                memories = conn.execute(
                    "SELECT id, kind, text, source_conversation_id, created_at, last_used_at FROM memories"
                    " WHERE username = ? AND account_incarnation = ? ORDER BY last_used_at DESC",
                    (username, incarnation),
                ).fetchall()
            finally:
                conn.close()
        return {"user_md": row["user_md"] if row else "", "memories": [dict(m) for m in memories]}

    def set_user_md(self, username: str, incarnation: str, text: str) -> str:
        """Replace the USER.md profile (cut to 2000 chars); returns the stored text."""
        text = sanitize(text)[:MAX_USER_MD]
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO souls VALUES (?, ?, ?, ?) ON CONFLICT(username, account_incarnation)"
                    " DO UPDATE SET user_md = excluded.user_md, updated_at = excluded.updated_at",
                    (username, incarnation, text, _now()),
                )
                conn.commit()
            finally:
                conn.close()
        return text

    def add_memories(
        self, username: str, incarnation: str, items: Iterable[Dict[str, str]], source_conversation_id: Optional[str]
    ) -> int:
        """Add new ``{kind, text}`` items; a duplicate (normalised text) is refreshed instead.

        Keeps at most 60 memories per account, evicting the least recently used.
        Returns how many new memories were stored.
        """
        added = 0
        with self._lock:
            conn = self._connect()
            try:
                existing = {
                    normalize_memory(r["text"]): r["id"]
                    for r in conn.execute(
                        "SELECT id, text FROM memories WHERE username = ? AND account_incarnation = ?",
                        (username, incarnation),
                    )
                }
                for item in items:
                    kind = item.get("kind")
                    text = " ".join(sanitize(str(item.get("text") or "")).split())[:MAX_MEMORY_TEXT]
                    key = normalize_memory(text)
                    if kind not in MEMORY_KINDS or not key:
                        continue
                    now = _now()
                    if key in existing:
                        conn.execute("UPDATE memories SET last_used_at = ? WHERE id = ?", (now, existing[key]))
                        continue
                    existing[key] = uuid4().hex
                    conn.execute(
                        "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (existing[key], username, incarnation, kind, text, source_conversation_id, now, now),
                    )
                    added += 1
                conn.execute(
                    "DELETE FROM memories WHERE id IN (SELECT id FROM memories"
                    " WHERE username = ? AND account_incarnation = ? ORDER BY last_used_at DESC LIMIT -1 OFFSET ?)",
                    (username, incarnation, MAX_MEMORIES),
                )
                conn.commit()
            finally:
                conn.close()
        return added

    def touch_memories(self, username: str, incarnation: str, ids: List[str]) -> None:
        """Mark the caller's memories as just used (they were put into a prompt)."""
        if not ids:
            return
        now = _now()
        with self._lock:
            conn = self._connect()
            try:
                conn.executemany(
                    "UPDATE memories SET last_used_at = ? WHERE id = ? AND username = ? AND account_incarnation = ?",
                    [(now, i, username, incarnation) for i in ids],
                )
                conn.commit()
            finally:
                conn.close()

    def delete_memory(self, memory_id: str, username: str, incarnation: str) -> bool:
        """Delete one of the caller's memories; False when not theirs."""
        return self._delete(
            "DELETE FROM memories WHERE id = ? AND username = ? AND account_incarnation = ?",
            (memory_id, username, incarnation),
        ) > 0

    def clear(self, username: str, incarnation: str) -> int:
        """Forget everything for this account (profile too); returns deleted memory count."""
        deleted = self._delete(
            "DELETE FROM memories WHERE username = ? AND account_incarnation = ?", (username, incarnation)
        )
        self._delete("DELETE FROM souls WHERE username = ? AND account_incarnation = ?", (username, incarnation))
        return deleted

    def delete_by_username(self, username: str) -> int:
        """Delete profiles and memories of every incarnation of *username*; returns rows deleted."""
        return self._delete("DELETE FROM memories WHERE username = ?", (username,)) + self._delete(
            "DELETE FROM souls WHERE username = ?", (username,)
        )

    def _delete(self, sql: str, params: tuple) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
            finally:
                conn.close()
        return cur.rowcount
