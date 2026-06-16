from __future__ import annotations

import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.analytics import router
from routers.deps import get_optional_user, limiter
from src.analytics.first_party import (
    AppAnalyticsEvent,
    record_app_analytics_event,
    sanitize_page_path,
    sanitize_payload,
)


def test_sanitizers_remove_private_paths_and_sensitive_payload():
    assert sanitize_page_path('/blog/post?token=secret') == '/blog/post'
    assert sanitize_page_path('/%73hare/private-token') == '/private'
    assert sanitize_page_path('/MYpage') == '/private'
    assert sanitize_payload({
        'query_text': 'raw paper title',
        'query_length_bucket': '11-30',
        'result_count_bucket': '1-5',
        'paper_id': 'x',
        'utm_source': 'alice@example.com',
        'utm_campaign': 'Paper Review 2026!',
    }) == {
        'query_length_bucket': '11-30',
        'result_count_bucket': '1-5',
        'utm_campaign': 'Paper_Review_2026',
    }


def test_record_app_analytics_event_keeps_user_id_local(tmp_path):
    db = tmp_path / 'analytics.db'
    row_id = record_app_analytics_event(
        db,
        AppAnalyticsEvent(
            user_id='alice',
            client_id='client_12345678',
            session_id='session_12345678',
            event_name='search',
            page_path='/search?q=secret',
            payload={'query_length_bucket': '11-30', 'query': 'raw'},
        ),
    )
    assert row_id == 1
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute('SELECT * FROM app_analytics_events').fetchone()
        assert row['user_id'] == 'alice'
        assert row['event_name'] == 'search'
        assert row['page_path'] == '/search'
        assert json.loads(row['payload']) == {'query_length_bucket': '11-30'}
        daily = conn.execute('SELECT event_date,user_id,event_name,event_count FROM app_daily_user_event_metrics').fetchone()
        assert daily['user_id'] == 'alice'
        assert daily['event_name'] == 'search'
        assert daily['event_count'] == 1
    finally:
        conn.close()


def test_blog_utm_daily_view_aggregates_page_views(tmp_path):
    db = tmp_path / 'analytics.db'
    for user_id, session_id in [('alice', 'session_12345678'), (None, 'session_87654321')]:
        record_app_analytics_event(
            db,
            AppAnalyticsEvent(
                user_id=user_id,
                client_id=f"client_{session_id.split('_')[1]}",
                session_id=session_id,
                event_name='page_view',
                page_path='/blog/public-slug',
                payload={
                    'utm_source': 'google',
                    'utm_medium': 'organic',
                    'utm_campaign': 'Paper Review',
                    'page_type': 'blog_post',
                },
            ),
        )

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            '''
            SELECT page_path,utm_source,utm_medium,utm_campaign,page_views,sessions,client_visitors,signed_in_users
            FROM app_daily_blog_utm_metrics
            '''
        ).fetchone()
        assert row['page_path'] == '/blog/public-slug'
        assert row['utm_source'] == 'google'
        assert row['utm_medium'] == 'organic'
        assert row['utm_campaign'] == 'Paper_Review'
        assert row['page_views'] == 2
        assert row['sessions'] == 2
        assert row['client_visitors'] == 2
        assert row['signed_in_users'] == 1
    finally:
        conn.close()


def test_analytics_endpoint_uses_server_side_optional_user(tmp_path, monkeypatch):
    monkeypatch.setenv('ANALYTICS_DB_PATH', str(tmp_path / 'analytics.db'))
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router)
    app.dependency_overrides[get_optional_user] = lambda: 'alice'
    client = TestClient(app)

    response = client.post('/api/analytics/events', json={
        'client_id': 'client_12345678',
        'session_id': 'session_12345678',
        'event_name': 'bookmark_save',
        'page_path': '/mypage?private=1',
        'payload': {'source': 'button', 'token': 'secret'},
    })
    assert response.status_code == 202
    assert response.json() == {'accepted': True}

    conn = sqlite3.connect(tmp_path / 'analytics.db')
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute('SELECT user_id,event_name,page_path,payload FROM app_analytics_events').fetchone()
        assert row['user_id'] == 'alice'
        assert row['event_name'] == 'bookmark_save'
        assert row['page_path'] == '/private'
        assert json.loads(row['payload']) == {'source': 'button'}
    finally:
        conn.close()
