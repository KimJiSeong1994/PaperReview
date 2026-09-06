"""Durable, privacy-bounded operational analytics for MCP traffic.

The ledger intentionally stores one lifecycle row per request, tool invocation,
or background job. It never stores arbitrary request payloads.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import logging
import math
import os
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KST = dt.timezone(dt.timedelta(hours=9), name="Asia/Seoul")
TOOL_NAMES = frozenset(
    {
        "add_bookmark",
        "check_blog_draft",
        "create_blog_draft",
        "create_curriculum",
        "explore_related",
        "generate_figure",
        "get_paper",
        "get_review_report",
        "get_review_status",
        "list_bookmarks",
        "remove_bookmark",
        "search_papers",
        "start_review",
        "update_blog_draft",
    }
)

_KINDS = frozenset({"request", "tool", "job"})
_STATUSES = frozenset({"started", "succeeded", "failed", "cancelled", "unknown"})
_SOURCES = frozenset({"ua_claim", "adapter_report", "server_observed"})
_ACTOR_ROLES = frozenset({"user", "admin", "internal"})
_REAL_TERMINALS = frozenset({"succeeded", "failed", "cancelled"})
_MEANINGFUL_REQUESTS = frozenset(
    {
        "POST /api/search",
        "POST /api/deep-review",
        "POST /api/bookmarks/from-paper",
        "DELETE /api/bookmarks/{bookmark_id}",
        "POST /api/curricula/generate",
        "POST /api/bookmarks/{bookmark_id}/citation-tree",
        "POST /api/autofigure/method-to-svg",
        "POST /api/blog/posts",
        "PUT /api/blog/posts/{post_id}",
        "POST /api/deep-review/visualize-direct",
        "POST /api/deep-review/visualize/{session_id}",
    }
)
_MEANINGFUL_TOOLS = frozenset(
    {
        "search_papers",
        "start_review",
        "add_bookmark",
        "remove_bookmark",
        "create_curriculum",
        "explore_related",
        "generate_figure",
        "create_blog_draft",
        "update_blog_draft",
    }
)
_JOB_NAME_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_REQUEST_NAME_RE = re.compile(
    r"^(?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD) (?:/[^?#]{0,180}|\(unmatched\))$"
)
_LIFECYCLE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_VERSION_RE = re.compile(r"^[vV]?\d+(?:\.\d+){0,3}(?:[-+][A-Za-z0-9.-]{1,24})?$")
_KNOWN_CLIENTS: dict[str, str | None] = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "claude-code": "Claude Code",
    "claude desktop": "Claude Desktop",
    "claude-desktop": "Claude Desktop",
    "codex": "Codex",
    "cursor": "Cursor",
    "gemini": "Gemini",
    "other": "Other",
    "unknown": None,
    "vscode": "VS Code",
    "visual studio code": "VS Code",
}
_WRITE_SLOTS = threading.BoundedSemaphore(8)


def mcp_analytics_db_path() -> Path:
    return Path(os.getenv("MCP_ANALYTICS_DB_PATH", "data/mcp_analytics.db"))


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return (
        value.astimezone(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=0.25, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=250")
    return conn


def initialize_mcp_usage(db_path: Path | str | None = None) -> bool:
    """Create the dedicated MCP ledger, returning false instead of breaking boot."""
    path = Path(db_path) if db_path is not None else mcp_analytics_db_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect(path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mcp_usage_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mcp_usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL CHECK (kind IN ('request','tool','job')),
                    name TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('started','succeeded','failed','cancelled','unknown')),
                    actor_id TEXT,
                    actor_scope TEXT NOT NULL,
                    actor_role TEXT,
                    invocation_id TEXT,
                    job_id TEXT,
                    duration_ms REAL,
                    http_status INTEGER,
                    adapter_version TEXT,
                    client_name TEXT,
                    client_version TEXT,
                    source TEXT NOT NULL CHECK (source IN ('ua_claim','adapter_report','server_observed')),
                    started_at TEXT,
                    terminal_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_mcp_tool_invocation
                    ON mcp_usage_events(actor_scope, invocation_id)
                    WHERE kind = 'tool' AND invocation_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS ux_mcp_job
                    ON mcp_usage_events(actor_scope, job_id)
                    WHERE kind = 'job' AND job_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS ix_mcp_usage_created ON mcp_usage_events(created_at);
                CREATE INDEX IF NOT EXISTS ix_mcp_usage_started ON mcp_usage_events(started_at);
                CREATE INDEX IF NOT EXISTS ix_mcp_usage_updated ON mcp_usage_events(updated_at);
                CREATE INDEX IF NOT EXISTS ix_mcp_usage_actor ON mcp_usage_events(actor_id);
                CREATE TABLE IF NOT EXISTS mcp_usage_actor_tombstones (
                    actor_hash TEXT PRIMARY KEY,
                    deleted_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO mcp_usage_metadata(key, value) VALUES ('initialized_at', ?)",
                (_iso(_utc_now()),),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        logger.exception("failed to initialize MCP analytics ledger")
        return False


def _bounded_text(value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    result = str(value).strip().replace("\x00", "")
    return result[:maximum] or None


def _safe_version(value: Any) -> str | None:
    result = _bounded_text(value, maximum=32)
    return result if result and _VERSION_RE.fullmatch(result) else None


def _safe_client(value: Any) -> str | None:
    result = _bounded_text(value, maximum=64)
    if not result:
        return None
    return _KNOWN_CLIENTS.get(result.casefold(), "Other")


def _uuid_text(value: Any, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError("missing lifecycle identifier")
        return None
    return str(uuid.UUID(str(value)))


def _normalize(fields: dict[str, Any]) -> dict[str, Any]:
    kind = str(fields.get("kind", "")).strip()
    status = str(fields.get("status", "")).strip()
    source = str(fields.get("source", "")).strip()
    if kind not in _KINDS or status not in _STATUSES or source not in _SOURCES:
        raise ValueError("unsupported MCP analytics event")

    name = str(fields.get("name", "")).strip()
    if kind == "tool":
        if name not in TOOL_NAMES:
            raise ValueError("unsupported tool name")
    elif kind == "request":
        if not _REQUEST_NAME_RE.fullmatch(name):
            raise ValueError("invalid normalized request route")
    elif not _JOB_NAME_RE.fullmatch(name):
        raise ValueError("invalid job name")

    invocation_id = _uuid_text(fields.get("invocation_id"), required=kind == "tool")
    job_id = _bounded_text(fields.get("job_id"), maximum=128)
    if kind == "job" and (not job_id or not _LIFECYCLE_ID_RE.fullmatch(job_id)):
        raise ValueError("missing job_id")

    duration = fields.get("duration_ms")
    if duration is not None:
        duration = float(duration)
        if not math.isfinite(duration) or duration < 0 or duration > 86_400_000:
            raise ValueError("invalid duration_ms")

    http_status = fields.get("http_status")
    if http_status is not None:
        http_status = int(http_status)
        if http_status < 100 or http_status > 599:
            raise ValueError("invalid http_status")

    actor_id = _bounded_text(fields.get("actor_id"), maximum=160)
    actor_role = _bounded_text(fields.get("actor_role"), maximum=16)
    if actor_role not in _ACTOR_ROLES:
        actor_role = None
    return {
        "event_id": _uuid_text(fields.get("event_id")) or str(uuid.uuid4()),
        "kind": kind,
        "name": name,
        "status": status,
        "actor_id": actor_id,
        "actor_scope": actor_id or "",
        "actor_role": actor_role,
        "invocation_id": invocation_id,
        "job_id": job_id,
        "duration_ms": duration,
        "http_status": http_status,
        "adapter_version": _safe_version(fields.get("adapter_version")),
        "client_name": _safe_client(fields.get("client_name")),
        "client_version": _safe_version(fields.get("client_version")),
        "source": source,
    }


def _existing_row(conn: sqlite3.Connection, event: dict[str, Any]) -> sqlite3.Row | None:
    if event["kind"] == "tool":
        return conn.execute(
            "SELECT * FROM mcp_usage_events WHERE kind='tool' AND actor_scope=? AND invocation_id=?",
            (event["actor_scope"], event["invocation_id"]),
        ).fetchone()
    if event["kind"] == "job":
        return conn.execute(
            "SELECT * FROM mcp_usage_events WHERE kind='job' AND actor_scope=? AND job_id=?",
            (event["actor_scope"], event["job_id"]),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM mcp_usage_events WHERE event_id=?", (event["event_id"],)
    ).fetchone()


def _record_event_impl(path: Path, fields: dict[str, Any]) -> bool:
    event = _normalize(fields)
    if not initialize_mcp_usage(path):
        return False
    now = _iso(_utc_now())
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if event["actor_id"] and conn.execute(
            "SELECT 1 FROM mcp_usage_actor_tombstones WHERE actor_hash=?",
            (_actor_hash(event["actor_id"]),),
        ).fetchone():
            conn.commit()
            return True
        existing = _existing_row(conn, event)
        if existing is not None:
            old_status = existing["status"]
            new_status = event["status"]
            should_advance = (
                old_status == "started" and new_status != "started"
            ) or (old_status == "unknown" and new_status in _REAL_TERMINALS)
            if should_advance:
                conn.execute(
                    """
                    UPDATE mcp_usage_events SET
                      status=?, terminal_at=?, updated_at=?,
                      duration_ms=COALESCE(?, duration_ms),
                      http_status=COALESCE(?, http_status),
                      actor_role=COALESCE(actor_role, ?),
                      adapter_version=COALESCE(adapter_version, ?),
                      client_name=COALESCE(client_name, ?),
                      client_version=COALESCE(client_version, ?),
                      source=CASE WHEN source='ua_claim' THEN ? ELSE source END
                    WHERE id=?
                    """,
                    (
                        new_status, now, now, event["duration_ms"], event["http_status"],
                        event["actor_role"], event["adapter_version"], event["client_name"],
                        event["client_version"], event["source"], existing["id"],
                    ),
                )
            conn.commit()
            return True

        started_at = now if event["status"] == "started" else None
        terminal_at = now if event["status"] != "started" else None
        conn.execute(
            """
            INSERT INTO mcp_usage_events (
              event_id, kind, name, status, actor_id, actor_scope, actor_role,
              invocation_id, job_id, duration_ms, http_status, adapter_version,
              client_name, client_version, source, started_at, terminal_at,
              created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event["event_id"], event["kind"], event["name"], event["status"],
                event["actor_id"], event["actor_scope"], event["actor_role"],
                event["invocation_id"], event["job_id"], event["duration_ms"],
                event["http_status"], event["adapter_version"], event["client_name"],
                event["client_version"], event["source"], started_at, terminal_at, now, now,
            ),
        )
        retention_days = max(
            90, min(int(os.getenv("MCP_ANALYTICS_RETENTION_DAYS", "400")), 3650)
        )
        cutoff = _iso(_utc_now() - dt.timedelta(days=retention_days))
        conn.execute("DELETE FROM mcp_usage_events WHERE updated_at < ?", (cutoff,))
        conn.commit()
        return True
    finally:
        conn.close()


def record_event(**fields: Any) -> bool:
    """Persist an event within bounded lock time; invalid/errors fail open."""
    if not _WRITE_SLOTS.acquire(blocking=False):
        logger.warning("dropping MCP analytics event: writer capacity exhausted")
        return False
    try:
        try:
            return _record_event_impl(mcp_analytics_db_path(), fields)
        except Exception:
            logger.exception("failed to persist MCP analytics event")
            return False
    finally:
        _WRITE_SLOTS.release()


async def record_event_async(**fields: Any) -> bool:
    """Run the bounded writer off the event loop."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(record_event, **fields), timeout=1.0)
    except TimeoutError:
        logger.warning("MCP analytics async write timed out")
        return False


def _actor_hash(actor_id: str) -> str:
    key = os.getenv("MCP_ANALYTICS_TOMBSTONE_KEY") or os.getenv(
        "JWT_SECRET", "local-mcp-analytics-tombstone"
    )
    return hmac.new(
        key.encode("utf-8"), actor_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def delete_actor_events(actor_id: str, db_path: Path | str | None = None) -> int:
    """Delete one account's rows and prevent in-flight jobs recreating them.

    The one-way tombstone intentionally also suppresses analytics if the same
    username is later re-registered. A missing ledger is initialized to retain
    the tombstone even if a job's start event could not be written. Database
    errors are raised so account-deletion cascades can report them.
    """
    actor = _bounded_text(actor_id, maximum=160)
    if not actor:
        return 0
    path = Path(db_path) if db_path is not None else mcp_analytics_db_path()
    if not initialize_mcp_usage(path):
        raise RuntimeError("MCP analytics deletion storage unavailable")
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR REPLACE INTO mcp_usage_actor_tombstones(actor_hash, deleted_at) VALUES (?, ?)",
            (_actor_hash(actor), _iso(_utc_now())),
        )
        cur = conn.execute("DELETE FROM mcp_usage_events WHERE actor_id=?", (actor,))
        conn.commit()
        return int(cur.rowcount)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(float(ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]), 3)


def _empty_report(
    days: int,
    now: dt.datetime,
    *,
    available: bool,
    reason: str | None,
) -> dict[str, Any]:
    now_kst = now.astimezone(KST)
    start_date = now_kst.date() - dt.timedelta(days=days - 1)
    return {
        "available": available,
        "reason": reason,
        "window": {
            "start": start_date.isoformat(),
            "end": now_kst.date().isoformat(),
            "days": days,
            "timezone": "Asia/Seoul",
        },
        "measurement": {
            "started_at": None,
            "last_event_at": None,
            "source_trust": "client_claimed",
            "tool_telemetry_available": False,
            "claimed_adapter_requests": 0,
            "requests_with_invocation_id": 0,
            "legacy_or_unattributed_requests": 0,
            "invocation_coverage": None,
            "limitations": [
                "MCP attribution and client metadata are claims, not proof of a particular host.",
                "Counts measure authenticated accounts and events, not people or commercial adoption.",
                "Tool telemetry requires an updated adapter and may be incomplete during ingestion outages.",
            ],
        },
        "totals": {
            "requests": 0, "active_accounts": 0, "tool_calls": 0,
            "tool_successes": 0, "tool_failures": 0, "tool_unknown": 0,
            "jobs_started": 0, "jobs_completed": 0, "jobs_failed": 0,
            "jobs_pending": 0, "request_error_rate": None, "request_p95_ms": None,
            "tool_p95_ms": None, "job_p95_ms": None, "repeat_accounts": 0,
        },
        "daily": [],
        "tools": [],
        "routes": [],
        "clients": [],
        "versions": [],
        "jobs": [],
        "errors": [],
    }


def build_mcp_usage_report(
    db_path: Path | str | None = None,
    *,
    days: int,
    include_internal: bool = False,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Build the independent admin report using KST calendar-day cohorts."""
    if days not in (7, 28, 90):
        raise ValueError("days must be one of 7, 28, 90")
    current = now or _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    report = _empty_report(days, current, available=False, reason="not_instrumented")
    path = Path(db_path) if db_path is not None else mcp_analytics_db_path()
    if not path.exists():
        return report

    start_date = current.astimezone(KST).date() - dt.timedelta(days=days - 1)
    start_utc = dt.datetime.combine(start_date, dt.time.min, tzinfo=KST).astimezone(dt.timezone.utc)
    end_utc = current.astimezone(dt.timezone.utc)
    try:
        conn = _connect(path)
        try:
            initialized = conn.execute(
                "SELECT value FROM mcp_usage_metadata WHERE key='initialized_at'"
            ).fetchone()
            role_sql = (
                ""
                if include_internal
                else " AND COALESCE(actor_role,'') NOT IN ('admin','internal')"
            )
            rows = conn.execute(
                f"""
                SELECT * FROM mcp_usage_events
                WHERE (
                    (kind != 'job' AND created_at >= ? AND created_at <= ?)
                    OR (kind = 'job' AND (
                        (started_at >= ? AND started_at <= ?)
                        OR (started_at IS NULL AND created_at >= ? AND created_at <= ?)
                    ))
                ){role_sql}
                """,
                (
                    _iso(start_utc), _iso(end_utc), _iso(start_utc),
                    _iso(end_utc), _iso(start_utc), _iso(end_utc),
                ),
            ).fetchall()
            all_last = conn.execute(
                "SELECT MAX(updated_at) AS value FROM mcp_usage_events"
            ).fetchone()["value"]
            telemetry = conn.execute(
                "SELECT 1 FROM mcp_usage_events WHERE kind='tool' AND source='adapter_report' LIMIT 1"
            ).fetchone() is not None
        finally:
            conn.close()
    except Exception:
        logger.exception("failed to build MCP analytics report")
        unavailable = _empty_report(days, current, available=False, reason="unavailable")
        return unavailable

    report["available"] = True
    report["reason"] = None
    report["measurement"]["started_at"] = initialized["value"] if initialized else None
    report["measurement"]["last_event_at"] = all_last
    report["measurement"]["tool_telemetry_available"] = telemetry

    requests = [r for r in rows if r["kind"] == "request"]
    tools = [r for r in rows if r["kind"] == "tool"]
    jobs = [r for r in rows if r["kind"] == "job"]
    request_errors = [
        r for r in requests
        if r["status"] in {"failed", "cancelled"} or (r["http_status"] or 0) >= 400
    ]
    tool_success = [r for r in tools if r["status"] == "succeeded"]
    tool_failed = [r for r in tools if r["status"] in {"failed", "cancelled"}]
    tool_unknown = [r for r in tools if r["status"] in {"started", "unknown"}]

    started_jobs = [r for r in jobs if r["started_at"]]
    completed_jobs = [r for r in started_jobs if r["status"] == "succeeded"]
    failed_jobs = [r for r in started_jobs if r["status"] in {"failed", "cancelled"}]
    stale_before = current.astimezone(dt.timezone.utc) - dt.timedelta(hours=24)

    def is_stale_job(row: sqlite3.Row) -> bool:
        if not row["started_at"]:
            return False
        started = dt.datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
        return row["status"] in {"started", "unknown"} and started < stale_before

    pending_jobs = [
        r for r in started_jobs
        if r["status"] == "started" and not is_stale_job(r)
    ]
    report["measurement"].update(
        {
            "claimed_adapter_requests": len(requests),
            "requests_with_invocation_id": sum(bool(r["invocation_id"]) for r in requests),
            "legacy_or_unattributed_requests": sum(not r["invocation_id"] for r in requests),
            "invocation_coverage": (
                round(sum(bool(r["invocation_id"]) for r in requests) / len(requests), 4)
                if requests else None
            ),
        }
    )

    meaningful: dict[str, set[str]] = {}
    for row in requests:
        if (
            row["actor_id"]
            and row["name"] in _MEANINGFUL_REQUESTS
            and row["status"] == "succeeded"
            and row["http_status"] is not None
            and 200 <= row["http_status"] < 400
        ):
            kst_date = dt.datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).astimezone(KST).date().isoformat()
            meaningful.setdefault(row["actor_id"], set()).add(kst_date)
    for row in tools:
        if (
            row["actor_id"]
            and row["name"] in _MEANINGFUL_TOOLS
            and row["status"] == "succeeded"
        ):
            kst_date = dt.datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).astimezone(KST).date().isoformat()
            meaningful.setdefault(row["actor_id"], set()).add(kst_date)
    for row in started_jobs:
        if row["actor_id"]:
            kst_date = dt.datetime.fromisoformat(row["started_at"].replace("Z", "+00:00")).astimezone(KST).date().isoformat()
            meaningful.setdefault(row["actor_id"], set()).add(kst_date)

    request_durations = [r["duration_ms"] for r in requests if r["duration_ms"] is not None]
    tool_durations = [r["duration_ms"] for r in tools if r["duration_ms"] is not None]
    job_durations = [
        r["duration_ms"]
        for r in started_jobs
        if r["status"] in _REAL_TERMINALS and r["duration_ms"] is not None
    ]
    report["totals"] = {
        "requests": len(requests), "active_accounts": len(meaningful), "tool_calls": len(tools),
        "tool_successes": len(tool_success), "tool_failures": len(tool_failed), "tool_unknown": len(tool_unknown),
        "jobs_started": len(started_jobs), "jobs_completed": len(completed_jobs), "jobs_failed": len(failed_jobs),
        "jobs_pending": len(pending_jobs),
        "request_error_rate": round(len(request_errors) / len(requests), 4) if requests else None,
        "request_p95_ms": _percentile_95(request_durations), "tool_p95_ms": _percentile_95(tool_durations),
        "job_p95_ms": _percentile_95(job_durations),
        "repeat_accounts": sum(1 for dates in meaningful.values() if len(dates) >= 2),
    }

    def event_date(row: sqlite3.Row) -> str:
        return dt.datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).astimezone(KST).date().isoformat()

    daily: list[dict[str, Any]] = []
    for offset in range(days):
        date = (start_date + dt.timedelta(days=offset)).isoformat()
        day_requests = [r for r in requests if event_date(r) == date]
        day_tools = [r for r in tools if event_date(r) == date]
        day_started = [
            r for r in started_jobs
            if dt.datetime.fromisoformat(r["started_at"].replace("Z", "+00:00")).astimezone(KST).date().isoformat() == date
        ]
        day_accounts = {actor for actor, dates in meaningful.items() if date in dates}
        daily.append({
            "date": date, "requests": len(day_requests), "active_accounts": len(day_accounts),
            "tool_calls": len(day_tools), "jobs_started": len(day_started),
            "jobs_completed": sum(r["status"] == "succeeded" for r in day_started),
            "jobs_failed": sum(r["status"] in {"failed", "cancelled"} for r in day_started),
        })
    report["daily"] = daily

    for tool_name in sorted({r["name"] for r in tools}):
        group = [r for r in tools if r["name"] == tool_name]
        report["tools"].append({
            "name": tool_name, "calls": len(group),
            "succeeded": sum(r["status"] == "succeeded" for r in group),
            "failed": sum(r["status"] in {"failed", "cancelled"} for r in group),
            "unknown": sum(r["status"] in {"started", "unknown"} for r in group),
            "p95_ms": _percentile_95([r["duration_ms"] for r in group if r["duration_ms"] is not None]),
        })
    report["tools"].sort(key=lambda x: (-x["calls"], x["name"]))

    for route_name in sorted({r["name"] for r in requests}):
        group = [r for r in requests if r["name"] == route_name]
        report["routes"].append({
            "name": route_name, "requests": len(group),
            "errors": sum(r["status"] in {"failed", "cancelled"} or (r["http_status"] or 0) >= 400 for r in group),
            "p95_ms": _percentile_95([r["duration_ms"] for r in group if r["duration_ms"] is not None]),
        })
    report["routes"].sort(key=lambda x: (-x["requests"], x["name"]))

    client_keys = {(r["client_name"] or "Unknown", r["client_version"] or "Unknown") for r in requests + tools}
    for client_name, client_version in client_keys:
        report["clients"].append({
            "name": client_name, "version": client_version,
            "requests": sum((r["client_name"] or "Unknown", r["client_version"] or "Unknown") == (client_name, client_version) for r in requests),
            "tool_calls": sum((r["client_name"] or "Unknown", r["client_version"] or "Unknown") == (client_name, client_version) for r in tools),
        })
    report["clients"].sort(key=lambda x: (-(x["requests"] + x["tool_calls"]), x["name"], x["version"]))

    for version in sorted({r["adapter_version"] or "Unknown" for r in requests + tools}):
        report["versions"].append({
            "version": version,
            "requests": sum((r["adapter_version"] or "Unknown") == version for r in requests),
            "tool_calls": sum((r["adapter_version"] or "Unknown") == version for r in tools),
        })
    report["versions"].sort(key=lambda x: (-(x["requests"] + x["tool_calls"]), x["version"]))

    for job_name in sorted({r["name"] for r in jobs}):
        group = [r for r in jobs if r["name"] == job_name]
        cohort = [r for r in group if r["started_at"]]
        report["jobs"].append({
            "name": job_name, "started": len(cohort),
            "completed": sum(r["status"] == "succeeded" for r in cohort),
            "failed": sum(r["status"] in {"failed", "cancelled"} for r in cohort),
            "pending": sum(r["status"] == "started" and not is_stale_job(r) for r in cohort),
            "unknown": (
                sum(not r["started_at"] for r in group)
                + sum(r["status"] == "unknown" or is_stale_job(r) for r in cohort)
            ),
        })

    error_counts: dict[tuple[str, str], int] = {}
    for row in request_errors:
        code = str(row["http_status"] or row["status"])
        error_counts[("request", code)] = error_counts.get(("request", code), 0) + 1
    for row in tool_failed:
        code = "tool_failed" if row["status"] == "failed" else "cancelled"
        error_counts[("tool", code)] = error_counts.get(("tool", code), 0) + 1
    for row in failed_jobs:
        code = "job_failed" if row["status"] == "failed" else "cancelled"
        error_counts[("job", code)] = error_counts.get(("job", code), 0) + 1
    report["errors"] = [
        {"kind": kind, "code": code, "count": count}
        for (kind, code), count in sorted(error_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return report


__all__ = [
    "TOOL_NAMES",
    "build_mcp_usage_report",
    "delete_actor_events",
    "initialize_mcp_usage",
    "mcp_analytics_db_path",
    "record_event",
    "record_event_async",
]
