"""Tests for the admin visits report (/api/admin/analytics/visits).

Hermetic: a temp analytics.db is seeded with raw rows (full control over
``created_at``), nginx logs come from a temp dir via NGINX_ACCESS_LOG_DIR,
and admin auth is replaced through FastAPI dependency_overrides.
"""

from __future__ import annotations

import datetime as dt
import gzip
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from api_server import app
from routers.deps.auth import get_admin_user
from src.analytics.crawler_logs import build_crawler_report
from src.analytics.ga4_bigquery_sync import (
    AnalyticsSyncConfig,
    _resolve_dataset_location,
    ensure_analytics_db,
)
from src.analytics.visits_report import build_visits_report

NOW = dt.datetime(2026, 7, 14, 3, 0, tzinfo=dt.timezone.utc)  # 12:00 KST


def _seed(db: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(db))
    conn.executemany(
        """
        INSERT INTO app_analytics_events
          (user_id, client_id, session_id, event_name, page_path, payload,
           source, created_at, received_at)
        VALUES (?, ?, ?, ?, ?, '{}', 'first_party', ?, ?)
        """,
        [(*r, r[-1]) for r in rows],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def analytics_db(tmp_path: Path) -> Path:
    db = tmp_path / "analytics.db"
    ensure_analytics_db(db)
    # Two visitors today (KST 2026-07-14); c1 was also here before the window.
    _seed(
        db,
        [
            # historical event (outside any window) -> c1 is "returning"
            (None, "c1", "s0", "page_view", "/blog", "2026-01-01T00:00:00Z"),
            # today: c1 session s1 — two page views + a search (engaged)
            (None, "c1", "s1", "page_view", "/blog", "2026-07-14T01:00:00Z"),
            (None, "c1", "s1", "page_view", "/blog/post-a", "2026-07-14T01:05:00Z"),
            ("alice", "c1", "s1", "search", "/", "2026-07-14T01:06:00Z"),
            # today: c2 session s2 — single page view (not engaged)
            (None, "c2", "s2", "page_view", "/blog/post-a", "2026-07-14T02:00:00Z"),
        ],
    )
    return db


def test_build_visits_report_aggregates(analytics_db: Path) -> None:
    report = build_visits_report(analytics_db, days=7, now=NOW)

    totals = report["traffic"]["totals"]
    assert totals["visitors"] == 2
    assert totals["sessions"] == 2
    assert totals["page_views"] == 3
    assert totals["signed_in_users"] == 1
    assert totals["returning_visitors"] == 1
    assert totals["new_visitors"] == 1

    assert report["window"]["timezone"] == "Asia/Seoul"
    daily = {d["date"]: d for d in report["traffic"]["daily"]}
    assert daily["2026-07-14"]["visitors"] == 2
    assert daily["2026-07-14"]["page_views"] == 3

    # 01:00 UTC = 10:00 KST; 02:00 UTC = 11:00 KST
    assert report["timing"]["hour_of_day"][10] == 2
    assert report["timing"]["hour_of_day"][11] == 1
    # 2026-07-14 is a Tuesday -> strftime %w == 2
    assert report["timing"]["day_of_week"][2] == 3
    assert report["timing"]["peak_hour"] == 10

    top = {p["path"]: p for p in report["top_pages"]}
    assert top["/blog/post-a"]["page_views"] == 2
    assert top["/blog/post-a"]["visitors"] == 2

    landing = {p["path"]: p for p in report["landing"]}
    assert landing["/blog"]["sessions"] == 1
    assert landing["/blog"]["engaged_rate"] == 1.0
    assert landing["/blog/post-a"]["engaged_rate"] == 0.0

    assert report["product_events"] == {"search": 1}

    assert report["ga4"]["available"] is False
    assert report["ga4"]["last_run"] is None


def test_ga4_status_reports_last_failed_run(analytics_db: Path) -> None:
    conn = sqlite3.connect(str(analytics_db))
    conn.execute(
        """
        INSERT INTO ga_sync_runs
          (sync_started_at, sync_finished_at, status, start_date, end_date,
           project_id, dataset, property_id, rows_daily, rows_events,
           rows_pages, error)
        VALUES ('t0', 't1', 'failed', 'd0', 'd1', 'p', 'ds', 'prop',
                0, 0, 0, 'NotFound: 404 Not found: Dataset x\nLocation: US')
        """
    )
    conn.commit()
    conn.close()

    report = build_visits_report(analytics_db, days=7, now=NOW)
    assert report["ga4"]["available"] is False
    assert report["ga4"]["last_run"]["status"] == "failed"
    # Multi-line BigQuery errors are trimmed to their first line.
    assert "\n" not in report["ga4"]["last_run"]["error"]
    # A "dataset not found" error is the export-not-yet-created case, surfaced
    # as pending (waiting to connect) rather than a hard failure.
    assert report["ga4"]["state"] == "pending"


def test_ga4_state_pending_when_no_run_yet(analytics_db: Path) -> None:
    report = build_visits_report(analytics_db, days=7, now=NOW)
    assert report["ga4"]["state"] == "never_run"


def test_ga4_state_failed_for_non_dataset_errors(analytics_db: Path) -> None:
    conn = sqlite3.connect(str(analytics_db))
    conn.execute(
        """
        INSERT INTO ga_sync_runs
          (sync_started_at, sync_finished_at, status, start_date, end_date,
           project_id, dataset, property_id, rows_daily, rows_events,
           rows_pages, error)
        VALUES ('t0', 't1', 'failed', 'd0', 'd1', 'p', 'ds', 'prop',
                0, 0, 0, 'Forbidden: 403 Permission bigquery.tables.get denied')
        """
    )
    conn.commit()
    conn.close()
    report = build_visits_report(analytics_db, days=7, now=NOW)
    assert report["ga4"]["state"] == "failed"


LOG_TEMPLATE = (
    '1.2.3.4 - - [{time}] "GET {path} HTTP/1.1" {status} 123 "{referer}" "{ua}"\n'
)


@pytest.fixture
def nginx_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log_dir = tmp_path / "nginx"
    log_dir.mkdir()
    lines = [
        LOG_TEMPLATE.format(
            time="13/Jul/2026:10:00:00 +0000",
            path="/blog/post-a",
            status=200,
            referer="-",
            ua="Mozilla/5.0 (compatible; GPTBot/1.0)",
        ),
        LOG_TEMPLATE.format(
            time="13/Jul/2026:10:01:00 +0000",
            path="/blog/post-a?utm=x",
            status=200,
            referer="-",
            ua="ChatGPT-User/1.0",
        ),
        LOG_TEMPLATE.format(
            time="13/Jul/2026:10:02:00 +0000",
            path="/blog",
            status=404,
            referer="-",
            ua="Mozilla/5.0 (compatible; Yeti/1.1; +https://naver.me/spd)",
        ),
        # human click-through from ChatGPT (AI referral, browser UA)
        LOG_TEMPLATE.format(
            time="13/Jul/2026:10:03:00 +0000",
            path="/blog/post-a",
            status=200,
            referer="https://chatgpt.com/",
            ua="Mozilla/5.0 (Macintosh)",
        ),
        # too old — outside every window used in tests
        LOG_TEMPLATE.format(
            time="01/Jan/2026:00:00:00 +0000",
            path="/",
            status=200,
            referer="-",
            ua="GPTBot",
        ),
    ]
    (log_dir / "access.log").write_text("".join(lines[:2]))
    (log_dir / "access.log.1").write_text(lines[2])
    with gzip.open(log_dir / "access.log.2.gz", "wt") as fh:
        fh.write("".join(lines[3:]))
    monkeypatch.setenv("NGINX_ACCESS_LOG_DIR", str(log_dir))
    return log_dir


def test_crawler_report_classifies_bots_and_referrals(nginx_logs: Path) -> None:
    report = build_crawler_report(days=7, now=NOW)
    assert report["available"] is True
    bots = {b["bot"]: b for b in report["bots"]}
    assert bots["GPTBot"]["hits"] == 1  # the January hit is outside the window
    assert bots["ChatGPT-User"]["hits"] == 1
    assert bots["Yeti(Naver)"]["errors"] == 1
    assert report["citation_clicks"] == 1
    assert report["citation_paths"] == [{"path": "/blog/post-a", "hits": 1}]
    assert report["ai_referral_hits"] == 1
    assert report["ai_referral_sources"] == [{"source": "chatgpt.com", "hits": 1}]


def test_crawler_report_degrades_without_log_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NGINX_ACCESS_LOG_DIR", str(tmp_path / "definitely-missing"))
    report = build_crawler_report(days=7, now=NOW)
    # Missing dir yields no matching files -> empty but available report.
    assert report["available"] is True
    assert report["bots"] == []


@pytest.fixture
def client(
    analytics_db: Path, nginx_logs: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(analytics_db))
    app.dependency_overrides[get_admin_user] = lambda: "test-admin"
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_admin_user, None)


def test_visits_endpoint_returns_report(client: TestClient) -> None:
    resp = client.get("/api/admin/analytics/visits?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["traffic"]["totals"]["visitors"] == 2
    assert body["ai"]["available"] is True
    assert body["window"]["days"] == 7


def test_visits_endpoint_rejects_odd_windows(client: TestClient) -> None:
    assert client.get("/api/admin/analytics/visits?days=13").status_code == 400


def test_visits_endpoint_requires_admin(
    analytics_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(analytics_db))
    resp = TestClient(app).get("/api/admin/analytics/visits")
    assert resp.status_code == 401


def _config(tmp_path: Path, location: str | None = None) -> AnalyticsSyncConfig:
    return AnalyticsSyncConfig(
        project_id="p",
        dataset="ds",
        property_id="prop",
        analytics_db_path=tmp_path / "a.db",
        location=location,
    )


def test_resolve_dataset_location_probe_wins_over_configured(tmp_path: Path) -> None:
    """A wrongly-configured GA4_BQ_LOCATION must not override reality."""
    config = _config(tmp_path, location="US")
    assert (
        _resolve_dataset_location(config, probe=lambda p, d: "asia-northeast3")
        == "asia-northeast3"
    )


def test_resolve_dataset_location_falls_back_to_configured_on_probe_failure(
    tmp_path: Path,
) -> None:
    def failing_probe(project: str, dataset: str) -> str:
        raise RuntimeError("no datasets.get permission")

    config = _config(tmp_path, location="asia-northeast3")
    assert _resolve_dataset_location(config, probe=failing_probe) == "asia-northeast3"


def test_resolve_dataset_location_reraises_without_fallback(tmp_path: Path) -> None:
    def failing_probe(project: str, dataset: str) -> str:
        raise RuntimeError("Dataset p:ds does not exist")

    with pytest.raises(RuntimeError, match="does not exist"):
        _resolve_dataset_location(_config(tmp_path), probe=failing_probe)
