import sqlite3

from src.analytics.dashboard import build_dashboard
from src.analytics.ga4_bigquery_sync import ensure_analytics_db
from tests.test_admin_visits_report import _seed, analytics_db as analytics_db, NOW
from tests.test_admin_assistant import client as client, _user, _bearer


def test_equal_elapsed_comparison_and_future_exclusion(analytics_db):
    _seed(analytics_db, [
        (None, 'previous', 'p', 'page_view', '/', '2026-07-07T02:00:00Z'),
        (None, 'too_late', 'x', 'page_view', '/', '2026-07-07T04:00:00Z'),
        (None, 'future', 'f', 'page_view', '/', '2026-07-14T04:00:00Z'),
    ])
    result = build_dashboard(analytics_db, days=7, now=NOW)
    assert result['totals'] == dict(visitors=2, page_views=3, returning_visitors=1)
    assert result['comparison']['totals']['visitors'] == 1
    assert result['comparison']['available'] is True
    assert result['comparison']['end'] == '2026-07-07T03:00:00+00:00'
    assert result['daily'][0]['date'] == '2026-07-08'
    assert result['daily'][-1] == {'date': '2026-07-14', 'visitors': 2}
    assert result['top_pages'][0] == {'path': '/blog/post-a', 'views': 2}


def test_empty_history_and_incomplete_comparison(tmp_path):
    db = tmp_path / 'analytics.db'
    ensure_analytics_db(db)
    report = build_dashboard(db, days=28, now=NOW)
    assert report['comparison']['available'] is False
    assert report['daily'][0]['visitors'] is None
    assert report['measurement']['first_at'] is None
    assert report['acquisition']['state'] == 'not_connected'
    assert len(report['daily']) == 28
    _seed(db, [(None, 'new', 'n', 'page_view', '/', NOW.isoformat())])
    report = build_dashboard(db, days=28, now=NOW)
    assert report['totals']['visitors'] == 1
    assert report['comparison']['available'] is False
    assert report['daily'][0]['visitors'] is None
    assert report['daily'][-1]['visitors'] == 1


def test_acquisition_uses_kst_dates_and_marks_failed_sync(analytics_db):
    with sqlite3.connect(analytics_db) as conn:
        conn.executemany('''INSERT INTO ga_daily_metrics
            (event_date, property_id, source, medium, sessions, synced_at)
            VALUES (?, 'p', 'google', 'organic', ?, '2026-07-14T00:00:00Z')''',
            [('2026-07-07', 100), ('2026-07-08', 3), ('2026-07-14', 5), ('2026-07-15', 200)])
        conn.execute('''INSERT INTO ga_sync_runs
            (sync_started_at, sync_finished_at, status, start_date, end_date, project_id, dataset, property_id)
            VALUES ('2026-07-14T00:00:00Z', '2026-07-14T00:01:00Z', 'failed', '2026-07-08', '2026-07-14', 'p', 'd', 'p')''')
    result = build_dashboard(analytics_db, days=7, now=NOW)
    assert result['acquisition']['channels'] == [{'source': 'google', 'medium': 'organic', 'sessions': 8}]
    assert result['acquisition']['state'] == 'failed'


def test_kst_boundary_private_pages_and_zero_baseline(tmp_path):
    db = tmp_path / 'analytics.db'
    ensure_analytics_db(db)
    _seed(db, [
        (None, 'old', 'o', 'page_view', '/', '2026-01-01T00:00:00Z'),
        (None, 'a', 'a', 'page_view', '/private', '2026-07-07T15:00:00Z'),
        (None, 'b', 'b', 'page_view', '/', '2026-07-07T14:59:59Z'),
    ])
    report = build_dashboard(db, days=7, now=NOW)
    assert report['comparison']['available'] is True
    assert report['comparison']['totals']['visitors'] == 0
    assert report['totals']['visitors'] == 1
    assert report['top_pages'] == []
    assert report['daily'][0]['visitors'] == 1


def test_overview_endpoint_and_window(client, analytics_db, monkeypatch, auth_headers):
    monkeypatch.setenv('ANALYTICS_DB_PATH', str(analytics_db))
    assert client.get('/api/admin/analytics/overview?days=7', headers=auth_headers).status_code == 200
    assert client.get('/api/admin/analytics/overview?days=30', headers=auth_headers).status_code == 400
    _user('plain')
    assert client.get('/api/admin/analytics/overview', headers=_bearer('plain')).status_code == 403


def test_missing_store_is_unavailable(client, auth_headers):
    assert client.get('/api/admin/analytics/overview', headers=auth_headers).status_code == 503


def test_overview_auth():
    from fastapi.testclient import TestClient
    from api_server import app
    with TestClient(app) as c:
        assert c.get('/api/admin/analytics/overview').status_code == 401
