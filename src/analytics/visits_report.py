"""Admin visits-report aggregations over first-party analytics events.

Everything here reads the single-host SQLite ``analytics.db`` written by
``src.analytics.first_party`` (events) and ``ga4_bigquery_sync`` (GA4
aggregates + sync run log). Timestamps in ``app_analytics_events`` are UTC
ISO-8601; all user-facing bucketing (daily series, hour-of-day, weekday)
converts to KST via SQLite's ``datetime(..., '+9 hours')`` so the dashboard
matches how the (Korean) admin thinks about days.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from pathlib import Path
from typing import Any

KST = dt.timezone(dt.timedelta(hours=9))

# Sessions with more than one page_view, or any non-page_view product event,
# count as "engaged" (mirrors GA4's engaged-session idea without timers).
_ENGAGED_SESSION_SQL = """
SELECT session_id
FROM app_analytics_events
WHERE created_at >= :start_utc
GROUP BY session_id
HAVING SUM(CASE WHEN event_name = 'page_view' THEN 1 ELSE 0 END) > 1
    OR SUM(CASE WHEN event_name != 'page_view' THEN 1 ELSE 0 END) > 0
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _window_start_utc(days: int, now: dt.datetime | None = None) -> str:
    """UTC ISO timestamp of local-KST midnight ``days - 1`` days ago.

    The window covers ``days`` KST calendar days including today, matching
    the daily buckets the report renders.
    """
    now_kst = (now or dt.datetime.now(dt.timezone.utc)).astimezone(KST)
    start_kst = (now_kst - dt.timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start_kst.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_visits_report(
    db_path: Path,
    *,
    days: int,
    top_limit: int = 10,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Aggregate the first-party event log into the admin visits report."""
    start_utc = _window_start_utc(days, now)
    now_kst = (now or dt.datetime.now(dt.timezone.utc)).astimezone(KST)
    conn = _connect(db_path)
    try:
        params = {"start_utc": start_utc, "top_limit": top_limit}

        totals = conn.execute(
            """
            SELECT
              COUNT(DISTINCT client_id) AS visitors,
              COUNT(DISTINCT session_id) AS sessions,
              SUM(CASE WHEN event_name = 'page_view' THEN 1 ELSE 0 END) AS page_views,
              COUNT(DISTINCT CASE WHEN user_id IS NOT NULL THEN user_id END)
                AS signed_in_users
            FROM app_analytics_events
            WHERE created_at >= :start_utc
            """,
            params,
        ).fetchone()

        returning = conn.execute(
            """
            SELECT COUNT(DISTINCT e.client_id) AS n
            FROM app_analytics_events e
            WHERE e.created_at >= :start_utc
              AND EXISTS (
                SELECT 1 FROM app_analytics_events p
                WHERE p.client_id = e.client_id AND p.created_at < :start_utc
              )
            """,
            params,
        ).fetchone()["n"]

        daily = [
            dict(r)
            for r in conn.execute(
                """
                SELECT
                  substr(datetime(created_at, '+9 hours'), 1, 10) AS date,
                  COUNT(DISTINCT client_id) AS visitors,
                  COUNT(DISTINCT session_id) AS sessions,
                  SUM(CASE WHEN event_name = 'page_view' THEN 1 ELSE 0 END)
                    AS page_views
                FROM app_analytics_events
                WHERE created_at >= :start_utc
                GROUP BY 1 ORDER BY 1
                """,
                params,
            )
        ]

        hour_rows = conn.execute(
            """
            SELECT CAST(strftime('%H', datetime(created_at, '+9 hours')) AS INTEGER) AS h,
                   COUNT(*) AS n
            FROM app_analytics_events
            WHERE created_at >= :start_utc AND event_name = 'page_view'
            GROUP BY 1
            """,
            params,
        ).fetchall()
        hour_of_day = [0] * 24
        for r in hour_rows:
            hour_of_day[r["h"]] = r["n"]

        dow_rows = conn.execute(
            """
            SELECT CAST(strftime('%w', datetime(created_at, '+9 hours')) AS INTEGER) AS d,
                   COUNT(*) AS n
            FROM app_analytics_events
            WHERE created_at >= :start_utc AND event_name = 'page_view'
            GROUP BY 1
            """,
            params,
        ).fetchall()
        day_of_week = [0] * 7  # 0 = Sunday (strftime %w)
        for r in dow_rows:
            day_of_week[r["d"]] = r["n"]

        top_pages = [
            dict(r)
            for r in conn.execute(
                """
                SELECT page_path AS path,
                       COUNT(*) AS page_views,
                       COUNT(DISTINCT client_id) AS visitors
                FROM app_analytics_events
                WHERE created_at >= :start_utc AND event_name = 'page_view'
                GROUP BY 1 ORDER BY page_views DESC, visitors DESC
                LIMIT :top_limit
                """,
                params,
            )
        ]

        landing = [
            dict(r)
            for r in conn.execute(
                f"""
                WITH firsts AS (
                  SELECT session_id, page_path,
                         ROW_NUMBER() OVER (
                           PARTITION BY session_id ORDER BY created_at, id
                         ) AS rn
                  FROM app_analytics_events
                  WHERE created_at >= :start_utc AND event_name = 'page_view'
                ),
                engaged AS ({_ENGAGED_SESSION_SQL})
                SELECT f.page_path AS path,
                       COUNT(*) AS sessions,
                       ROUND(AVG(CASE WHEN e.session_id IS NOT NULL THEN 1.0 ELSE 0.0 END), 3)
                         AS engaged_rate
                FROM firsts f
                LEFT JOIN engaged e ON e.session_id = f.session_id
                WHERE f.rn = 1
                GROUP BY 1 ORDER BY sessions DESC
                LIMIT :top_limit
                """,
                params,
            )
        ]

        utm_sources = [
            dict(r)
            for r in conn.execute(
                """
                SELECT utm_source, utm_medium,
                       SUM(page_views) AS page_views,
                       SUM(sessions) AS sessions
                FROM app_daily_blog_utm_metrics
                WHERE event_date >= substr(datetime(:start_utc, '+9 hours'), 1, 10)
                  AND utm_source IS NOT NULL
                GROUP BY 1, 2 ORDER BY page_views DESC
                LIMIT :top_limit
                """,
                params,
            )
        ]

        product_events = {
            r["event_name"]: r["n"]
            for r in conn.execute(
                """
                SELECT event_name, COUNT(*) AS n
                FROM app_analytics_events
                WHERE created_at >= :start_utc AND event_name != 'page_view'
                GROUP BY 1
                """,
                params,
            )
        }

        ga4 = _ga4_status(conn, start_utc, top_limit)
    finally:
        conn.close()

    peak_hour = max(range(24), key=lambda h: hour_of_day[h]) if any(hour_of_day) else None
    peak_dow = max(range(7), key=lambda d: day_of_week[d]) if any(day_of_week) else None

    return {
        "window": {
            "days": days,
            "start": daily[0]["date"] if daily else now_kst.strftime("%Y-%m-%d"),
            "end": now_kst.strftime("%Y-%m-%d"),
            "timezone": "Asia/Seoul",
        },
        "traffic": {
            "totals": {
                "visitors": totals["visitors"] or 0,
                "sessions": totals["sessions"] or 0,
                "page_views": totals["page_views"] or 0,
                "signed_in_users": totals["signed_in_users"] or 0,
                "returning_visitors": returning or 0,
                "new_visitors": max((totals["visitors"] or 0) - (returning or 0), 0),
                "avg_daily_visitors": round((totals["visitors"] or 0) / days, 1),
            },
            "daily": daily,
        },
        "timing": {
            "hour_of_day": hour_of_day,
            "day_of_week": day_of_week,
            "peak_hour": peak_hour,
            "peak_day_of_week": peak_dow,
        },
        "top_pages": top_pages,
        "landing": landing,
        "acquisition": {"utm_sources": utm_sources},
        "product_events": product_events,
        "ga4": ga4,
    }


# A "dataset not found" sync error is not a real failure: GA4's BigQuery
# export only creates the dataset once the property receives its first data,
# so until then the dashboard should read as "waiting to connect", not "failed".
_DATASET_MISSING_RE = re.compile(r"not\s*found.*dataset|dataset.*not\s*found", re.IGNORECASE)


def _classify_ga4_state(last_run: dict[str, Any] | None, has_channels: bool) -> str:
    """Return a UI-facing GA4 state: connected / pending / failed / never_run."""
    if has_channels:
        return "connected"
    if last_run is None:
        return "never_run"
    if last_run.get("status") == "success":
        return "connected"
    error = str(last_run.get("error") or "")
    if _DATASET_MISSING_RE.search(error):
        return "pending"
    return "failed"


def _ga4_status(conn: sqlite3.Connection, start_utc: str, top_limit: int) -> dict[str, Any]:
    """GA4 sync health + channel breakdown when data exists.

    Degrades gracefully: always reports the last run and a UI-facing ``state``,
    and includes channel data only when rows are present. A missing export
    dataset is surfaced as ``pending`` rather than ``failed`` — the export
    materializes the dataset only after GA4 first receives data.
    """
    last_run_row = conn.execute(
        """
        SELECT sync_finished_at, status, error, rows_daily
        FROM ga_sync_runs ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    last_run = dict(last_run_row) if last_run_row else None
    if last_run and last_run.get("error"):
        last_run["error"] = str(last_run["error"]).split("\n", 1)[0][:200]

    start_date = start_utc[:10]
    channels = [
        dict(r)
        for r in conn.execute(
            """
            SELECT source, medium,
                   SUM(total_users) AS users,
                   SUM(sessions) AS sessions
            FROM ga_daily_metrics
            WHERE event_date >= :start_date
            GROUP BY 1, 2 ORDER BY users DESC
            LIMIT :top_limit
            """,
            {"start_date": start_date, "top_limit": top_limit},
        )
    ]
    return {
        "available": bool(channels),
        "state": _classify_ga4_state(last_run, bool(channels)),
        "last_run": last_run,
        "channels": channels,
    }
