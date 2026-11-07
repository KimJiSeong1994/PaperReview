"""Small, bounded browser-traffic overview for the admin's first screen."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from src.analytics.visits_report import KST, _connect, _window_start_utc


def build_dashboard(db_path: Path, *, days: int, now: dt.datetime | None = None) -> dict[str, Any]:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    start = dt.datetime.fromisoformat(_window_start_utc(days, now).replace('Z', '+00:00'))
    previous_start, previous_end = start - dt.timedelta(days=days), now - dt.timedelta(days=days)
    dates = [(start.astimezone(KST).date() + dt.timedelta(days=i)).isoformat() for i in range(days)]
    conn = _connect(db_path)
    try:
        conn.execute('BEGIN')  # one snapshot for totals, history, and ranks
        history = conn.execute(
            'SELECT MIN(created_at) AS first_at, MAX(created_at) AS last_at FROM app_analytics_events WHERE julianday(created_at) <= julianday(?)',
            (now.isoformat(),),
        ).fetchone()

        def totals(begin: dt.datetime, end: dt.datetime) -> dict:
            return dict(conn.execute('''
                WITH firsts AS (
                    SELECT client_id, MIN(julianday(created_at)) AS first_at
                      FROM app_analytics_events GROUP BY client_id
                )
                SELECT COUNT(DISTINCT e.client_id) AS visitors,
                       COALESCE(SUM(e.event_name = 'page_view'), 0) AS page_views,
                       COUNT(DISTINCT CASE WHEN firsts.first_at < julianday(:start)
                           THEN e.client_id END) AS returning_visitors
                  FROM app_analytics_events e JOIN firsts USING (client_id)
                 WHERE julianday(e.created_at) BETWEEN julianday(:start) AND julianday(:end)
            ''', {'start': begin.isoformat(), 'end': end.isoformat()}).fetchone())

        params = {'start': start.isoformat(), 'end': now.isoformat()}
        daily = {row['date']: row['visitors'] for row in conn.execute('''
            SELECT date(created_at, '+9 hours') AS date, COUNT(DISTINCT client_id) AS visitors
              FROM app_analytics_events
             WHERE julianday(created_at) BETWEEN julianday(:start) AND julianday(:end)
             GROUP BY 1
        ''', params)}
        pages = [dict(row) for row in conn.execute('''
            SELECT page_path AS path, COUNT(*) AS views
              FROM app_analytics_events
             WHERE julianday(created_at) BETWEEN julianday(:start) AND julianday(:end)
               AND event_name = 'page_view' AND page_path != '/private'
             GROUP BY 1 ORDER BY views DESC, path LIMIT 5
        ''', params)]
        channels = [dict(row) for row in conn.execute('''
            SELECT source, medium, SUM(sessions) AS sessions
              FROM ga_daily_metrics WHERE event_date BETWEEN ? AND ?
             GROUP BY 1, 2 ORDER BY sessions DESC, source, medium LIMIT 5
        ''', (dates[0], dates[-1]))]
        sync = conn.execute('SELECT status, sync_finished_at FROM ga_sync_runs ORDER BY id DESC LIMIT 1').fetchone()
        # Earliest retained event establishes history coverage, not proof of continuous collection.
        first = dt.datetime.fromisoformat(history['first_at'].replace('Z', '+00:00')) if history['first_at'] else None
        if first and first.tzinfo is None:
            first = first.replace(tzinfo=dt.timezone.utc)
        return {
            'window': {'days': days, 'start': start.isoformat(), 'end': now.isoformat()},
            'totals': totals(start, now),
            'comparison': {
                'start': previous_start.isoformat(), 'end': previous_end.isoformat(),
                'available': bool(first and first <= previous_start),
                'totals': totals(previous_start, previous_end),
            },
            'daily': [{'date': date, 'visitors': daily.get(date, 0)
                       if first and date >= first.astimezone(KST).date().isoformat() else None}
                      for date in dates],
            'top_pages': pages,
            'acquisition': {'channels': channels, 'state': 'failed' if sync and sync['status'] != 'success' else 'connected' if sync else 'not_connected',
                            'synced_at': sync['sync_finished_at'] if sync else None},
            'measurement': {'first_at': history['first_at'], 'last_at': history['last_at'],
                            'population': 'consented_browser_events'},
        }
    finally:
        conn.close()
