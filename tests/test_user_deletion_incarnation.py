"""Deletion barriers use temporary stores only; no production app import."""

import asyncio
import inspect
import json
import multiprocessing
import sqlite3

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from filelock import FileLock
from starlette.requests import Request

from src.storage.user_db import AccountLifecycleError, UserDB


def test_initial_accounts_share_frozen_readonly_legacy_cutoff(tmp_path):
    from datetime import datetime, timezone

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE users (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT, created_at TEXT, metadata TEXT)"
        )
        for name in ("alice", "bob"):
            conn.execute(
                "INSERT INTO users VALUES (?, 'hash', 'admin', 'original', ?)",
                (
                    name,
                    json.dumps({"legacy_event_cutoff": "2999-01-01T00:00:00+00:00"}),
                ),
            )
    before = datetime.now(timezone.utc)
    db = UserDB(path)
    first = db.get_all()
    cutoff = first["alice"]["legacy_event_cutoff"]
    assert before <= datetime.fromisoformat(cutoff) <= datetime.now(timezone.utc)
    assert first["bob"]["legacy_event_cutoff"] == cutoff
    assert UserDB(path).get_all() == first
    db.upsert(
        "alice",
        {"legacy_event_cutoff": None, "metadata": {"legacy_event_cutoff": "forged"}},
        expected_incarnation=first["alice"]["account_incarnation"],
    )
    assert db.get("alice")["legacy_event_cutoff"] == cutoff
    assert db.get("alice")["password_hash"] == "hash"
    incarnation = first["alice"]["account_incarnation"]
    db.begin_delete("alice", incarnation)
    db.finish_delete("alice", incarnation, cleanup_succeeded=True)
    replacement = db.create_account(
        "alice",
        {"legacy_event_cutoff": cutoff, "metadata": {"legacy_event_cutoff": cutoff}},
    )
    assert replacement["legacy_event_cutoff"] is None
    assert replacement["account_incarnation"] != incarnation
    assert UserDB(path).get("alice")["legacy_event_cutoff"] is None
    assert (
        db.create_account("new", {"legacy_event_cutoff": cutoff})["legacy_event_cutoff"]
        is None
    )


def test_legacy_json_uses_store_cutoff_not_payload_and_never_resurrects(tmp_path):
    db = UserDB(tmp_path / "users.db")
    original = db.create_account("deleted", {})
    db.begin_delete("deleted", original["account_incarnation"])
    db.finish_delete("deleted", original["account_incarnation"], cleanup_succeeded=True)
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "legacy": {
                    "role": "admin",
                    "legacy_event_cutoff": "2999-01-01",
                    "metadata": {"legacy_event_cutoff": "forged"},
                },
                "deleted": {"legacy_event_cutoff": "2999-01-01"},
            }
        )
    )
    with db.transaction() as tx:
        frozen = tx.conn.execute(
            "SELECT value FROM account_store_meta WHERE key='legacy_event_cutoff'"
        ).fetchone()[0]
    assert db.migrate_from_json(path) == 1
    assert db.get("legacy")["legacy_event_cutoff"] == frozen
    assert db.get("deleted") is None
    assert UserDB(tmp_path / "users.db").get("legacy")["legacy_event_cutoff"] == frozen
    assert db.migrate_from_json(path) == 0


def test_failed_initialization_rolls_back_cutoff_and_all_identities(
    tmp_path, monkeypatch
):
    import src.storage.user_db as module

    path = tmp_path / "users.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE users (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT, created_at TEXT, metadata TEXT)"
        )
        conn.executemany(
            "INSERT INTO users VALUES (?, 'hash', 'user', 'old', NULL)",
            [("alice",), ("bob",)],
        )
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
                "SELECT name FROM sqlite_master WHERE name IN ('account_lifecycles','account_store_meta')"
            ).fetchall()
            == []
        )
    monkeypatch.setattr(module.uuid, "uuid4", original)
    records = UserDB(path).get_all()
    assert (
        records["alice"]["legacy_event_cutoff"] == records["bob"]["legacy_event_cutoff"]
    )
    assert records["alice"]["legacy_event_cutoff"] is not None


def _hold_cleanup_lock(path, ready, release):
    db = UserDB(path)
    with db.cleanup_lock("alice"):
        ready.set()
        release.wait(15)


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from routers.deps import storage, user_deletion as deletion
    from routers.deps.auth import AuthenticatedPrincipal
    from src.storage.bookmark_db import BookmarkDB

    db = UserDB(tmp_path / "users.db")
    bookmarks = BookmarkDB(tmp_path / "bookmarks.db")
    monkeypatch.setattr(deletion, "_get_user_db", lambda: db)
    monkeypatch.setattr(storage, "_get_user_db", lambda: db)
    monkeypatch.setattr(deletion, "_get_bookmark_db", lambda: bookmarks)
    paths = {
        "events_db": tmp_path / "events.db",
        "profile_db": tmp_path / "profile.db",
        "embeddings_users_dir": tmp_path / "embeddings",
        "blog_posts_file": tmp_path / "posts.json",
        "blog_posts_lock": FileLock(str(tmp_path / "posts.lock")),
        "curricula_dir": tmp_path / "curricula",
        "audit_log": tmp_path / "audit.jsonl",
        "papers_file": tmp_path / "papers.json",
        "mcp_analytics_db": tmp_path / "mcp.db",
        "recommendations_dir": tmp_path / "recommendations",
        "recommendation_candidates_dir": tmp_path / "candidates",
    }
    with sqlite3.connect(paths["events_db"]) as conn:
        conn.execute("CREATE TABLE user_events(user_id TEXT)")
        conn.execute("INSERT INTO user_events VALUES ('alice')")
    from src.recommendation_state import RecommendationState

    RecommendationState.initialize(paths["events_db"], authority=db)
    alice = db.create_account("alice", {"password_hash": "old", "role": "user"})
    admin = db.create_account("operator", {"role": "admin"})
    actor = AuthenticatedPrincipal("operator", admin["account_incarnation"])
    return SimpleNamespace(
        db=db,
        deletion=deletion,
        paths=paths,
        incarnation=alice["account_incarnation"],
        actor=actor,
        tmp=tmp_path,
    )


def _delete(s, **kwargs):
    return s.deletion.delete_user_cascade(
        "alice", account_incarnation=s.incarnation, paths=s.paths, **kwargs
    )


@pytest.mark.parametrize("loss", ["file", "table"])
def test_policy_store_loss_during_deletion_retains_reservation(stores, loss):
    from src.recommendation_state import RecommendationState

    s = stores
    policy = RecommendationState(s.paths["events_db"], authority=s.db)
    policy.apply_action(
        s.incarnation,
        run_id="run",
        canonical_key="paper",
        action="hide",
        request_id="hide-before-loss",
    )
    if loss == "file":
        s.paths["events_db"].unlink()
    else:
        with sqlite3.connect(s.paths["events_db"]) as conn:
            conn.execute("DROP TABLE recommendation_actions")
    result = _delete(s)
    assert not result.deleted and result.retryable
    assert "recommendations" in result.partial_failures
    assert s.db.get_lifecycle("alice")["state"] == "cleanup_pending"
    with pytest.raises(AccountLifecycleError, match="username_reserved"):
        s.db.create_account("alice", {})
    retry = _delete(s, actor=s.actor)
    assert not retry.deleted and "recommendations" in retry.partial_failures
    with pytest.raises(sqlite3.Error):
        RecommendationState.initialize(s.paths["events_db"], authority=s.db)
    if loss == "file":
        assert not s.paths["events_db"].exists()


def _owned_file(root, owner):
    target = root / owner / "run" / "raw.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("private")
    return target


def test_success_revokes_old_jwt_cleans_only_owner_and_recreates(stores, monkeypatch):
    s = stores
    from routers import auth

    monkeypatch.setattr(auth, "_get_user_db", lambda: s.db)
    token = auth._create_token("alice", account_incarnation=s.incarnation)
    owned = _owned_file(s.paths["recommendations_dir"], s.incarnation)
    legacy = _owned_file(s.paths["recommendations_dir"], "alice")
    legacy.write_text(json.dumps({"user_id": "alice"}))
    private = _owned_file(
        s.paths["recommendation_candidates_dir"] / "private", s.incarnation
    )
    public = _owned_file(s.paths["recommendation_candidates_dir"], "public")
    unrelated = _owned_file(s.paths["recommendations_dir"], "other")
    result = _delete(s)
    assert result.deleted and not result.retryable
    assert not owned.exists() and not legacy.exists() and not private.exists()
    assert public.exists() and unrelated.exists()
    assert s.db.get_lifecycle("alice") is None
    replacement = s.db.create_account("alice", {"password_hash": "new"})
    assert replacement["account_incarnation"] != s.incarnation
    with pytest.raises(HTTPException) as error:
        auth._decode_token(token)
    assert error.value.status_code == 401


@pytest.mark.parametrize("failure", ["bookmarks", "policy", "files", "audit"])
def test_failure_reserves_identity_until_admin_retry(stores, monkeypatch, failure):
    s = stores
    from src.recommendation_state import RecommendationState

    def fail(*args, **kwargs):
        raise OSError("injected")

    with monkeypatch.context() as patch:
        if failure == "bookmarks":
            patch.setattr(s.deletion, "_stage_bookmarks", fail)
        elif failure == "policy":
            patch.setattr(RecommendationState, "delete_incarnation", fail)
        elif failure == "files":
            patch.setattr(s.deletion, "_remove_owned_tree", fail)
        else:
            patch.setattr(s.deletion, "append_audit_log", fail)
        result = _delete(s)
    assert not result.deleted and result.retryable
    assert s.db.get("alice") is None
    assert s.db.get_lifecycle("alice") == {
        "account_incarnation": s.incarnation,
        "state": "cleanup_pending",
    }
    with pytest.raises(AccountLifecycleError, match="username_reserved"):
        s.db.create_account("alice", {})
    assert _delete(s, actor=s.actor).deleted
    assert s.db.create_account("alice", {})["account_incarnation"] != s.incarnation


def test_late_old_retry_never_touches_replacement_username_data(stores, monkeypatch):
    s = stores
    assert _delete(s).deleted
    replacement = s.db.create_account("alice", {"password_hash": "new"})
    new_file = _owned_file(s.paths["recommendations_dir"], "alice")
    with sqlite3.connect(s.paths["events_db"]) as conn:
        conn.execute("INSERT INTO user_events VALUES ('alice')")
    calls = []
    monkeypatch.setattr(
        s.deletion, "_stage_rubric_db", lambda *args: calls.append("cleanup")
    )
    result = _delete(s, actor=s.actor)
    assert not result.deleted and not result.retryable
    assert result.partial_failures == ["account_inactive_or_mismatch"]
    assert calls == [] and new_file.exists()
    assert s.db.get("alice") == replacement
    with sqlite3.connect(s.paths["events_db"]) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM user_events WHERE user_id='alice'"
            ).fetchone()[0]
            == 1
        )


def test_cross_process_cleanup_lock_is_nonblocking(stores):
    s = stores
    ctx = multiprocessing.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    process = ctx.Process(
        target=_hold_cleanup_lock, args=(s.tmp / "users.db", ready, release)
    )
    process.start()
    try:
        assert ready.wait(10)
        result = _delete(s)
        assert result.partial_failures == ["cleanup_busy"] and result.retryable
        assert s.db.get("alice") is not None
    finally:
        release.set()
        process.join(15)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert process.exitcode == 0
    assert _delete(s).deleted


def test_revoke_precedes_cleanup_without_holding_authority_lock(stores, monkeypatch):
    s = stores
    original = s.deletion._stage_bookmarks

    def observe(username):
        other = UserDB(s.tmp / "users.db")
        assert other.get_lifecycle(username)["state"] == "deleting"
        with pytest.raises(AccountLifecycleError):
            other.validate_principal(username, s.incarnation)
        with pytest.raises(AccountLifecycleError):
            other.create_account(username, {})
        assert _delete(s, actor=s.actor).partial_failures == ["cleanup_busy"]
        original(username)

    monkeypatch.setattr(s.deletion, "_stage_bookmarks", observe)
    assert _delete(s).deleted


def test_authority_failure_runs_no_cleanup(stores, monkeypatch):
    s = stores
    calls = []
    monkeypatch.setattr(s.deletion, "_stage_bookmarks", lambda name: calls.append(name))

    def fail():
        raise sqlite3.OperationalError("injected")

    monkeypatch.setattr(s.deletion, "_get_user_db", fail)
    result = _delete(s)
    assert result.partial_failures == ["account_authority"] and result.retryable
    assert calls == []


def test_symlink_cleanup_fails_closed_and_preserves_external_files(stores):
    s = stores
    outside = s.tmp / "outside"
    outside.mkdir()
    secret = outside / "keep"
    secret.write_text("untouched")
    root = s.paths["recommendations_dir"]
    root.mkdir()
    (root / s.incarnation).symlink_to(outside, target_is_directory=True)
    result = _delete(s)
    assert "recommendations" in result.partial_failures
    assert secret.read_text() == "untouched"
    assert s.db.get_lifecycle("alice")["state"] == "cleanup_pending"


def test_legacy_collision_does_not_remove_other_generation(stores):
    s = stores
    colliding = _owned_file(s.paths["recommendations_dir"], "alice")
    colliding.write_text(
        json.dumps({"user_id": "other", "account_incarnation": "alice"})
    )
    result = _delete(s)
    assert "recommendations" in result.partial_failures and result.retryable
    assert colliding.exists()


def test_finalize_failure_keeps_revocation_and_supports_admin_retry(
    stores, monkeypatch
):
    s = stores

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("injected")

    with monkeypatch.context() as patch:
        patch.setattr(s.db, "finish_delete", fail)
        result = _delete(s)
    assert result.partial_failures == ["account_authority"] and result.retryable
    assert s.db.get_lifecycle("alice")["state"] == "deleting"
    with pytest.raises(AccountLifecycleError):
        s.db.validate_principal("alice", s.incarnation)
    assert _delete(s, actor=s.actor).deleted


def test_corrupt_owner_input_prevents_false_complete_cleanup(stores):
    s = stores
    s.paths["blog_posts_file"].write_text("{}")
    result = _delete(s)
    assert "blog_anonymize" in result.partial_failures and result.retryable
    assert s.db.get_lifecycle("alice")["state"] == "cleanup_pending"


def _request():
    return Request(
        {
            "type": "http",
            "headers": [],
            "method": "DELETE",
            "path": "/",
            "client": ("127.0.0.1", 1234),
        }
    )


def test_self_endpoint_uses_captured_principal_not_replacement(stores, monkeypatch):
    s = stores
    from routers import me
    from routers.deps.auth import AuthenticatedPrincipal

    principal = AuthenticatedPrincipal("alice", s.incarnation)
    assert _delete(s).deleted
    replacement = s.db.create_account("alice", {"password_hash": "new"})
    monkeypatch.setattr(
        me,
        "delete_user_cascade",
        lambda name, **kwargs: s.deletion.delete_user_cascade(
            name, paths=s.paths, **kwargs
        ),
    )
    response = Response()
    result = asyncio.run(inspect.unwrap(me.delete_all)(_request(), response, principal))
    assert not result.deleted and response.status_code == 409
    assert s.db.get("alice") == replacement


def test_admin_endpoint_retries_pending_without_credentials(stores, monkeypatch):
    s = stores
    from routers import admin

    monkeypatch.setattr(admin, "_get_user_db", lambda: s.db)
    monkeypatch.setattr(
        admin,
        "delete_user_cascade",
        lambda name, **kwargs: s.deletion.delete_user_cascade(
            name, paths=s.paths, **kwargs
        ),
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            s.deletion,
            "_stage_bookmarks",
            lambda name: (_ for _ in ()).throw(OSError("injected")),
        )
        assert not _delete(s).deleted
    response = Response()
    result = asyncio.run(
        inspect.unwrap(admin.delete_user)(_request(), "alice", response, s.actor)
    )
    assert result["success"] and not result["retryable"]
    assert s.db.get_lifecycle("alice") is None


def test_admin_target_replaced_between_capture_and_revoke_is_not_deleted(
    stores, monkeypatch
):
    s = stores
    from routers import admin

    monkeypatch.setattr(admin, "_get_user_db", lambda: s.db)
    replacement = {}

    def replace_then_delete(name, **kwargs):
        assert kwargs["account_incarnation"] == s.incarnation
        s.db.begin_delete(name, s.incarnation)
        s.db.finish_delete(name, s.incarnation, cleanup_succeeded=True)
        replacement.update(s.db.create_account(name, {"password_hash": "new"}))
        return s.deletion.delete_user_cascade(name, paths=s.paths, **kwargs)

    monkeypatch.setattr(admin, "delete_user_cascade", replace_then_delete)
    response = Response()
    result = asyncio.run(
        inspect.unwrap(admin.delete_user)(_request(), "alice", response, s.actor)
    )
    assert not result["success"] and response.status_code == 409
    assert s.db.get("alice") == replacement


def test_self_partial_response_is_explicitly_retryable(stores, monkeypatch):
    s = stores
    from routers import me
    from routers.deps.auth import AuthenticatedPrincipal

    monkeypatch.setattr(
        me,
        "delete_user_cascade",
        lambda name, **kwargs: s.deletion.delete_user_cascade(
            name, paths=s.paths, **kwargs
        ),
    )
    monkeypatch.setattr(
        s.deletion,
        "_stage_bookmarks",
        lambda name: (_ for _ in ()).throw(OSError("injected")),
    )
    response = Response()
    result = asyncio.run(
        inspect.unwrap(me.delete_all)(
            _request(),
            response,
            AuthenticatedPrincipal("alice", s.incarnation),
        )
    )
    assert not result.deleted and result.retryable and response.status_code == 503
    assert s.db.get_lifecycle("alice")["state"] == "cleanup_pending"


def test_admin_demotion_rechecked_before_cleanup_and_role_cas(stores, monkeypatch):
    s = stores
    from routers import admin

    monkeypatch.setattr(admin, "_get_user_db", lambda: s.db)
    asyncio.run(
        admin.update_user_role("alice", admin.RoleUpdateRequest(role="admin"), s.actor)
    )
    assert s.db.get("alice")["account_incarnation"] == s.incarnation
    s.db.upsert(
        "operator", {"role": "user"}, expected_incarnation=s.actor.account_incarnation
    )
    result = _delete(s, actor=s.actor)
    assert result.partial_failures == ["admin_required"]
    assert s.db.get("alice") is not None
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            admin.update_user_role(
                "alice", admin.RoleUpdateRequest(role="user"), s.actor
            )
        )
    assert error.value.status_code == 403


def test_stale_admin_principal_cannot_delete_after_actor_recreation(stores):
    s = stores
    s.db.begin_delete("operator", s.actor.account_incarnation)
    s.db.finish_delete("operator", s.actor.account_incarnation, cleanup_succeeded=True)
    s.db.create_account("operator", {"role": "admin"})
    result = _delete(s, actor=s.actor)
    assert result.partial_failures == ["account_inactive_or_mismatch"]
    assert s.db.get("alice") is not None
