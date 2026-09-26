"""Account authority contracts. Every store and legacy file is temporary."""

import asyncio
import inspect
import json
import multiprocessing
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.storage.user_db import AccountLifecycleError, UserDB


def test_policy_receipt_is_persistent_store_authority_not_account_metadata(tmp_path):
    from src.recommendation_state import RecommendationState

    path = tmp_path / "users.db"
    authority = UserDB(path)
    events = tmp_path / "events.db"
    RecommendationState.initialize(events, authority=authority)
    original = authority.policy_store_receipt(events)
    user = authority.create_account("alice", {"policy_store": "forged"})
    authority.upsert(
        "alice",
        {"metadata": {"policy_store": "replacement"}},
        expected_incarnation=user["account_incarnation"],
    )
    assert UserDB(path).policy_store_receipt(events) == original
    with pytest.raises(sqlite3.Error, match="path_mismatch"):
        RecommendationState.initialize(tmp_path / "replacement.db", authority=authority)
    assert not (tmp_path / "replacement.db").exists()
    authority.begin_delete("alice", user["account_incarnation"])
    authority.finish_delete(
        "alice", user["account_incarnation"], cleanup_succeeded=True
    )
    assert authority.policy_store_receipt(events) == original


def test_policy_receipt_read_does_not_create_missing_authority(tmp_path):
    authority = UserDB(tmp_path / "users.db")
    authority._db_path.unlink()
    with pytest.raises(sqlite3.Error):
        authority.policy_store_receipt(tmp_path / "events.db")
    assert not authority._db_path.exists()


def _create_in_process(path, queue):
    db = UserDB(path)
    try:
        queue.put(
            (
                "created",
                db.create_account("alice", {"password_hash": "hash"})[
                    "account_incarnation"
                ],
            )
        )
    except AccountLifecycleError as exc:
        queue.put((exc.reason, db.get("alice")["account_incarnation"]))


def _legacy_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE users (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT, created_at TEXT, metadata TEXT)"
        )
        for name in ("alice", "bob"):
            conn.execute(
                "INSERT INTO users VALUES (?, 'original-hash', 'admin', 'original-date', ?)",
                (
                    name,
                    json.dumps(
                        {
                            "role": "forged",
                            "account_incarnation": "forged",
                            "theme": "dark",
                        }
                    ),
                ),
            )


def test_existing_initialization_preserves_credentials_and_is_stable(tmp_path):
    path = tmp_path / "users.db"
    _legacy_db(path)
    first = UserDB(path).get_all()
    assert UserDB(path).get_all() == first
    assert len({u["account_incarnation"] for u in first.values()}) == 2
    for user in first.values():
        assert user["password_hash"] == "original-hash"
        assert user["role"] == "admin"
        assert user["created_at"] == "original-date"
        assert user["theme"] == "dark"
        assert user["account_incarnation"] != "forged"


def test_initialization_failure_rolls_back_all_schema_and_identities(
    tmp_path, monkeypatch
):
    import src.storage.user_db as module

    path = tmp_path / "users.db"
    _legacy_db(path)
    original = module.uuid.uuid4
    calls = 0

    def fail_second():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected")
        return original()

    monkeypatch.setattr(module.uuid, "uuid4", fail_second)
    with pytest.raises(RuntimeError, match="injected"):
        UserDB(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='account_lifecycles'"
            ).fetchone()
            is None
        )
    monkeypatch.setattr(module.uuid, "uuid4", original)
    assert len(UserDB(path).get_all()) == 2


@pytest.mark.parametrize("existing", [False, True])
def test_multiprocess_initialization_and_registration_have_one_identity(
    tmp_path, existing
):
    path = str(tmp_path / "users.db")
    if existing:
        _legacy_db(path)
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    processes = [
        ctx.Process(target=_create_in_process, args=(path, queue)) for _ in range(4)
    ]
    try:
        for process in processes:
            process.start()
        results = [queue.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        assert [status for status, _ in results].count("created") == (
            0 if existing else 1
        )
        assert {status for status, _ in results} == (
            {"username_reserved"} if existing else {"created", "username_reserved"}
        )
        assert len({identity for _, identity in results}) == 1
        assert UserDB(path).get("alice")["account_incarnation"] == results[0][1]
        if existing:
            assert UserDB(path).get("alice")["password_hash"] == "original-hash"
            assert UserDB(path).get("alice")["role"] == "admin"
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()


def test_registration_rollback_never_leaves_half_account(tmp_path):
    db = UserDB(tmp_path / "users.db")
    with db.transaction() as tx:
        tx.conn.execute("""CREATE TRIGGER fail_lifecycle BEFORE INSERT ON account_lifecycles
                           BEGIN SELECT RAISE(ABORT, 'injected'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        db.create_account("alice", {})
    assert db.get("alice") is None
    with db.transaction() as tx:
        assert tx.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert (
            tx.conn.execute("SELECT COUNT(*) FROM account_lifecycles").fetchone()[0]
            == 0
        )
        assert (
            tx.conn.execute("SELECT COUNT(*) FROM account_history").fetchone()[0] == 0
        )


def test_update_cas_metadata_and_stale_resurrection(tmp_path):
    db = UserDB(tmp_path / "users.db")
    old = db.create_account("alice", {"password_hash": "hash", "role": "admin"})
    incarnation = old["account_incarnation"]
    db.upsert(
        "alice",
        {
            "theme": "dark",
            "metadata": {"account_incarnation": "forged", "role": "forged"},
        },
        expected_incarnation=incarnation,
    )
    current = db.get("alice")
    assert current["password_hash"] == "hash"
    assert current["role"] == "admin"
    assert current["account_incarnation"] == incarnation
    with pytest.raises(AccountLifecycleError, match="incarnation_immutable"):
        db.upsert(
            "alice", {"account_incarnation": "forged"}, expected_incarnation=incarnation
        )
    with pytest.raises(TypeError):
        db.upsert("alice", old)
    db.begin_delete("alice", incarnation)
    db.finish_delete("alice", incarnation, cleanup_succeeded=True)
    with pytest.raises(AccountLifecycleError):
        db.upsert("alice", old, expected_incarnation=incarnation)
    new = db.create_account("alice", {"password_hash": "new", "role": "user"})
    with pytest.raises(AccountLifecycleError):
        db.upsert("alice", old, expected_incarnation=incarnation)
    assert db.get("alice") == new


def test_deletion_reservation_retry_and_late_cleanup(tmp_path):
    db = UserDB(tmp_path / "users.db")
    incarnation = db.create_account("alice", {})["account_incarnation"]
    with pytest.raises(AccountLifecycleError, match="deletion_not_started"):
        db.finish_delete("alice", incarnation, cleanup_succeeded=True)
    assert db.begin_delete("alice", incarnation) == incarnation
    assert db.get("alice") is None
    assert "alice" not in db.get_all()
    db.finish_delete("alice", incarnation, cleanup_succeeded=False)
    db = UserDB(tmp_path / "users.db")
    with pytest.raises(AccountLifecycleError, match="username_reserved"):
        db.create_account("alice", {})
    with pytest.raises(AccountLifecycleError):
        db.validate_principal("alice", incarnation)
    assert db.begin_delete("alice", incarnation) == incarnation
    db.finish_delete("alice", incarnation, cleanup_succeeded=True)
    new = db.create_account("alice", {"password_hash": "replacement"})
    assert new["account_incarnation"] != incarnation
    for operation in (
        lambda: db.begin_delete("alice", incarnation),
        lambda: db.finish_delete("alice", incarnation, cleanup_succeeded=True),
    ):
        with pytest.raises(AccountLifecycleError):
            operation()
    assert db.get("alice") == new


def test_legacy_and_default_admin_cannot_resurrect_deleted_accounts(tmp_path):
    db = UserDB(tmp_path / "users.db")
    old = db.create_account("alice", {})["account_incarnation"]
    db.begin_delete("alice", old)
    db.finish_delete("alice", old, cleanup_succeeded=True)
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps({"alice": {"password_hash": "stale"}, "bob": {"role": "admin"}})
    )
    assert db.migrate_from_json(path) == 1
    assert db.get("alice") is None
    assert db.get("bob")["role"] == "admin"
    assert db.migrate_from_json(path) == 0
    with pytest.raises(AccountLifecycleError, match="store_not_pristine"):
        db.create_account("alice", {}, only_if_pristine=True)


def test_account_guard_serializes_final_commit_and_delete(tmp_path):
    path = tmp_path / "users.db"
    db = UserDB(path)
    incarnation = db.create_account("alice", {})["account_incarnation"]
    started = threading.Event()
    deleted = threading.Event()
    output = tmp_path / "published.json"

    # Initialize the competing connection before acquiring the guard, since
    # initialization itself is intentionally serialized by the same barrier.
    other = UserDB(path)

    def delete_initialized():
        started.set()
        other.begin_delete("alice", incarnation)
        deleted.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with db.account_guard("alice", incarnation):
            future = executor.submit(delete_initialized)
            assert started.wait(2)
            assert not deleted.wait(0.05)
            output.write_text("committed before revoke")
        future.result(timeout=10)
    assert deleted.is_set()
    with pytest.raises(AccountLifecycleError):
        with db.account_guard("alice", incarnation):
            output.write_text("late overwrite")
    assert output.read_text() == "committed before revoke"


@pytest.fixture
def auth_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from routers import auth
    from routers.deps import auth as deps_auth
    from routers.deps import storage

    monkeypatch.setattr(storage, "USERS_FILE", tmp_path / "users.json")
    db = storage._get_user_db()
    monkeypatch.setattr(auth, "_get_user_db", lambda: db)
    return db, auth, deps_auth, storage


def _request(token=None):
    headers = [] if token is None else [(b"authorization", f"Bearer {token}".encode())]
    return Request(
        {
            "type": "http",
            "headers": headers,
            "method": "GET",
            "path": "/",
            "client": ("127.0.0.1", 1234),
        }
    )


def test_missing_old_mismatched_and_deleted_jwt_fail_all_dependencies(
    auth_store, monkeypatch
):
    db, auth, deps, _ = auth_store
    record = db.create_account("alice", {"role": "admin"})
    incarnation = record["account_incarnation"]
    valid = auth._create_token("alice", account_incarnation=incarnation)
    payload = {
        "sub": "alice",
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    missing = jwt.encode(payload, auth.JWT_SECRET, algorithm="HS256")
    mismatch = jwt.encode(
        {**payload, "account_incarnation": "wrong"}, auth.JWT_SECRET, algorithm="HS256"
    )
    principal = asyncio.run(deps.get_authenticated_principal(_request(valid)))
    assert (principal.username, principal.account_incarnation) == ("alice", incarnation)
    assert asyncio.run(deps.get_admin_user(_request(valid))) == "alice"
    for token in (missing, mismatch):
        with pytest.raises(HTTPException) as failure:
            auth._decode_token(token)
        assert failure.value.status_code == 401
    db.begin_delete("alice", incarnation)
    for token in (missing, mismatch, valid):
        with pytest.raises(HTTPException) as failure:
            auth._decode_token(token)
        assert failure.value.status_code == 401
        for dependency in (
            deps.get_current_user,
            deps.get_admin_user,
            deps.get_authenticated_principal,
        ):
            with pytest.raises(HTTPException) as failure:
                asyncio.run(dependency(_request(token)))
            assert failure.value.status_code == 401
        assert asyncio.run(deps.get_optional_user(_request(token))) is None
        with pytest.raises(HTTPException):
            asyncio.run(inspect.unwrap(auth.verify_token)(_request(token)))
    monkeypatch.setattr(deps, "is_mcp_request", lambda headers: True)
    with pytest.raises(HTTPException):
        asyncio.run(deps.get_optional_user(_request(valid)))
    db.finish_delete("alice", incarnation, cleanup_succeeded=True)
    new = db.create_account("alice", {"role": "user"})
    with pytest.raises(HTTPException):
        auth._decode_token(valid)
    new_token = auth._create_token(
        "alice", account_incarnation=new["account_incarnation"]
    )
    assert auth._decode_token(new_token)["sub"] == "alice"


def test_current_role_overrides_signed_role_and_optional_unavailable(
    auth_store, monkeypatch
):
    db, auth, deps, _ = auth_store
    old = db.create_account("alice", {"role": "admin"})
    token = auth._create_token("alice", account_incarnation=old["account_incarnation"])
    db.upsert(
        "alice", {"role": "user"}, expected_incarnation=old["account_incarnation"]
    )
    assert auth._decode_token(token)["role"] == "user"
    with pytest.raises(HTTPException) as failure:
        asyncio.run(deps.get_admin_user(_request(token)))
    assert failure.value.status_code == 403
    assert asyncio.run(deps.get_optional_user(_request())) is None

    def unavailable(*args):
        raise sqlite3.OperationalError("injected")

    monkeypatch.setattr(db, "validate_principal", unavailable)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(deps.get_optional_user(_request(token)))
    assert failure.value.status_code == 503


def test_login_race_never_issues_replacement_identity(auth_store, monkeypatch):
    db, auth, _, _ = auth_store
    original = db.create_account("alice", {"password_hash": "original", "role": "user"})

    def verify_and_replace(password, stored):
        assert stored == "original"
        db.begin_delete("alice", original["account_incarnation"])
        db.finish_delete(
            "alice", original["account_incarnation"], cleanup_succeeded=True
        )
        db.create_account("alice", {"password_hash": "replacement", "role": "admin"})
        return True

    monkeypatch.setattr(auth, "_verify_password", verify_and_replace)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(
            inspect.unwrap(auth.login)(
                _request(), auth.LoginRequest(username="alice", password="secret")
            )
        )
    assert failure.value.status_code == 401
    assert db.get("alice")["password_hash"] == "replacement"


def test_successful_login_and_password_migration_keep_identity(auth_store, monkeypatch):
    db, auth, _, _ = auth_store
    record = db.create_account(
        "alice", {"password_hash": "a" * 64, "role": "admin", "created_at": "then"}
    )
    monkeypatch.setattr(auth, "_verify_password", lambda password, stored: True)
    monkeypatch.setattr(auth, "_hash_password", lambda password: "upgraded")
    response = asyncio.run(
        inspect.unwrap(auth.login)(
            _request(), auth.LoginRequest(username="alice", password="secret")
        )
    )
    payload = auth._decode_token(response.access_token)
    assert payload["account_incarnation"] == record["account_incarnation"]
    assert db.get("alice") == {**record, "password_hash": "upgraded"}


def test_helpers_reject_new_deleted_and_reincarnated_snapshots(auth_store):
    db, _, _, storage = auth_store
    old = db.create_account("alice", {"role": "admin"})
    with pytest.raises(
        AccountLifecycleError, match="explicit_lifecycle_operation_required"
    ):
        with storage.modify_users() as users:
            del users["alice"]
    assert db.get("alice") == old
    with storage.modify_users() as users:
        users["alice"]["role"] = "user"
    assert db.get("alice")["role"] == "user"
    snapshot = storage.load_users()
    db.begin_delete("alice", old["account_incarnation"])
    db.finish_delete("alice", old["account_incarnation"], cleanup_succeeded=True)
    new = db.create_account("alice", {"role": "admin"})
    with pytest.raises(AccountLifecycleError):
        storage.save_users(snapshot)
    assert db.get("alice") == new
    with pytest.raises(AccountLifecycleError):
        storage.save_users({"bob": {"role": "admin"}})
    assert db.get("bob") is None
