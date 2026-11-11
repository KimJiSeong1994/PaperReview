"""Google sign-in HTTP boundaries; no live credentials or provider calls."""
import hashlib
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from google.auth import exceptions as google_errors

from routers import auth
from routers.deps.storage import _get_user_db

ORIGIN = {'Origin': 'https://jiphyeonjeon.kr'}
CLIENT_ID = '123-test.apps.googleusercontent.com'


@pytest.fixture(autouse=True)
def google_config(monkeypatch, app):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', CLIENT_ID)
    monkeypatch.setenv('CORS_ORIGINS', 'https://jiphyeonjeon.kr')
    monkeypatch.setattr(app.state.limiter, 'enabled', False)


async def challenge(client, monkeypatch, credentials=None, subject='google-subject'):
    response = await client.post('/api/auth/google/challenge', json=credentials or {}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    nonce = response.json()['nonce']
    monkeypatch.setattr(auth, '_verify_google_credential', lambda token, audience: {
        'sub': subject, 'nonce': nonce, 'email': 'person@gmail.com', 'email_verified': True, 'name': 'Person',
    })
    return response


async def exchange(client, **kwargs):
    return await client.post('/api/auth/google', json={'credential': 'signed-google-token'}, headers=ORIGIN, **kwargs)


def legacy_account(name='existing', role='user'):
    return _get_user_db().create_account(name, {
        'password_hash': auth._hash_password('existing-password'), 'role': role,
        'created_at': datetime.now(timezone.utc).isoformat(),
    })


async def test_config_and_legacy_cutover(client, monkeypatch):
    config = await client.get('/api/auth/config')
    assert config.json() == {'google_enabled': True, 'google_client_id': CLIENT_ID,
                             'password_login_enabled': False, 'registration_enabled': False}
    assert config.headers['cache-control'] == 'no-store'
    for path in ('login', 'register'):
        r = await client.post('/api/auth/' + path, json={'username': 'someone', 'password': 'secret'})
        assert r.status_code == 403 and r.json()['detail'] == 'google_sign_in_required'
    monkeypatch.delenv('GOOGLE_CLIENT_ID')
    config = await client.get('/api/auth/config')
    assert config.json()['password_login_enabled'] is True
    assert config.json()['google_enabled'] is False
    r = await client.post('/api/auth/google/challenge', json={}, headers=ORIGIN)
    assert r.status_code == 503


async def test_browser_bound_login_and_replay(client, monkeypatch):
    ch = await challenge(client, monkeypatch)
    cookie = ch.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie and 'path=/api/auth/google' in cookie
    assert ch.json()['client_id'] == CLIENT_ID
    cookie_value = client.cookies.get(auth._GOOGLE_NONCE_COOKIE)
    response = await exchange(client)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['role'] == 'user' and data['is_new_user'] is True
    assert data['username'].startswith('google_')
    assert _get_user_db().get(data['username'])['password_hash'] is None
    verified = await client.get('/api/auth/verify', headers={'Authorization': 'Bearer ' + data['access_token']})
    assert verified.status_code == 200
    # Even restoring the browser cookie cannot replay a consumed signed credential.
    client.cookies.set(auth._GOOGLE_NONCE_COOKIE, cookie_value, path='/api/auth/google')
    replay = await exchange(client)
    assert replay.status_code == 401


async def test_existing_google_identity_signs_into_same_account(client, monkeypatch):
    await challenge(client, monkeypatch)
    first = (await exchange(client)).json()
    await challenge(client, monkeypatch)
    second = (await exchange(client)).json()
    assert second['username'] == first['username'] and second['is_new_user'] is False


async def test_link_preserves_admin_incarnation_and_requires_old_password(client, monkeypatch):
    before = legacy_account(role='admin')
    bad = await client.post('/api/auth/google/challenge', json={'username': 'existing', 'password': 'wrong'}, headers=ORIGIN)
    assert bad.status_code == 401
    await challenge(client, monkeypatch, {'username': 'existing', 'password': 'existing-password'})
    data = (await exchange(client)).json()
    assert data['username'] == 'existing' and data['role'] == 'admin' and not data['is_new_user']
    assert _get_user_db().get('existing')['account_incarnation'] == before['account_incarnation']


async def test_cross_origin_and_missing_browser_binding_rejected(client, monkeypatch):
    for headers in ({}, {'Origin': 'https://evil.example'}, {'Origin': 'null'}):
        assert (await client.post('/api/auth/google/challenge', json={}, headers=headers)).status_code == 403
    await challenge(client, monkeypatch)
    assert (await client.post('/api/auth/google', json={'credential': 'token'}, headers={'Origin': 'https://evil.example'})).status_code == 403
    client.cookies.clear()
    assert (await exchange(client)).status_code == 401


async def test_mismatched_nonce_and_expiry(client, monkeypatch):
    ch = await challenge(client, monkeypatch)
    monkeypatch.setattr(auth, '_verify_google_credential', lambda *_: {'sub': 's', 'nonce': 'wrong'})
    assert (await exchange(client)).status_code == 401
    nonce = ch.json()['nonce']
    monkeypatch.setattr(auth, '_verify_google_credential', lambda *_: {'sub': 's', 'nonce': nonce})
    db = _get_user_db()
    with db.transaction() as tx:
        tx.conn.execute('UPDATE google_auth_challenges SET expires_at=0 WHERE nonce_hash=?', (hashlib.sha256(nonce.encode()).hexdigest(),))
    assert (await exchange(client)).status_code == 401


async def test_link_target_deleted_and_recreated_cannot_be_taken_over(client, monkeypatch):
    old = legacy_account()
    await challenge(client, monkeypatch, {'username': 'existing', 'password': 'existing-password'})
    db = _get_user_db()
    db.begin_delete('existing', old['account_incarnation'])
    db.finish_delete('existing', old['account_incarnation'], cleanup_succeeded=True)
    replacement = legacy_account()
    response = await exchange(client)
    assert response.status_code in (401, 409)
    assert db.get('existing')['account_incarnation'] == replacement['account_incarnation']


async def test_link_conflict_does_not_merge_accounts(client, monkeypatch):
    await challenge(client, monkeypatch)
    google_account = (await exchange(client)).json()['username']
    old = legacy_account()
    await challenge(client, monkeypatch, {'username': 'existing', 'password': 'existing-password'})
    response = await exchange(client)
    assert response.status_code == 409
    assert response.json()['detail'] == 'google_identity_conflict'
    assert _get_user_db().get('existing')['account_incarnation'] == old['account_incarnation']
    assert _get_user_db().get(google_account) is not None


async def test_partial_link_credentials_and_google_password_hash_are_safe(client, monkeypatch):
    for payload in ({'username': 'existing'}, {'password': 'password'}):
        assert (await client.post('/api/auth/google/challenge', json=payload, headers=ORIGIN)).status_code == 422
    await challenge(client, monkeypatch)
    username = (await exchange(client)).json()['username']
    r = await client.post('/api/auth/google/challenge', json={'username': username, 'password': 'anything'}, headers=ORIGIN)
    assert r.status_code == 401


def test_provider_verification_uses_configured_audience_and_checks_claims(monkeypatch):
    calls = []
    good = {'iss': 'https://accounts.google.com', 'sub': 'subject', 'email_verified': True}
    def verify(token, request, audience):
        calls.append((token, audience))
        return good
    monkeypatch.setattr(auth.google_id_token, 'verify_oauth2_token', verify)
    assert auth._verify_google_credential('signed', CLIENT_ID)['sub'] == 'subject'
    assert calls == [('signed', CLIENT_ID)]
    for invalid in ({**good, 'sub': ''}, {**good, 'iss': 'https://evil.example'}, {**good, 'email_verified': False}):
        monkeypatch.setattr(auth.google_id_token, 'verify_oauth2_token', lambda *a, **kw: invalid)
        with pytest.raises(HTTPException) as err:
            auth._verify_google_credential('signed', CLIENT_ID)
        assert err.value.status_code == 401
    with pytest.raises(HTTPException):
        auth._verify_google_credential('signed', '')


def test_invalid_token_and_provider_outage_have_distinct_errors(monkeypatch):
    for error, status in ((ValueError('bad audience or signature'), 401), (google_errors.TransportError('provider down'), 503)):
        def fail(*a, **kw):
            raise error
        monkeypatch.setattr(auth.google_id_token, 'verify_oauth2_token', fail)
        with pytest.raises(HTTPException) as caught:
            auth._verify_google_credential('signed', CLIENT_ID)
        assert caught.value.status_code == status


async def test_production_challenge_cookie_is_secure(client, monkeypatch):
    monkeypatch.setenv('ENVIRONMENT', 'production')
    r = await client.post('/api/auth/google/challenge', json={}, headers=ORIGIN)
    assert r.status_code == 200
    assert 'secure' in r.headers['set-cookie'].lower()
    assert r.headers['cache-control'] == 'no-store'


async def test_token_verifier_failure_never_creates_google_identity(client, monkeypatch):
    await challenge(client, monkeypatch)
    before = _get_user_db().count()
    def invalid(*args):
        raise HTTPException(status_code=401, detail='invalid_google_credential')
    monkeypatch.setattr(auth, '_verify_google_credential', invalid)
    assert (await exchange(client)).status_code == 401
    assert _get_user_db().count() == before


def test_optional_production_google_configuration_preserves_unconfigured_servers():
    from pathlib import Path
    workflow = Path('.github/workflows/ci.yml').read_text()
    start = workflow.index('      - name: Configure Google sign-in when a client ID is supplied')
    end = workflow.index('      - name: Update JEV server API key', start)
    step = workflow[start:end]
    assert "if: steps.stale.outputs.skip != 'true'" in step
    assert "GOOGLE_CLIENT_ID: ${{ vars.GOOGLE_CLIENT_ID || '' }}" in step
    assert 'if [ -n "$GOOGLE_CLIENT_ID" ]; then' in step
    assert 'sys.stdin.read()' in step and 're.fullmatch' in step
    assert 'env_file.is_file()' in step
    assert 'set_key' in step and 'GOOGLE_CLIENT_ID' in step
    assert workflow.index('Install exact backend revision and dependencies') < start
    assert end < workflow.index('Restart the managed service and verify readiness')
