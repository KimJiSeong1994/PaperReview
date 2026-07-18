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

from src.analytics.first_party import ALLOWED_FIRST_PARTY_EVENTS

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


def _inclusive_day_span(start_date: str | None, end_date: str) -> int:
    """Inclusive ISO-date span, or zero when no valid start is available."""
    if not start_date:
        return 0
    try:
        start = dt.date.fromisoformat(start_date)
        end = dt.date.fromisoformat(end_date)
    except ValueError:
        return 0
    return max((end - start).days + 1, 0)


# Curated product funnels rendered on the admin report. Each is an ordered list
# of first-party event names; a session counts toward step k only if it fired
# every earlier step at-or-before step k (first-occurrence ordered funnel). No
# extra instrumentation is required — all steps are existing events.
CURATED_FUNNELS: list[dict[str, Any]] = [
    {
        "id": "search_to_review",
        "label": "검색 → 딥리뷰 완료",
        "steps": ["search", "deep_review_start", "deep_review_complete"],
    },
    {
        # Fills the middle: paper_select (opening a result) is optional and not a
        # prerequisite of a review, so it is its own funnel, not a review step.
        "id": "search_to_engagement",
        "label": "검색 → 결과 관여",
        "steps": ["search", "paper_select"],
    },
    {
        "id": "review_to_bookmark",
        "label": "딥리뷰 완료 → 북마크",
        "steps": ["deep_review_complete", "bookmark_save"],
    },
    {
        "id": "onboarding",
        "label": "온보딩 (방문 → 가입 → 검색)",
        "steps": ["page_view", "sign_up", "login", "search"],
    },
    {
        "id": "poster_flow",
        "label": "검색 → 포스터 생성",
        "steps": ["search", "poster_generate_start", "poster_generate_complete"],
    },
]

# Fail fast on a typo'd event name in a curated funnel.
for _f in CURATED_FUNNELS:
    _unknown = set(_f["steps"]) - ALLOWED_FIRST_PARTY_EVENTS
    if _unknown:
        raise ValueError(f"funnel {_f['id']!r} references unknown events: {sorted(_unknown)}")


def _funnel_counts(
    conn: sqlite3.Connection, start_utc: str, steps: list[str]
) -> list[int]:
    """Distinct sessions reaching each ordered step within the window.

    Per session we take the first timestamp of each step event, then require
    each step's first occurrence to be at-or-after the previous step's. Uses
    ``>=`` (not ``>``) because ``created_at`` is second-precision, so adjacent
    steps can share a second; ties are counted as "in order".
    """
    params: dict[str, Any] = {"start_utc": start_utc}
    when_cols = []
    for i, event in enumerate(steps):
        params[f"e{i}"] = event
        when_cols.append(f"MIN(CASE WHEN event_name = :e{i} THEN created_at END) AS t{i}")
    placeholders = ", ".join(f":e{i}" for i in range(len(steps)))

    count_cols = []
    for i in range(len(steps)):
        conds = ["t0 IS NOT NULL"] + [f"t{k} >= t{k - 1}" for k in range(1, i + 1)]
        count_cols.append(
            f"COUNT(DISTINCT CASE WHEN {' AND '.join(conds)} THEN session_id END) AS s{i}"
        )

    sql = f"""
    WITH step_times AS (
      SELECT session_id, {', '.join(when_cols)}
      FROM app_analytics_events
      WHERE created_at >= :start_utc AND event_name IN ({placeholders})
      GROUP BY session_id
    )
    SELECT {', '.join(count_cols)} FROM step_times
    """
    row = conn.execute(sql, params).fetchone()
    return [row[f"s{i}"] or 0 for i in range(len(steps))]


def build_funnel_report(
    conn: sqlite3.Connection, start_utc: str, funnel: dict[str, Any]
) -> dict[str, Any]:
    """One curated funnel: per-step session counts, conversion rate, drop-off."""
    counts = _funnel_counts(conn, start_utc, funnel["steps"])
    base = counts[0] or 0
    steps = [
        {
            "event": event,
            "count": counts[i],
            "rate": round(counts[i] / base, 3) if base else 0.0,
            "drop_off": (counts[i - 1] - counts[i]) if i > 0 else 0,
        }
        for i, event in enumerate(funnel["steps"])
    ]
    return {
        "id": funnel["id"],
        "label": funnel["label"],
        "steps": steps,
        "overall_conversion": round(counts[-1] / base, 3) if base else 0.0,
    }


def build_deep_review_outcome(conn: sqlite3.Connection, start_utc: str) -> dict[str, int]:
    """Split deep-review sessions by terminal outcome: complete vs fail vs
    abandon. Answers "did it fail or did the user just leave?" — a session that
    started counts as completed if it later completed, else failed if it later
    failed, else abandoned (started, no terminal event)."""
    row = conn.execute(
        """
        WITH s AS (
          SELECT session_id,
            MIN(CASE WHEN event_name = 'deep_review_start' THEN created_at END) AS t_start,
            MIN(CASE WHEN event_name = 'deep_review_complete' THEN created_at END) AS t_done,
            MIN(CASE WHEN event_name = 'deep_review_fail' THEN created_at END) AS t_fail
          FROM app_analytics_events
          WHERE created_at >= :start_utc
            AND event_name IN
              ('deep_review_start', 'deep_review_complete', 'deep_review_fail')
          GROUP BY session_id
        )
        SELECT
          COUNT(DISTINCT CASE WHEN t_start IS NOT NULL THEN session_id END) AS started,
          COUNT(DISTINCT CASE WHEN t_start IS NOT NULL AND t_done >= t_start
                              THEN session_id END) AS completed,
          COUNT(DISTINCT CASE WHEN t_start IS NOT NULL AND t_fail >= t_start
                              AND (t_done IS NULL OR t_done < t_start)
                              THEN session_id END) AS failed
        FROM s
        """,
        {"start_utc": start_utc},
    ).fetchone()
    started = row["started"] or 0
    completed = row["completed"] or 0
    failed = row["failed"] or 0
    return {
        "started": started,
        "completed": completed,
        "failed": failed,
        "abandoned": max(started - completed - failed, 0),
    }


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
    requested_start_date = (now_kst.date() - dt.timedelta(days=days - 1)).isoformat()
    window_end_date = now_kst.date().isoformat()
    conn = _connect(db_path)
    try:
        params = {"start_utc": start_utc, "top_limit": top_limit}

        measurement_row = conn.execute(
            """
            SELECT
              MIN(created_at) AS first_event_at,
              MAX(received_at) AS last_event_at,
              substr(datetime(MIN(created_at), '+9 hours'), 1, 10)
                AS first_event_date
            FROM app_analytics_events
            """
        ).fetchone()

        window_measurement_row = conn.execute(
            """
            SELECT
              COUNT(*) AS event_count,
              COUNT(DISTINCT substr(datetime(created_at, '+9 hours'), 1, 10))
                AS observed_days
            FROM app_analytics_events
            WHERE created_at >= :start_utc
            """,
            params,
        ).fetchone()

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

        engaged_sessions = conn.execute(
            f"SELECT COUNT(*) AS n FROM ({_ENGAGED_SESSION_SQL})", params
        ).fetchone()["n"]

        single_page_sessions = conn.execute(
            """
            SELECT COUNT(*) AS n FROM (
              SELECT session_id
              FROM app_analytics_events
              WHERE created_at >= :start_utc
              GROUP BY session_id
              HAVING COUNT(*) = 1
            )
            """,
            params,
        ).fetchone()["n"]

        funnels = [build_funnel_report(conn, start_utc, f) for f in CURATED_FUNNELS]
        deep_review_outcome = build_deep_review_outcome(conn, start_utc)

        ga4 = _ga4_status(conn, start_utc, top_limit)
    finally:
        conn.close()

    peak_hour = max(range(24), key=lambda h: hour_of_day[h]) if any(hour_of_day) else None
    peak_dow = max(range(7), key=lambda d: day_of_week[d]) if any(day_of_week) else None

    sessions_total = totals["sessions"] or 0
    page_views_total = totals["page_views"] or 0
    daily_visitor_total = sum(int(row["visitors"] or 0) for row in daily)
    first_event_date = measurement_row["first_event_date"]
    history_start_date = max(first_event_date, requested_start_date) if first_event_date else None
    history_days = min(_inclusive_day_span(history_start_date, window_end_date), days)

    return {
        "window": {
            "days": days,
            "start": requested_start_date,
            "end": window_end_date,
            "timezone": "Asia/Seoul",
        },
        "measurement": {
            "population": "consented_browser_events",
            "session_definition": "browser_tab_lifetime",
            "first_event_at": measurement_row["first_event_at"],
            "last_event_at": measurement_row["last_event_at"],
            "history_days": history_days,
            "observed_days": window_measurement_row["observed_days"] or 0,
            "event_count": window_measurement_row["event_count"] or 0,
        },
        "traffic": {
            "totals": {
                "visitors": totals["visitors"] or 0,
                "sessions": sessions_total,
                "page_views": page_views_total,
                "signed_in_users": totals["signed_in_users"] or 0,
                "returning_visitors": returning or 0,
                "new_visitors": max((totals["visitors"] or 0) - (returning or 0), 0),
                # A visitor may appear on multiple days. Sum each day's
                # distinct visitors before dividing by the requested window.
                "avg_daily_visitors": round(daily_visitor_total / days, 1),
                "engaged_sessions": engaged_sessions,
                "engaged_rate": round(engaged_sessions / sessions_total, 3)
                if sessions_total
                else 0.0,
                "bounce_rate": round(single_page_sessions / sessions_total, 3)
                if sessions_total
                else 0.0,
                "pages_per_session": round(page_views_total / sessions_total, 1)
                if sessions_total
                else 0.0,
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
        "funnels": funnels,
        "deep_review_outcome": deep_review_outcome,
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
