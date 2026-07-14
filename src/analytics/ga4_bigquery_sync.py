"""Sync privacy-safe GA4 BigQuery daily aggregates into analytics.db.

The GA4 BigQuery export is event-level. This module only persists daily
aggregates and deliberately excludes GA pseudo IDs, app usernames, raw search
queries, tokens, titles, or event parameter blobs from the local database.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

logger = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_DATASET_RE = re.compile(r"^[A-Za-z0-9_]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_ANALYTICS_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS ga_daily_metrics (
        event_date      TEXT NOT NULL,
        property_id     TEXT NOT NULL,
        source          TEXT NOT NULL DEFAULT '(unknown)',
        medium          TEXT NOT NULL DEFAULT '(unknown)',
        device_category TEXT NOT NULL DEFAULT '(unknown)',
        country         TEXT NOT NULL DEFAULT '(unknown)',
        total_users     INTEGER NOT NULL DEFAULT 0,
        sessions        INTEGER NOT NULL DEFAULT 0,
        page_views      INTEGER NOT NULL DEFAULT 0,
        event_count     INTEGER NOT NULL DEFAULT 0,
        synced_at       TEXT NOT NULL,
        PRIMARY KEY (
            event_date, property_id, source, medium, device_category, country
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ga_daily_event_metrics (
        event_date  TEXT NOT NULL,
        property_id TEXT NOT NULL,
        event_name  TEXT NOT NULL,
        event_count INTEGER NOT NULL DEFAULT 0,
        total_users INTEGER NOT NULL DEFAULT 0,
        synced_at   TEXT NOT NULL,
        PRIMARY KEY (event_date, property_id, event_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ga_daily_page_metrics (
        event_date  TEXT NOT NULL,
        property_id TEXT NOT NULL,
        page_path   TEXT NOT NULL,
        page_views  INTEGER NOT NULL DEFAULT 0,
        total_users INTEGER NOT NULL DEFAULT 0,
        synced_at   TEXT NOT NULL,
        PRIMARY KEY (event_date, property_id, page_path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ga_sync_runs (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        sync_started_at  TEXT NOT NULL,
        sync_finished_at TEXT,
        status           TEXT NOT NULL,
        start_date       TEXT NOT NULL,
        end_date         TEXT NOT NULL,
        project_id       TEXT NOT NULL,
        dataset          TEXT NOT NULL,
        property_id      TEXT NOT NULL,
        rows_daily       INTEGER NOT NULL DEFAULT 0,
        rows_events      INTEGER NOT NULL DEFAULT 0,
        rows_pages       INTEGER NOT NULL DEFAULT 0,
        error            TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_analytics_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT,
        client_id   TEXT NOT NULL,
        session_id  TEXT NOT NULL,
        event_name  TEXT NOT NULL,
        page_path   TEXT NOT NULL,
        payload     TEXT NOT NULL DEFAULT '{}',
        source      TEXT NOT NULL DEFAULT 'first_party',
        created_at  TEXT NOT NULL,
        received_at TEXT NOT NULL
    )
    """,
    """
    CREATE VIEW IF NOT EXISTS app_daily_user_event_metrics AS
    SELECT
        substr(created_at, 1, 10) AS event_date,
        COALESCE(user_id, '(anonymous)') AS user_id,
        event_name,
        COUNT(*) AS event_count,
        MAX(created_at) AS last_event_at
    FROM app_analytics_events
    GROUP BY event_date, user_id, event_name
    """,
    """
    CREATE VIEW IF NOT EXISTS app_daily_blog_utm_metrics AS
    SELECT
        substr(created_at, 1, 10) AS event_date,
        page_path,
        COALESCE(NULLIF(json_extract(payload, '$.utm_source'), ''), '(none)') AS utm_source,
        COALESCE(NULLIF(json_extract(payload, '$.utm_medium'), ''), '(none)') AS utm_medium,
        COALESCE(NULLIF(json_extract(payload, '$.utm_campaign'), ''), '(none)') AS utm_campaign,
        COALESCE(NULLIF(json_extract(payload, '$.utm_id'), ''), '(none)') AS utm_id,
        COALESCE(NULLIF(json_extract(payload, '$.utm_term'), ''), '(none)') AS utm_term,
        COALESCE(NULLIF(json_extract(payload, '$.utm_content'), ''), '(none)') AS utm_content,
        COUNT(*) AS page_views,
        COUNT(DISTINCT session_id) AS sessions,
        COUNT(DISTINCT client_id) AS client_visitors,
        COUNT(DISTINCT CASE WHEN user_id IS NOT NULL THEN user_id END) AS signed_in_users,
        MAX(created_at) AS last_event_at
    FROM app_analytics_events
    WHERE event_name = 'page_view'
      AND page_path LIKE '/blog/%'
    GROUP BY
        event_date, page_path, utm_source, utm_medium, utm_campaign,
        utm_id, utm_term, utm_content
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ga_daily_metrics_date
        ON ga_daily_metrics(event_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ga_daily_metrics_source_date
        ON ga_daily_metrics(source, medium, event_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ga_event_metrics_name_date
        ON ga_daily_event_metrics(event_name, event_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ga_page_metrics_date_views
        ON ga_daily_page_metrics(event_date, page_views DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_app_analytics_user_time
        ON app_analytics_events(user_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_app_analytics_event_time
        ON app_analytics_events(event_name, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_app_analytics_client_time
        ON app_analytics_events(client_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_app_analytics_session_time
        ON app_analytics_events(session_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_app_analytics_page_event_time
        ON app_analytics_events(page_path, event_name, created_at)
    """,
)


@dataclass(frozen=True)
class AnalyticsSyncConfig:
    """Configuration for one GA4 BigQuery daily aggregate sync."""

    project_id: str
    dataset: str
    property_id: str
    analytics_db_path: Path = Path("data/analytics.db")
    location: str | None = None
    max_page_rows_per_day: int = 500

    @property
    def table_wildcard(self) -> str:
        project, dataset = normalize_project_dataset(self.project_id, self.dataset)
        return f"`{project}.{dataset}.events_*`"


class QueryClient(Protocol):
    def query(self, query: str, job_config: Any | None = None) -> Any: ...


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_day(value: str) -> dt.date:
    if not _DATE_RE.match(value):
        raise ValueError(f"expected YYYY-MM-DD date, got {value!r}")
    return dt.date.fromisoformat(value)


def suffix(day: dt.date) -> str:
    return day.strftime("%Y%m%d")


def normalize_project_dataset(project_id: str, dataset: str) -> tuple[str, str]:
    """Validate project/dataset identifiers before interpolating SQL names."""
    if "." in dataset:
        project_id, dataset = dataset.split(".", 1)
    if not _IDENTIFIER_RE.match(project_id):
        raise ValueError(f"invalid BigQuery project id: {project_id!r}")
    if not _DATASET_RE.match(dataset):
        raise ValueError(f"invalid BigQuery dataset: {dataset!r}")
    return project_id, dataset


def ensure_analytics_db(db_path: Path) -> None:
    """Create/upgrade analytics.db tables idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        for statement in _ANALYTICS_DDL:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def _query_common_cte(table_wildcard: str) -> str:
    return f"""
    WITH base AS (
      SELECT
        PARSE_DATE('%Y%m%d', event_date) AS event_day,
        COALESCE(NULLIF(traffic_source.source, ''), '(direct)') AS source,
        COALESCE(NULLIF(traffic_source.medium, ''), '(none)') AS medium,
        COALESCE(NULLIF(device.category, ''), '(unknown)') AS device_category,
        COALESCE(NULLIF(geo.country, ''), '(unknown)') AS country,
        user_pseudo_id,
        event_name,
        (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS ga_session_id,
        (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_path') AS page_path_param,
        (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location') AS page_location
      FROM {table_wildcard}
      WHERE REGEXP_CONTAINS(_TABLE_SUFFIX, r'^[0-9]{{8}}$')
        AND _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
    )
    """


def build_daily_metrics_query(config: AnalyticsSyncConfig) -> str:
    return _query_common_cte(config.table_wildcard) + """
    SELECT
      FORMAT_DATE('%F', event_day) AS event_date,
      @property_id AS property_id,
      source,
      medium,
      device_category,
      country,
      COUNT(DISTINCT user_pseudo_id) AS total_users,
      COUNT(DISTINCT IF(
        ga_session_id IS NULL OR user_pseudo_id IS NULL,
        NULL,
        CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING))
      )) AS sessions,
      COUNTIF(event_name = 'page_view') AS page_views,
      COUNT(*) AS event_count
    FROM base
    GROUP BY event_date, property_id, source, medium, device_category, country
    ORDER BY event_date, source, medium, device_category, country
    """


def build_event_metrics_query(config: AnalyticsSyncConfig) -> str:
    return _query_common_cte(config.table_wildcard) + """
    SELECT
      FORMAT_DATE('%F', event_day) AS event_date,
      @property_id AS property_id,
      event_name,
      COUNT(*) AS event_count,
      COUNT(DISTINCT user_pseudo_id) AS total_users
    FROM base
    GROUP BY event_date, property_id, event_name
    ORDER BY event_date, event_count DESC, event_name
    """


def build_page_metrics_query(config: AnalyticsSyncConfig) -> str:
    return _query_common_cte(config.table_wildcard) + """
    , page_base AS (
      SELECT
        FORMAT_DATE('%F', event_day) AS event_date,
        @property_id AS property_id,
        user_pseudo_id,
        COALESCE(
          NULLIF(page_path_param, ''),
          NULLIF(REGEXP_EXTRACT(page_location, r'^https?://[^/]+([^?#]*)'), ''),
          '/'
        ) AS raw_page_path
      FROM base
      WHERE event_name = 'page_view'
    ), page_rollup AS (
      SELECT
        event_date,
        property_id,
        REGEXP_REPLACE(raw_page_path, r'[?#].*$', '') AS page_path,
        COUNT(*) AS page_views,
        COUNT(DISTINCT user_pseudo_id) AS total_users
      FROM page_base
      WHERE raw_page_path IS NOT NULL
      GROUP BY event_date, property_id, page_path
    )
    SELECT event_date, property_id, page_path, page_views, total_users
    FROM page_rollup
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY event_date, property_id
      ORDER BY page_views DESC, page_path
    ) <= @max_page_rows_per_day
    ORDER BY event_date, page_views DESC, page_path
    """


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return getattr(row, key, default)


def _materialize(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [dict(row.items()) if hasattr(row, "items") else dict(row) for row in rows]


def _make_query_job_config(start_date: dt.date, end_date: dt.date, property_id: str, max_page_rows_per_day: int) -> Any:
    from google.cloud import bigquery  # imported lazily so tests need no GCP deps

    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_suffix", "STRING", suffix(start_date)),
            bigquery.ScalarQueryParameter("end_suffix", "STRING", suffix(end_date)),
            bigquery.ScalarQueryParameter("property_id", "STRING", property_id),
            bigquery.ScalarQueryParameter("max_page_rows_per_day", "INT64", max_page_rows_per_day),
        ]
    )


def _open_bigquery_client(project_id: str, location: str | None) -> QueryClient:
    from google.cloud import bigquery  # imported lazily so analytics.db migrations stay lightweight

    kwargs: dict[str, Any] = {"project": project_id}
    if location:
        kwargs["location"] = location
    return bigquery.Client(**kwargs)


def _resolve_dataset_location(config: AnalyticsSyncConfig) -> str | None:
    """Return the configured location, else the dataset's actual location.

    Every sync run before 2026-07 failed with "Dataset ... was not found in
    location US" because GA4 exports land in the property's region while an
    unconfigured client defaults to US. Dataset metadata lookups are
    location-agnostic, so we ask BigQuery where the dataset lives instead of
    requiring GA4_BQ_LOCATION to be set correctly by hand.
    """
    if config.location:
        return config.location
    from google.cloud import bigquery

    project, dataset = normalize_project_dataset(config.project_id, config.dataset)
    probe = bigquery.Client(project=project)
    try:
        return str(probe.get_dataset(f"{project}.{dataset}").location)
    finally:
        probe.close()


def _run_query(client: QueryClient, query: str, job_config: Any | None) -> list[dict[str, Any]]:
    job = client.query(query, job_config=job_config)
    return _materialize(job.result())


def _replace_date_range(conn: sqlite3.Connection, start_date: dt.date, end_date: dt.date) -> None:
    params = (start_date.isoformat(), end_date.isoformat())
    conn.execute("DELETE FROM ga_daily_metrics WHERE event_date BETWEEN ? AND ?", params)
    conn.execute("DELETE FROM ga_daily_event_metrics WHERE event_date BETWEEN ? AND ?", params)
    conn.execute("DELETE FROM ga_daily_page_metrics WHERE event_date BETWEEN ? AND ?", params)


def _insert_daily(conn: sqlite3.Connection, rows: list[dict[str, Any]], synced_at: str) -> None:
    conn.executemany(
        """
        INSERT INTO ga_daily_metrics (
            event_date, property_id, source, medium, device_category, country,
            total_users, sessions, page_views, event_count, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["event_date"],
                r["property_id"],
                r.get("source") or "(unknown)",
                r.get("medium") or "(unknown)",
                r.get("device_category") or "(unknown)",
                r.get("country") or "(unknown)",
                int(r.get("total_users") or 0),
                int(r.get("sessions") or 0),
                int(r.get("page_views") or 0),
                int(r.get("event_count") or 0),
                synced_at,
            )
            for r in rows
        ],
    )


def _insert_events(conn: sqlite3.Connection, rows: list[dict[str, Any]], synced_at: str) -> None:
    conn.executemany(
        """
        INSERT INTO ga_daily_event_metrics (
            event_date, property_id, event_name, event_count, total_users, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["event_date"],
                r["property_id"],
                r.get("event_name") or "(unknown)",
                int(r.get("event_count") or 0),
                int(r.get("total_users") or 0),
                synced_at,
            )
            for r in rows
        ],
    )


def _insert_pages(conn: sqlite3.Connection, rows: list[dict[str, Any]], synced_at: str) -> None:
    conn.executemany(
        """
        INSERT INTO ga_daily_page_metrics (
            event_date, property_id, page_path, page_views, total_users, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["event_date"],
                r["property_id"],
                r.get("page_path") or "/",
                int(r.get("page_views") or 0),
                int(r.get("total_users") or 0),
                synced_at,
            )
            for r in rows
        ],
    )


def sync_ga4_daily_aggregates(
    config: AnalyticsSyncConfig,
    *,
    start_date: dt.date,
    end_date: dt.date,
    client: QueryClient | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch GA4 daily aggregates from BigQuery and persist to analytics.db."""
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    if config.max_page_rows_per_day <= 0:
        raise ValueError("max_page_rows_per_day must be positive")

    normalize_project_dataset(config.project_id, config.dataset)
    ensure_analytics_db(config.analytics_db_path)

    started_at = utc_now_iso()
    bq_client = client or _open_bigquery_client(
        config.project_id, _resolve_dataset_location(config)
    )
    job_config = None if client is not None else _make_query_job_config(
        start_date,
        end_date,
        config.property_id,
        config.max_page_rows_per_day,
    )

    daily_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    page_rows: list[dict[str, Any]] = []
    status = "success"
    error: str | None = None

    try:
        daily_rows = _run_query(bq_client, build_daily_metrics_query(config), job_config)
        event_rows = _run_query(bq_client, build_event_metrics_query(config), job_config)
        page_rows = _run_query(bq_client, build_page_metrics_query(config), job_config)

        if not dry_run:
            synced_at = utc_now_iso()
            conn = sqlite3.connect(str(config.analytics_db_path), check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("BEGIN")
                _replace_date_range(conn, start_date, end_date)
                _insert_daily(conn, daily_rows, synced_at)
                _insert_events(conn, event_rows, synced_at)
                _insert_pages(conn, page_rows, synced_at)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("ga4 BigQuery sync failed")
        raise
    finally:
        if not dry_run:
            finished_at = utc_now_iso()
            conn = sqlite3.connect(str(config.analytics_db_path), check_same_thread=False)
            try:
                conn.execute(
                    """
                    INSERT INTO ga_sync_runs (
                        sync_started_at, sync_finished_at, status, start_date, end_date,
                        project_id, dataset, property_id, rows_daily, rows_events,
                        rows_pages, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        started_at,
                        finished_at,
                        status,
                        start_date.isoformat(),
                        end_date.isoformat(),
                        config.project_id,
                        config.dataset,
                        config.property_id,
                        len(daily_rows),
                        len(event_rows),
                        len(page_rows),
                        error,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    return {
        "status": status,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "rows_daily": len(daily_rows),
        "rows_events": len(event_rows),
        "rows_pages": len(page_rows),
        "dry_run": dry_run,
    }


def default_date_range(days_back: int, today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    if days_back < 1:
        raise ValueError("days_back must be >= 1")
    today = today or dt.datetime.now(dt.UTC).date()
    end_date = today - dt.timedelta(days=1)
    start_date = end_date - dt.timedelta(days=days_back - 1)
    return start_date, end_date


def config_from_env(args: argparse.Namespace) -> AnalyticsSyncConfig:
    project_id = args.project_id or os.getenv("GA4_BQ_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    dataset = args.dataset or os.getenv("GA4_BQ_DATASET")
    property_id = args.property_id or os.getenv("GA4_PROPERTY_ID") or os.getenv("VITE_GA_MEASUREMENT_ID") or "unknown"
    if not project_id:
        raise SystemExit("Missing GA4_BQ_PROJECT_ID or --project-id")
    if not dataset:
        raise SystemExit("Missing GA4_BQ_DATASET or --dataset, e.g. analytics_123456789")
    return AnalyticsSyncConfig(
        project_id=project_id,
        dataset=dataset,
        property_id=property_id,
        analytics_db_path=Path(args.analytics_db),
        location=args.location or os.getenv("GA4_BQ_LOCATION"),
        max_page_rows_per_day=args.max_page_rows_per_day,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync daily GA4 BigQuery aggregates into data/analytics.db",
    )
    parser.add_argument("--project-id", help="BigQuery billing/project id; env GA4_BQ_PROJECT_ID")
    parser.add_argument("--dataset", help="GA4 export dataset, e.g. analytics_123456789; env GA4_BQ_DATASET")
    parser.add_argument("--property-id", help="GA4 property/measurement identifier label; env GA4_PROPERTY_ID")
    parser.add_argument("--location", help="BigQuery location, if required; env GA4_BQ_LOCATION")
    parser.add_argument("--analytics-db", default="data/analytics.db", help="Target SQLite DB path")
    parser.add_argument("--start-date", help="Inclusive YYYY-MM-DD. Defaults to yesterday minus --days-back + 1")
    parser.add_argument("--end-date", help="Inclusive YYYY-MM-DD. Defaults to yesterday")
    parser.add_argument("--days-back", type=int, default=4, help="Days to re-sync ending yesterday; default 4")
    parser.add_argument("--max-page-rows-per-day", type=int, default=500, help="Top page rows to keep per day")
    parser.add_argument("--dry-run", action="store_true", help="Run queries but do not write analytics.db")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    config = config_from_env(args)
    if args.start_date or args.end_date:
        if not (args.start_date and args.end_date):
            raise SystemExit("--start-date and --end-date must be provided together")
        start_date = parse_day(args.start_date)
        end_date = parse_day(args.end_date)
    else:
        start_date, end_date = default_date_range(args.days_back)
    summary = sync_ga4_daily_aggregates(config, start_date=start_date, end_date=end_date, dry_run=args.dry_run)
    print(summary)
    return 0


__all__ = [
    "AnalyticsSyncConfig",
    "build_daily_metrics_query",
    "build_event_metrics_query",
    "build_page_metrics_query",
    "config_from_env",
    "default_date_range",
    "ensure_analytics_db",
    "normalize_project_dataset",
    "sync_ga4_daily_aggregates",
]
