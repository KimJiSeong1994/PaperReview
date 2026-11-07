"""Growth contract: real messages, current accounts, and completed observation windows."""
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_admin_assistant import _conv, _turn, _user, _bearer, client as client, conv_db as conv_db
from routers import admin_growth

NOW = datetime(2026, 11, 7, 3, tzinfo=timezone.utc)  # noon KST


@pytest.fixture(autouse=True)
def fixed_window(monkeypatch):
    original = admin_growth._window

    def window(days):
        original(days)  # preserve parameter validation
        today = NOW.astimezone(admin_growth.KST).date()
        dates = [(today - timedelta(days=i)).isoformat() for i in reversed(range(days))]
        start = datetime.fromisoformat(dates[0]).replace(tzinfo=admin_growth.KST)
        return {"days": days, "start": start.isoformat(), "end": NOW.isoformat(),
                "timezone": "Asia/Seoul"}, dates

    monkeypatch.setattr(admin_growth, "_window", window)


def stats(client, auth_headers, days=28):
    response = client.get('/api/admin/growth/stats', params={'days': days}, headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


def account(db, name, days_ago=15, role='user'):
    inc = _user(name, role=role, created_at=(NOW - timedelta(days=days_ago)).isoformat())
    return _conv(db, name, inc)


def message(db, cid, days_ago=0, **kwargs):
    _turn(db, cid, 'user', (NOW - timedelta(days=days_ago)).isoformat(), **kwargs)


def test_auth_and_window(client, auth_headers):
    assert client.get('/api/admin/growth/stats').status_code == 401
    _user('plain')
    assert client.get('/api/admin/growth/stats', headers=_bearer('plain')).status_code == 403
    assert client.get('/api/admin/growth/stats?days=30', headers=auth_headers).status_code == 400


def test_empty_and_empty_conversation_are_not_activity(client, auth_headers, conv_db):
    account(conv_db, 'empty')
    result = stats(client, auth_headers)
    assert result['totals'] == dict(active_users=0, new_users=0, returning_users=0,
                                    repeat_users=0, user_messages=0)
    assert result['activation'] == dict(signups=1, eligible=1, activated=0, pending=0,
                                        pending_activated=0, rate=0.0)
    assert all(row['rate'] is None for row in result['retention'])
    assert len(result['daily']) == 28


def test_actual_use_excludes_admin_old_incarnations_and_future(client, auth_headers, conv_db):
    admin = account(conv_db, 'internal', role='admin')
    current = account(conv_db, 'current')
    old = _conv(conv_db, 'current', 'old-incarnation')
    deleted = _conv(conv_db, 'deleted', 'removed')
    for cid in (admin, old, deleted):
        message(conv_db, cid, 2)
    message(conv_db, current, -1)  # future data never belongs to the window
    message(conv_db, current, 2, content='PRIVATE_MESSAGE')
    message(conv_db, current, 2)
    message(conv_db, current, 1)
    result = stats(client, auth_headers)
    assert result['totals'] == dict(active_users=1, new_users=1, returning_users=0,
                                    repeat_users=1, user_messages=3)
    assert 'PRIVATE_MESSAGE' not in str(result) and current not in str(result)
    assert 'current' not in str(result['daily'])


def test_first_use_comes_from_history_and_days_use_kst(client, auth_headers, conv_db):
    cid = account(conv_db, 'existing', days_ago=60)
    message(conv_db, cid, 40)
    _turn(conv_db, cid, 'user', '2026-11-05T14:59:59Z')
    _turn(conv_db, cid, 'user', '2026-11-05T15:00:00Z')
    result = stats(client, auth_headers, 7)
    assert result['totals']['new_users'] == 0
    assert result['totals']['returning_users'] == result['totals']['repeat_users'] == 1
    daily = {row['date']: row for row in result['daily']}
    assert daily['2026-11-05']['active_users'] == daily['2026-11-06']['active_users'] == 1
    assert result['retention'][0]['eligible'] == 0


def test_activation_uses_first_message_and_only_mature_signups(client, auth_headers, conv_db):
    mature = account(conv_db, 'mature', days_ago=3)
    message(conv_db, mature, 2)  # exactly 24h
    late = account(conv_db, 'late', days_ago=3)
    message(conv_db, late, 1)
    pending = account(conv_db, 'pending', days_ago=0.5)
    message(conv_db, pending)
    account(conv_db, 'empty', days_ago=2)
    result = stats(client, auth_headers)
    assert result['activation'] == dict(signups=4, eligible=3, activated=1, pending=1,
                                        pending_activated=1, rate=0.3333)


def test_exact_day_retention_excludes_unfinished_days(client, auth_headers, conv_db):
    returned = account(conv_db, 'returned')
    for day in (9, 8, 2):  # D0, D1, D7
        message(conv_db, returned, day)
    missed = account(conv_db, 'missed')
    for day in (10, 8):  # D2 is not D1
        message(conv_db, missed, day)
    pending = account(conv_db, 'pending')
    for day in (7, 0):  # D7 today: exclude even if already returned
        message(conv_db, pending, day)
    today = account(conv_db, 'today')
    message(conv_db, today)
    result = stats(client, auth_headers)
    assert result['retention'] == [
        dict(day=1, eligible=3, returned=1, pending=1, rate=0.3333),
        dict(day=7, eligible=2, returned=1, pending=2, rate=0.5),
    ]


def test_invalid_signup_dates_are_reported_not_guessed(client, auth_headers, conv_db):
    for name, date in [('missing', ''), ('naive', '2026-11-01T12:00:00'), ('bad', 'invalid')]:
        inc = _user(name, created_at=date)
        message(conv_db, _conv(conv_db, name, inc))
    result = stats(client, auth_headers)
    assert result['measurement']['unknown_signup_dates'] == 3
    assert result['activation']['rate'] is None
    assert result['totals']['active_users'] == 3
