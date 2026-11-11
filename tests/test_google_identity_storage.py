"""Google identities follow the same account lifecycle as local credentials."""

import hashlib
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.storage.user_db import AccountLifecycleError, UserDB


@pytest.fixture
def db(tmp_path):
    return UserDB(tmp_path / "users.db")


def challenge(db, label, *, target=None, now=None):
    digest = hashlib.sha256(label.encode()).hexdigest()
    options = {}
    if target:
        options = {"target_username": target[0], "target_incarnation": target[1]}
    db.create_google_challenge(digest, expires_at=(now or time.time()) + 300, **options)
    return digest


def login(db, label, subject="google-subject", *, target=None, now=None, profile=None):
    now = now or time.time()
    nonce = challenge(db, label, target=target, now=now)
    return db.complete_google_login(nonce, subject, now=now, profile=profile)


def test_new_google_identity_is_user_and_same_subject_reuses_it(db):
    created = login(db, "first", profile={
        "display_name": "Researcher", "email": "reader@example.com",
        "role": "admin", "password_hash": "forged", "account_incarnation": "forged",
    })
    assert created["is_new_user"] is True
    assert created["username"].startswith("google_")
    user = created["user"]
    assert user["role"] == "user" and user["password_hash"] is None
    assert user["account_incarnation"] != "forged"
    assert user["display_name"] == "Researcher" and user["email"] == "reader@example.com"
    assert "google-subject" not in str(db.get_all())
    again = login(UserDB(db._db_path), "second")
    assert again["username"] == created["username"]
    assert again["user"]["account_incarnation"] == user["account_incarnation"]
    assert again["is_new_user"] is False and db.count() == 1


def test_matching_email_does_not_automatically_link_existing_account(db):
    existing = db.create_account("reader", {"role": "admin", "email": "reader@example.com"})
    result = login(db, "same-email", profile={"email": "reader@example.com"})
    assert result["username"] != "reader"
    assert result["user"]["role"] == "user"
    assert db.get("reader") == existing


def test_linking_preserves_admin_credentials_incarnation_and_metadata(db):
    existing = db.create_account("owner", {
        "role": "admin", "password_hash": "existing-hash", "created_at": "original-date",
        "display_name": "Original", "theme": "dark",
    })
    result = login(db, "link", target=("owner", existing["account_incarnation"]),
                   profile={"display_name": "Google Name", "email": "new@example.com"})
    assert result == {"username": "owner", "user": existing, "is_new_user": False}
    assert login(db, "later")["user"] == existing


def test_challenge_is_single_use_and_expired_nonce_is_consumed(db):
    now = time.time()
    nonce = challenge(db, "one-use", now=now)
    db.complete_google_login(nonce, "one", now=now)
    with pytest.raises(AccountLifecycleError, match="google_challenge_invalid"):
        db.complete_google_login(nonce, "one", now=now)
    expired = challenge(db, "expired", now=now)
    with pytest.raises(AccountLifecycleError, match="google_challenge_invalid"):
        db.complete_google_login(expired, "two", now=now + 300)
    with pytest.raises(AccountLifecycleError, match="google_challenge_invalid"):
        db.complete_google_login(expired, "two", now=now)
    assert db.count() == 1


def test_challenge_requires_complete_active_target(db):
    user = db.create_account("owner", {})
    with pytest.raises(AccountLifecycleError, match="invalid_principal"):
        db.create_google_challenge("a" * 64, expires_at=time.time() + 300, target_username="owner")
    with pytest.raises(AccountLifecycleError, match="account_inactive_or_mismatch"):
        challenge(db, "wrong-generation", target=("owner", "stale"))
    db.begin_delete("owner", user["account_incarnation"])
    with pytest.raises(AccountLifecycleError, match="account_inactive_or_mismatch"):
        challenge(db, "deleting", target=("owner", user["account_incarnation"]))


def test_subject_already_linked_to_another_account_rejects_and_consumes(db):
    one = db.create_account("one", {})
    two = db.create_account("two", {})
    login(db, "link-one", target=("one", one["account_incarnation"]))
    nonce = challenge(db, "link-two", target=("two", two["account_incarnation"]))
    with pytest.raises(AccountLifecycleError, match="google_identity_conflict"):
        db.complete_google_login(nonce, "google-subject", now=time.time())
    with pytest.raises(AccountLifecycleError, match="google_challenge_invalid"):
        db.complete_google_login(nonce, "different-subject", now=time.time())
    assert db.get("two") == two
    assert login(db, "still-one")["username"] == "one"


def test_target_cannot_be_relinked_to_a_different_google_subject(db):
    owner = db.create_account("owner", {})
    target = ("owner", owner["account_incarnation"])
    login(db, "first", "first-subject", target=target)
    with pytest.raises(AccountLifecycleError, match="google_account_already_linked"):
        login(db, "second", "second-subject", target=target)
    assert login(db, "same-link", "first-subject", target=target)["username"] == "owner"
    assert db.count() == 1


def test_old_link_challenge_cannot_attach_to_a_recreated_username(db):
    original = db.create_account("owner", {"role": "admin"})
    nonce = challenge(db, "before-delete", target=("owner", original["account_incarnation"]))
    db.begin_delete("owner", original["account_incarnation"])
    db.finish_delete("owner", original["account_incarnation"], cleanup_succeeded=True)
    replacement = db.create_account("owner", {"role": "user"})
    with pytest.raises(AccountLifecycleError, match="account_inactive_or_mismatch"):
        db.complete_google_login(nonce, "unlinked-subject", now=time.time())
    assert db.get("owner") == replacement
    assert login(db, "new-login", "unlinked-subject")["username"] != "owner"


@pytest.mark.parametrize("cleanup_pending", [False, True])
def test_deletion_reserves_identity_until_cleanup_completes(db, cleanup_pending):
    original = login(db, "first")
    name, incarnation = original["username"], original["user"]["account_incarnation"]
    db.begin_delete(name, incarnation)
    if cleanup_pending:
        db.finish_delete(name, incarnation, cleanup_succeeded=False)
    with pytest.raises(AccountLifecycleError, match="account_inactive_or_mismatch"):
        login(db, "during-delete")
    db.finish_delete(name, incarnation, cleanup_succeeded=True)
    replacement = login(db, "after-delete")
    assert replacement["is_new_user"] is True
    assert replacement["username"] != name
    assert replacement["user"]["account_incarnation"] != incarnation
    assert replacement["user"]["role"] == "user"


def test_concurrent_subject_signins_create_one_account(db):
    nonces = [challenge(db, str(i)) for i in range(6)]
    def complete(nonce):
        return UserDB(db._db_path).complete_google_login(nonce, "same-subject", now=time.time())
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(complete, nonces))
    assert len({result["username"] for result in results}) == 1
    assert sum(result["is_new_user"] for result in results) == 1
    assert db.count() == 1


def test_concurrent_nonce_replay_has_only_one_success(db):
    nonce = challenge(db, "one-browser")
    def complete(_):
        try:
            return UserDB(db._db_path).complete_google_login(nonce, "subject", now=time.time())
        except AccountLifecycleError as exc:
            return exc.reason
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(complete, range(4)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count("google_challenge_invalid") == 3
    assert db.count() == 1


def test_google_tables_are_additive_and_preserve_existing_store(db):
    original = db.create_account("legacy", {"role": "admin", "password_hash": "hash"})
    again = UserDB(db._db_path)
    assert again.get("legacy") == original
    with sqlite3.connect(db._db_path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "account_lifecycles", "external_identities", "google_auth_challenges"} <= names


def test_expected_failure_rolls_back_partial_account_write_but_consumes_nonce(db, monkeypatch):
    import src.storage.user_db as module

    nonce = challenge(db, "partial-write")
    original = module._UserTransaction.create_account

    def create_then_fail(tx, *args, **kwargs):
        original(tx, *args, **kwargs)
        raise AccountLifecycleError("injected_identity_failure")

    monkeypatch.setattr(module._UserTransaction, "create_account", create_then_fail)
    with pytest.raises(AccountLifecycleError, match="injected_identity_failure"):
        db.complete_google_login(nonce, "subject", now=time.time())
    assert db.count() == 0
    monkeypatch.setattr(module._UserTransaction, "create_account", original)
    with pytest.raises(AccountLifecycleError, match="google_challenge_invalid"):
        db.complete_google_login(nonce, "subject", now=time.time())
    assert login(db, "fresh-after-failure", "subject")["is_new_user"] is True


def test_issuing_new_challenge_prunes_expired_records(db, monkeypatch):
    import src.storage.user_db as module

    now = time.time()
    expired = challenge(db, "old", now=now)
    monkeypatch.setattr(module.time, "time", lambda: now + 301)
    current = challenge(db, "current", now=now + 301)
    with sqlite3.connect(db._db_path) as conn:
        assert conn.execute("SELECT nonce_hash FROM google_auth_challenges").fetchall() == [(current,)]
    with pytest.raises(AccountLifecycleError, match="google_challenge_invalid"):
        db.complete_google_login(expired, "subject", now=now)
