from __future__ import annotations

import datetime as dt
import sqlite3

from src.analytics.ga4_bigquery_sync import (
    AnalyticsSyncConfig,
    build_daily_metrics_query,
    build_event_metrics_query,
    build_page_metrics_query,
    default_date_range,
    ensure_analytics_db,
    normalize_project_dataset,
    sync_ga4_daily_aggregates,
)


class _FakeJob:
    def __init__(self, rows):
        self._rows = rows

    def result(self):
        return self._rows


class _FakeClient:
    def __init__(self):
        self.queries = []

    def query(self, query, job_config=None):
        self.queries.append(query)
        if "ga_daily_metrics" in query:
            raise AssertionError("unexpected table name in BigQuery SQL")
        if "GROUP BY event_date, property_id, source" in query:
            return _FakeJob([
                {
                    "event_date": "2026-06-15",
                    "property_id": "G-TEST",
                    "source": "google",
                    "medium": "organic",
                    "device_category": "desktop",
                    "country": "South Korea",
                    "total_users": 3,
                    "sessions": 4,
                    "page_views": 7,
                    "event_count": 12,
                }
            ])
        if "event_name" in query and "GROUP BY event_date, property_id, event_name" in query:
            return _FakeJob([
                {
                    "event_date": "2026-06-15",
                    "property_id": "G-TEST",
                    "event_name": "page_view",
                    "event_count": 7,
                    "total_users": 3,
                }
            ])
        if "page_rollup" in query:
            return _FakeJob([
                {
                    "event_date": "2026-06-15",
                    "property_id": "G-TEST",
                    "page_path": "/blog",
                    "page_views": 5,
                    "total_users": 2,
                }
            ])
        raise AssertionError(query)


def test_ensure_analytics_db_creates_separate_ga_tables(tmp_path):
    db = tmp_path / "analytics.db"
    ensure_analytics_db(db)
    conn = sqlite3.connect(db)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "ga_daily_metrics",
            "ga_daily_event_metrics",
            "ga_daily_page_metrics",
            "ga_sync_runs",
        }.issubset(tables)
        assert "user_events" not in tables
    finally:
        conn.close()


def test_bigquery_queries_use_ga4_daily_export_without_identity_projection(tmp_path):
    config = AnalyticsSyncConfig(
        project_id="paper-review-prod",
        dataset="analytics_123456789",
        property_id="G-TEST",
        analytics_db_path=tmp_path / "analytics.db",
    )
    queries = [
        build_daily_metrics_query(config),
        build_event_metrics_query(config),
        build_page_metrics_query(config),
    ]
    for query in queries:
        assert "`paper-review-prod.analytics_123456789.events_*`" in query
        assert "_TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix" in query
        assert "REGEXP_CONTAINS(_TABLE_SUFFIX" in query
        assert "page_title" not in query
        assert "user_id" not in query


def test_sync_replaces_date_range_and_records_run(tmp_path):
    db = tmp_path / "analytics.db"
    config = AnalyticsSyncConfig(
        project_id="paper-review-prod",
        dataset="analytics_123456789",
        property_id="G-TEST",
        analytics_db_path=db,
    )
    client = _FakeClient()
    summary = sync_ga4_daily_aggregates(
        config,
        start_date=dt.date(2026, 6, 15),
        end_date=dt.date(2026, 6, 15),
        client=client,
    )
    assert summary == {
        "status": "success",
        "start_date": "2026-06-15",
        "end_date": "2026-06-15",
        "rows_daily": 1,
        "rows_events": 1,
        "rows_pages": 1,
        "dry_run": False,
    }

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT page_views FROM ga_daily_metrics").fetchone()[0] == 7
        assert conn.execute("SELECT event_count FROM ga_daily_event_metrics").fetchone()[0] == 7
        assert conn.execute("SELECT page_path FROM ga_daily_page_metrics").fetchone()[0] == "/blog"
        assert conn.execute("SELECT status FROM ga_sync_runs").fetchone()[0] == "success"
    finally:
        conn.close()


def test_default_date_range_resyncs_yesterday_and_three_prior_days():
    start, end = default_date_range(4, today=dt.date(2026, 6, 16))
    assert start == dt.date(2026, 6, 12)
    assert end == dt.date(2026, 6, 15)


def test_dataset_validation_accepts_full_dataset_and_rejects_sql_injection():
    assert normalize_project_dataset("fallback", "my-project.analytics_123") == (
        "my-project",
        "analytics_123",
    )
    try:
        normalize_project_dataset("fallback", "analytics_123;DROP TABLE users")
    except ValueError:
        pass
    else:
        raise AssertionError("expected invalid dataset to be rejected")
