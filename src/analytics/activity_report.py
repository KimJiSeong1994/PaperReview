"""Admin ACTIVITY / PRODUCT metrics aggregation.

Parallel to ``visits_report.py`` (which covers anonymous browser traffic), this
module reports on *authenticated product usage*: signups, active users,
searches, bookmarks and deep-review pipeline health. It reads the durable,
user-attributed stores that already exist —

* ``events.db``  → ``user_events`` ledger (query/search/bookmark/login events)
* ``users.db``   → account signups (``created_at``, ``role``)
* ``bookmarks.db`` → saved bookmarks (``topic``, ``created_at``)
* ``reviews.db`` → durable deep-review sessions (see ``review_store``)

All daily bucketing converts to KST via ``datetime(..., '+9 hours')`` so the
series match how the (Korean) admin thinks about days, mirroring
``visits_report``. The response contract is frozen; genuinely infeasible fields
are returned as ``null``/``[]`` with an explanation appended to ``notes``.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

from src.analytics import review_store

KST = dt.timezone(dt.timedelta(hours=9))

# ── Deep-review cost proxy ────────────────────────────────────────────
# ponytail: cost proxy — replace with real token accounting when captured.
# input_tokens/output_tokens columns exist on review_sessions for that upgrade;
# until the pipeline surfaces token counts these constants stand in.
_REVIEW_COST_FAST_USD = 0.05  # flat cost of one fast-mode review
_REVIEW_COST_FULL_USD = 0.40  # cost of one full deep review, per researcher


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _window_start_utc(days: int, now: dt.datetime | None = None) -> str:
    """UTC ISO timestamp of KST midnight ``days - 1`` days ago.

    The window covers ``days`` KST calendar days including today, matching the
    daily buckets the report renders. Format mirrors events.db (``...Z``) so
    lexical ``created_at >= start`` comparisons are correct.
    """
    now_kst = (now or dt.datetime.now(dt.timezone.utc)).astimezone(KST)
    start_kst = (now_kst - dt.timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start_kst.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kst_date(ts: str) -> str | None:
    """KST calendar date (YYYY-MM-DD) for an ISO timestamp.

    Timezone-aware values are converted to KST; naive values (legacy rows
    written in server-local KST) are taken as-is. Returns ``None`` on any
    unparseable/empty input so callers can skip it.
    """
    if not ts:
        return None
    try:
        parsed = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts[:10] or None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KST)
    return parsed.date().isoformat()


def _percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile of a value list (``None`` if empty)."""
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * (len(ordered) - 1)))))
    return round(ordered[k], 1)


# ── Section builders ──────────────────────────────────────────────────


def _growth(users_db: Path, start_utc: str) -> dict[str, Any]:
    conn = _connect(users_db)
    try:
        total = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        rows = conn.execute(
            """
            SELECT substr(datetime(created_at, '+9 hours'), 1, 10) AS date,
                   COUNT(*) AS count
            FROM users
            WHERE created_at IS NOT NULL AND created_at != ''
              AND created_at >= :start
            GROUP BY 1 ORDER BY 1
            """,
            {"start": start_utc},
        ).fetchall()
    finally:
        conn.close()
    series = [{"date": r["date"], "count": r["count"]} for r in rows if r["date"]]
    return {
        "signups_series": series,
        "total_users": total or 0,
        "new_users_in_window": sum(r["count"] for r in series),
    }


def _active_users(events_db: Path, start_utc: str, now: dt.datetime | None) -> dict[str, Any]:
    conn = _connect(events_db)
    try:

        def distinct_since(since: str) -> int:
            return conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS n FROM user_events WHERE created_at >= ?",
                (since,),
            ).fetchone()["n"] or 0

        dau = distinct_since(_window_start_utc(1, now))
        wau = distinct_since(_window_start_utc(7, now))
        mau = distinct_since(_window_start_utc(30, now))
        series = [
            {"date": r["date"], "active": r["active"]}
            for r in conn.execute(
                """
                SELECT substr(datetime(created_at, '+9 hours'), 1, 10) AS date,
                       COUNT(DISTINCT user_id) AS active
                FROM user_events
                WHERE created_at >= :start
                GROUP BY 1 ORDER BY 1
                """,
                {"start": start_utc},
            ).fetchall()
            if r["date"]
        ]
    finally:
        conn.close()
    return {
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "stickiness": round(dau / mau, 3) if mau else 0.0,
        "active_series": series,
        "basis": (
            "Distinct user_id with any user_events row per KST day; now includes "
            "durable 'login' events. Read-only users who never emit an event are "
            "still under-counted."
        ),
    }


def _search(events_db: Path, start_utc: str) -> dict[str, Any]:
    conn = _connect(events_db)
    try:
        series = [
            {"date": r["date"], "count": r["count"]}
            for r in conn.execute(
                """
                SELECT substr(datetime(created_at, '+9 hours'), 1, 10) AS date,
                       COUNT(*) AS count
                FROM user_events
                WHERE event_type = 'query_submit' AND created_at >= :start
                GROUP BY 1 ORDER BY 1
                """,
                {"start": start_utc},
            ).fetchall()
            if r["date"]
        ]
        total_queries = conn.execute(
            "SELECT COUNT(*) AS n FROM user_events WHERE event_type='query_submit' AND created_at >= ?",
            (start_utc,),
        ).fetchone()["n"] or 0
        clicks = conn.execute(
            "SELECT COUNT(*) AS n FROM user_events WHERE event_type='search_click' AND created_at >= ?",
            (start_utc,),
        ).fetchone()["n"] or 0
        payload_rows = conn.execute(
            "SELECT payload FROM user_events WHERE event_type='query_submit' AND created_at >= ?",
            (start_utc,),
        ).fetchall()
    finally:
        conn.close()

    # Raw query text is not stored (privacy) — only a query_hash. Rank by hash.
    hist: dict[str, int] = {}
    for r in payload_rows:
        try:
            key = json.loads(r["payload"]).get("query_hash")
        except (json.JSONDecodeError, TypeError):
            key = None
        if key:
            hist[key] = hist.get(key, 0) + 1
    top_queries = [
        {"query": k, "count": v}
        for k, v in sorted(hist.items(), key=lambda kv: kv[1], reverse=True)[:20]
    ]
    return {
        "query_series": series,
        "total_queries": total_queries,
        "top_queries": top_queries,
        "click_through_rate": round(clicks / total_queries, 3) if total_queries else 0.0,
    }


def _bookmarks(events_db: Path, bookmarks_db: Path, start_utc: str) -> dict[str, Any]:
    conn = _connect(events_db)
    try:

        def series_for(event_type: str) -> list[dict[str, Any]]:
            return [
                {"date": r["date"], "count": r["count"]}
                for r in conn.execute(
                    """
                    SELECT substr(datetime(created_at, '+9 hours'), 1, 10) AS date,
                           COUNT(*) AS count
                    FROM user_events
                    WHERE event_type = :et AND created_at >= :start
                    GROUP BY 1 ORDER BY 1
                    """,
                    {"et": event_type, "start": start_utc},
                ).fetchall()
                if r["date"]
            ]

        add_series = series_for("bookmark_add")
        remove_series = series_for("bookmark_remove")
    finally:
        conn.close()

    bconn = _connect(bookmarks_db)
    try:
        top_topics = [
            {"topic": r["topic"], "count": r["count"]}
            for r in bconn.execute(
                """
                SELECT topic, COUNT(*) AS count
                FROM bookmarks
                WHERE topic IS NOT NULL AND topic != '' AND created_at >= :start
                GROUP BY topic ORDER BY count DESC LIMIT 20
                """,
                {"start": start_utc},
            ).fetchall()
        ]
    finally:
        bconn.close()

    net = sum(s["count"] for s in add_series) - sum(s["count"] for s in remove_series)
    return {
        "add_series": add_series,
        "remove_series": remove_series,
        "net_in_window": net,
        "top_topics": top_topics,
    }


def _reviews(start_utc: str, reviews_db: Path) -> dict[str, Any]:
    sessions = review_store.load_sessions_since(start_utc, db_path=reviews_db)

    create_hist: dict[str, int] = {}
    researcher_hist: dict[str, int] = {}
    failure_hist: dict[str, int] = {}
    durations: list[float] = []
    fast_flags: list[int] = []
    cost = 0.0
    completed = failed = 0

    for s in sessions:
        date = _kst_date(s.get("created_at", ""))
        if date:
            create_hist[date] = create_hist.get(date, 0) + 1

        status = s.get("status")
        if status == "completed":
            completed += 1
        elif status == "failed":
            failed += 1
            reason = (s.get("error") or "unknown")[:200]
            failure_hist[reason] = failure_hist.get(reason, 0) + 1

        nr = s.get("num_researchers")
        if nr is not None:
            researcher_hist[str(nr)] = researcher_hist.get(str(nr), 0) + 1

        fm = s.get("fast_mode")
        if fm is not None:
            fast_flags.append(int(fm))

        # Duration only for rows that actually completed with both timestamps.
        if s.get("completed_at") and s.get("created_at"):
            try:
                t0 = dt.datetime.fromisoformat(s["created_at"].replace("Z", "+00:00"))
                t1 = dt.datetime.fromisoformat(s["completed_at"].replace("Z", "+00:00"))
                secs = (t1 - t0).total_seconds()
                if secs >= 0:
                    durations.append(secs)
            except (ValueError, AttributeError):
                pass

        # Cost proxy: fast → flat; full → per-researcher.
        if fm == 1:
            cost += _REVIEW_COST_FAST_USD
        else:
            cost += _REVIEW_COST_FULL_USD * (nr or 1)

    started = len(sessions)
    terminal = completed + failed
    create_series = [{"date": d, "count": c} for d, c in sorted(create_hist.items())]
    failure_reasons = [
        {"reason": r, "count": c}
        for r, c in sorted(failure_hist.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return {
        "create_series": create_series,
        "started": started,
        "completed": completed,
        "failed": failed,
        "success_rate": round(completed / terminal, 3) if terminal else 0.0,
        "duration_p50_s": _percentile(durations, 50),
        "duration_p90_s": _percentile(durations, 90),
        "duration_p99_s": _percentile(durations, 99),
        "fast_mode_share": round(sum(fast_flags) / len(fast_flags), 3) if fast_flags else 0.0,
        "researcher_hist": researcher_hist,
        "failure_reasons": failure_reasons,
        "cost_estimate_usd": round(cost, 2),
        "basis": (
            "Durable review_sessions table (survives the 24h in-memory TTL and "
            "restarts). Durations are wall-clock created→completed. cost_estimate_usd "
            "is a proxy (fast/full base scaled by researchers), not real token cost. "
            "Rows backfilled from workspace metadata lack duration/researcher/fast_mode."
        ),
    }


def _recent_activity_by_user(events_db: Path, start_utc: str) -> list[dict[str, Any]]:
    conn = _connect(events_db)
    try:
        rows = conn.execute(
            """
            SELECT user_id,
                   substr(datetime(MAX(created_at), '+9 hours'), 1, 10) AS last_active,
                   COUNT(*) AS events_in_window
            FROM user_events
            WHERE created_at >= :start
            GROUP BY user_id
            ORDER BY events_in_window DESC
            LIMIT 50
            """,
            {"start": start_utc},
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "username": r["user_id"],
            "last_active": r["last_active"],
            "events_in_window": r["events_in_window"],
        }
        for r in rows
    ]


_METRIC_DEFINITIONS: dict[str, str] = {
    "growth.signups_series": "Accounts created per KST day (users.db created_at); sums to new_users_in_window.",
    "active_users.dau/wau/mau": "Distinct user_id with any events in the last 1/7/30 KST days (independent of the days param).",
    "active_users.stickiness": "DAU / MAU. 0 when MAU is 0.",
    "active_users.active_series": "Distinct active users per KST day across the selected window.",
    "search.click_through_rate": "search_click count / query_submit count in window (0 if no queries).",
    "search.top_queries": "Top query_hash values (raw query text is not stored; only a privacy hash).",
    "bookmarks.add_series/remove_series": "bookmark_add / bookmark_remove events per KST day (events.db).",
    "bookmarks.top_topics": "Most common bookmark topics saved in window (bookmarks.db).",
    "reviews.*": "Deep-review pipeline health from the durable review_sessions table.",
    "reviews.cost_estimate_usd": "PROXY cost (fast/full base scaled by researchers), not measured tokens.",
    "recent_activity_by_user": "Per user: last_active = max event date in window, ranked by event count (top 50).",
}


def build_activity_report(
    events_db: Path,
    users_db: Path,
    bookmarks_db: Path,
    reviews_db: Path = review_store.REVIEWS_DB_PATH,
    *,
    days: int,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Aggregate authenticated product-usage metrics for the given KST window.

    Parameters
    ----------
    events_db, users_db, bookmarks_db, reviews_db:
        Paths to the four backing SQLite stores.
    days:
        Window size in KST days (validated by the caller to 7/28/90).
    now:
        Injectable clock for deterministic tests.
    """
    start_utc = _window_start_utc(days, now)
    generated_at = (now or dt.datetime.now(dt.timezone.utc)).astimezone(
        dt.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    notes: list[str] = [
        "search.top_queries is keyed by query_hash — raw query text is not stored "
        "(privacy); each hash still reveals repeat-query volume.",
        "reviews.cost_estimate_usd is a proxy, not measured token cost.",
    ]

    search = _search(events_db, start_utc)
    reviews = _reviews(start_utc, reviews_db)
    if all(
        reviews[k] is None for k in ("duration_p50_s", "duration_p90_s", "duration_p99_s")
    ):
        notes.append(
            "review duration percentiles are null — no sessions with a recorded "
            "completed_at in this window (e.g. only backfilled/legacy rows)."
        )

    return {
        "window_days": days,
        "generated_at": generated_at,
        "growth": _growth(users_db, start_utc),
        "active_users": _active_users(events_db, start_utc, now),
        "search": search,
        "bookmarks": _bookmarks(events_db, bookmarks_db, start_utc),
        "reviews": reviews,
        "recent_activity_by_user": _recent_activity_by_user(events_db, start_utc),
        "metric_definitions": _METRIC_DEFINITIONS,
        "notes": notes,
    }


__all__ = ["build_activity_report"]
