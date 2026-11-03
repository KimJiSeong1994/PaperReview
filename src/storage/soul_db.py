"""Per-account "soul": an editable USER.md profile plus durable MEMORY.md notes.

Mirrors the OpenClaw/Hermes workspace memory model in-app. Ownership is the
exact (username, account_incarnation) pair, like conversations.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

MAX_MEMORIES = 60  # preference/topic/paper/fact, least recently used evicted
MAX_RESEARCH = 3  # the user's own research; the newest replace the oldest
MAX_INTERESTS = 20  # research interest labels; fewest hits evicted first
MAX_USER_MD = 2000
MAX_MEMORY_TEXT = 200
MEMORY_KINDS = ("preference", "topic", "paper", "fact", "research", "interest")
SCHEMA_VERSION = 2  # 1: research/interest kinds + hits; 2: research_profiles

_SOULS_SCHEMA = """
CREATE TABLE IF NOT EXISTS souls (
    username            TEXT NOT NULL,
    account_incarnation TEXT NOT NULL,
    user_md             TEXT NOT NULL DEFAULT '',
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (username, account_incarnation)
);
"""
_MEMORIES_SCHEMA = """
CREATE TABLE {table} (
    id                     TEXT PRIMARY KEY,
    username               TEXT NOT NULL,
    account_incarnation    TEXT NOT NULL,
    kind                   TEXT NOT NULL CHECK (kind IN ('preference', 'topic', 'paper', 'fact', 'research', 'interest')),
    text                   TEXT NOT NULL,
    source_conversation_id TEXT,
    created_at             TEXT NOT NULL,
    last_used_at           TEXT NOT NULL,
    hits                   INTEGER NOT NULL DEFAULT 1
);
"""
_PROFILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_profiles (
    username            TEXT NOT NULL,
    account_incarnation TEXT NOT NULL,
    profile_json        TEXT NOT NULL,
    source_hash         TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (username, account_incarnation)
);
"""
_MEMORIES_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_memories_owner ON memories (username, account_incarnation, last_used_at DESC);"
)
_V0_COLUMNS = "id, username, account_incarnation, kind, text, source_conversation_id, created_at, last_used_at"

_KIND_LABELS = {
    "preference": "선호", "topic": "관심 주제", "paper": "논문", "fact": "사실",
    "research": "연구 내용", "interest": "관심 분야",
}


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


def top_interests(memories: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Interest memories by hits, then most recent use."""
    interests = [m for m in memories if m["kind"] == "interest"]
    return sorted(interests, key=lambda m: (m.get("hits") or 1, m["last_used_at"]), reverse=True)[:limit]


def render_markdown(soul: Dict[str, Any]) -> str:
    """Render a soul as ``# USER.md`` + ``# MEMORY.md``; research and interests come first as sections."""
    user_md = soul.get("user_md", "").strip() or "(비어 있음)"
    memories = soul.get("memories", [])
    parts = []
    research = [m for m in memories if m["kind"] == "research"]
    if research:
        parts.append("## 연구 내용\n" + "\n".join(f"- {m['text']}" for m in research))
    interests = top_interests(memories, MAX_INTERESTS)
    if interests:
        parts.append("## 관심 분야\n- " + " · ".join(m["text"] for m in interests))
    lines = [f"- [{_KIND_LABELS.get(m['kind'], m['kind'])}] {m['text']}"
             for m in memories if m["kind"] not in ("research", "interest")]
    if lines:
        parts.append("\n".join(lines))
    return f"# USER.md\n\n{user_md}\n\n# MEMORY.md\n\n" + ("\n\n".join(parts) or "(비어 있음)")


class SoulDB:
    """Thread-safe SQLite store for USER.md profiles and memories (BookmarkDB pattern)."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SOULS_SCHEMA)
                self._migrate(conn)
            finally:
                conn.close()

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Bring ``memories`` to SCHEMA_VERSION; idempotent (PRAGMA user_version records it).

        SQLite cannot alter a CHECK constraint, so v0 → v1 rebuilds the table:
        copy every row into the new schema (hits = 1), drop, rename.
        """
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memories'").fetchone()
        if not exists:
            conn.executescript(_MEMORIES_SCHEMA.format(table="memories") + _MEMORIES_INDEX)
        elif version < 1:
            conn.executescript(
                "BEGIN;"
                + _MEMORIES_SCHEMA.format(table="memories_v1")
                + f"INSERT INTO memories_v1 ({_V0_COLUMNS}, hits) SELECT {_V0_COLUMNS}, 1 FROM memories;"
                "DROP TABLE memories;"
                "ALTER TABLE memories_v1 RENAME TO memories;"
                + _MEMORIES_INDEX
                + "COMMIT;"
            )
        conn.executescript(_PROFILES_SCHEMA)  # v2; IF NOT EXISTS keeps it idempotent
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

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
                    "SELECT id, kind, text, source_conversation_id, created_at, last_used_at, hits FROM memories"
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
        """Add new ``{kind, text}`` items; a duplicate (normalised text) is refreshed instead,
        and a repeated interest also gains a hit.

        Caps per account: 3 research (oldest dropped), 20 interests (fewest hits,
        then least recent, dropped), 60 of the other kinds (least recently used dropped).
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
                        conn.execute(
                            "UPDATE memories SET last_used_at = ?, hits = hits + (kind = 'interest') WHERE id = ?",
                            (now, existing[key]),
                        )
                        continue
                    existing[key] = uuid4().hex
                    conn.execute(
                        f"INSERT INTO memories ({_V0_COLUMNS}, hits) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                        (existing[key], username, incarnation, kind, text, source_conversation_id, now, now),
                    )
                    added += 1
                for kinds, order, cap in (
                    ("kind NOT IN ('research', 'interest')", "last_used_at DESC", MAX_MEMORIES),
                    ("kind = 'research'", "created_at DESC", MAX_RESEARCH),
                    ("kind = 'interest'", "hits DESC, last_used_at DESC", MAX_INTERESTS),
                ):
                    conn.execute(
                        f"DELETE FROM memories WHERE id IN (SELECT id FROM memories WHERE username = ? AND "
                        f"account_incarnation = ? AND {kinds} ORDER BY {order} LIMIT -1 OFFSET ?)",
                        (username, incarnation, cap),
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
        """Forget everything for this account (USER.md and research profile too); returns deleted memory count."""
        owner = (username, incarnation)
        deleted = self._delete("DELETE FROM memories WHERE username = ? AND account_incarnation = ?", owner)
        self._delete("DELETE FROM souls WHERE username = ? AND account_incarnation = ?", owner)
        self._delete("DELETE FROM research_profiles WHERE username = ? AND account_incarnation = ?", owner)
        return deleted

    def delete_by_username(self, username: str) -> int:
        """Delete USER.md, memories and research profiles of every incarnation of *username*; returns rows deleted."""
        return sum(
            self._delete(f"DELETE FROM {table} WHERE username = ?", (username,))
            for table in ("memories", "souls", "research_profiles")
        )

    def get_profile(self, username: str, incarnation: str) -> Optional[Dict[str, Any]]:
        """Cached research profile row ``{profile, source_hash, updated_at}``, or None."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT profile_json, source_hash, updated_at FROM research_profiles"
                    " WHERE username = ? AND account_incarnation = ?",
                    (username, incarnation),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        return {"profile": json.loads(row["profile_json"]), "source_hash": row["source_hash"],
                "updated_at": row["updated_at"]}

    def save_profile(self, username: str, incarnation: str, profile: Dict[str, Any], source_hash: str) -> None:
        """Store the derived research profile for this account."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO research_profiles VALUES (?, ?, ?, ?, ?) ON CONFLICT(username, account_incarnation)"
                    " DO UPDATE SET profile_json = excluded.profile_json, source_hash = excluded.source_hash,"
                    " updated_at = excluded.updated_at",
                    (username, incarnation, json.dumps(profile, ensure_ascii=False), source_hash, _now()),
                )
                conn.commit()
            finally:
                conn.close()

    def owners(self) -> List[tuple]:
        """Every (username, account_incarnation) that has a USER.md or any memory."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT username, account_incarnation FROM memories UNION "
                    "SELECT username, account_incarnation FROM souls"
                ).fetchall()
            finally:
                conn.close()
        return [(r[0], r[1]) for r in rows]

    def all_profiles(self) -> List[Dict[str, Any]]:
        """Every cached profile ``{username, account_incarnation, profile}`` (newsletter export)."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT username, account_incarnation, profile_json FROM research_profiles ORDER BY username"
                ).fetchall()
            finally:
                conn.close()
        return [{"username": r["username"], "account_incarnation": r["account_incarnation"],
                 "profile": json.loads(r["profile_json"])} for r in rows]

    # ── Admin aggregates: counts and timestamps only; never text, user_md or profile values ──

    def _read(self, sql: str, params: Any = ()) -> List[sqlite3.Row]:
        with self._lock:
            conn = self._connect()
            try:
                return conn.execute(sql, params).fetchall()
            finally:
                conn.close()

    def admin_stats(self, since: str, stale_before: str) -> Dict[str, Any]:
        """Aggregate counts over souls/memories/research_profiles; never selects text, user_md or profile values."""
        owner = "username || '|' || account_incarnation"
        accounts = self._read(
            f"""
            SELECT (SELECT COUNT(*) FROM (SELECT {owner} FROM memories UNION
                    SELECT {owner} FROM souls WHERE length(trim(user_md)) > 0)) AS with_soul,
                   (SELECT COUNT(DISTINCT {owner}) FROM memories) AS with_memories,
                   (SELECT COUNT(*) FROM souls WHERE length(trim(user_md)) > 0) AS with_user_md
            """
        )[0]
        memories = self._read(
            """
            SELECT COUNT(*) AS total, COALESCE(SUM(created_at >= ?), 0) AS new_in_window,
                   AVG(CASE WHEN kind = 'interest' THEN hits END) AS interest_avg_hits
              FROM memories
            """,
            (since,),
        )[0]
        by_kind = {
            r["kind"]: (r["count"], r["accounts"])
            for r in self._read(
                f"SELECT kind, COUNT(*) AS count, COUNT(DISTINCT {owner}) AS accounts FROM memories GROUP BY kind"
            )
        }
        profiles = self._read(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(updated_at < ?), 0) AS stale_over_24h,
                   COALESCE(SUM(json_extract(profile_json, '$.role') IS NOT NULL), 0) AS with_role,
                   COALESCE(SUM(json_extract(profile_json, '$.domain') IS NOT NULL), 0) AS with_domain,
                   COALESCE(SUM(COALESCE(json_array_length(profile_json, '$.keywords'), 0) > 0), 0) AS with_keywords
              FROM research_profiles
            """,
            (stale_before,),
        )[0]
        avg_hits = memories["interest_avg_hits"]
        return {
            "accounts": dict(accounts),
            "memories": {
                "total": memories["total"],
                "new_in_window": memories["new_in_window"],
                "interest_avg_hits": round(avg_hits, 2) if avg_hits is not None else None,
                "by_kind": [
                    {"kind": k, "count": by_kind.get(k, (0, 0))[0], "accounts": by_kind.get(k, (0, 0))[1]}
                    for k in MEMORY_KINDS
                ],
            },
            "profiles": dict(profiles),
        }

    def counts_by_owner(self) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """(username, incarnation) -> {"memory_count": int, "profile_updated_at": str | None}."""
        result: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in self._read("SELECT username, account_incarnation, COUNT(*) FROM memories GROUP BY 1, 2"):
            result[(r[0], r[1])] = {"memory_count": r[2], "profile_updated_at": None}
        for r in self._read("SELECT username, account_incarnation, updated_at FROM research_profiles"):
            result.setdefault((r[0], r[1]), {"memory_count": 0, "profile_updated_at": None})["profile_updated_at"] = r[2]
        return result

    def _delete(self, sql: str, params: tuple) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
            finally:
                conn.close()
        return cur.rowcount


def read_profile_readonly(db_path: Path, username: str, incarnation: str) -> Optional[Dict[str, Any]]:
    """Cached research profile from *db_path* opened read-only (offline jobs; never migrates or writes).

    None when the file, the table or the row is missing, or the file cannot be read.
    """
    path = Path(db_path)
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT profile_json FROM research_profiles WHERE username = ? AND account_incarnation = ?",
                (username, incarnation),
            ).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else None
    except (sqlite3.Error, ValueError):
        return None
