"""Durable tagged event writes are serialized with temporary account authority."""

import asyncio
import sqlite3

import pytest

from src.events.event_bus import EventBus
from src.events.event_types import EventType, UserEvent
from src.storage.user_db import AccountLifecycleError, UserDB


def event(incarnation=None):
    payload = {} if incarnation is None else {"account_incarnation": incarnation}
    return UserEvent(
        user_id="alice", event_type=EventType.BOOKMARK_ADD, payload=payload
    )


def count(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT COUNT(*) FROM user_events").fetchone()[0]


@pytest.mark.parametrize("mode", ["sync", "immediate", "batch", "drain"])
def test_late_old_identity_cannot_reinsert_after_cleanup(tmp_path, mode):
    db = UserDB(tmp_path / "users.db")
    old = db.create_account("alice", {})["account_incarnation"]
    path = tmp_path / "events.db"
    bus = EventBus(path, account_authority=db)
    queued = event(old)
    bus.persist_only(queued)
    assert count(path) == 1
    db.begin_delete("alice", old)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM user_events WHERE user_id='alice'")
    db.finish_delete("alice", old, cleanup_succeeded=True)
    new = db.create_account("alice", {})["account_incarnation"]
    try:
        if mode == "sync":
            with pytest.raises(AccountLifecycleError):
                bus.persist_only(queued)
        elif mode == "immediate":
            with pytest.raises(AccountLifecycleError):
                asyncio.run(bus.flush_immediately(queued))
        elif mode == "batch":
            asyncio.run(bus._persist_batch([queued]))
        else:
            bus._batch_queue.put_nowait(queued)
            asyncio.run(bus.wait_for_drain(timeout=0))
        assert count(path) == 0
        bus.persist_only(event(new))
        assert count(path) == 1
    finally:
        bus.close()


def test_unbound_and_unavailable_authority_fail_closed_but_untagged_still_persists(
    tmp_path, monkeypatch
):
    path = tmp_path / "events.db"
    bus = EventBus(path)
    try:
        with pytest.raises(AccountLifecycleError, match="unbound"):
            bus.persist_only(event("inc"))
        asyncio.run(bus._persist_batch([event("inc")]))
        assert count(path) == 0
        bus.persist_only(event())
        assert count(path) == 1
        db = UserDB(tmp_path / "users.db")
        inc = db.create_account("alice", {})["account_incarnation"]
        bus.bind_account_authority(db)

        def fail(*args):
            raise sqlite3.OperationalError("unavailable")

        monkeypatch.setattr(db, "account_guard", fail)
        with pytest.raises(sqlite3.OperationalError):
            bus.persist_only(event(inc))
        asyncio.run(bus._persist_batch([event(inc)]))
        assert count(path) == 1
    finally:
        bus.close()


def test_mixed_identity_batch_commits_before_next_users_guard(tmp_path, monkeypatch):
    from contextlib import contextmanager

    db = UserDB(tmp_path / "users.db")
    inc = db.create_account("alice", {})["account_incarnation"]
    bus = EventBus(tmp_path / "events.db", account_authority=db)
    original = db.account_guard
    guards = []
    statements = []
    bus._conn.set_trace_callback(statements.append)

    @contextmanager
    def observed(*args):
        guards.append(args)
        assert not bus._conn.in_transaction
        assert not bus._db_lock.locked()
        with original(*args) as account:
            yield account
        assert not bus._conn.in_transaction

    monkeypatch.setattr(db, "account_guard", observed)
    try:
        asyncio.run(
            bus._persist_batch(
                [
                    event(inc),
                    event(inc),
                    event("wrong"),
                    event("wrong"),
                    event(),
                    event(),
                    event(inc),
                    event(inc),
                ]
            )
        )
        assert count(tmp_path / "events.db") == 6
        assert guards == [("alice", inc), ("alice", "wrong"), ("alice", inc)]
        assert sum(sql == "BEGIN IMMEDIATE" for sql in statements) == 3
        assert sum(sql == "COMMIT" for sql in statements) == 3
        # Every successful group contains two INSERTs, not two transactions.
        groups = []
        inserts = 0
        for sql in statements:
            if sql.startswith("INSERT INTO user_events"):
                inserts += 1
            if sql == "COMMIT":
                groups.append(inserts)
                inserts = 0
        assert groups == [2, 2, 2]
    finally:
        bus.close()


def test_real_background_publish_drains_and_awaits_flusher_shutdown(tmp_path):
    async def scenario():
        db = UserDB(tmp_path / "users.db")
        inc = db.create_account("alice", {})["account_incarnation"]
        path = tmp_path / "events.db"
        bus = EventBus(path, account_authority=db)
        try:
            await bus.publish(event(inc))
            await bus.publish(event(inc))
            await bus.wait_for_drain()
            assert count(path) == 2
        finally:
            # close() requests cancellation; the owning loop must observe it
            # before teardown. Never leave a live task on a closing test loop.
            await bus.wait_for_drain()
            task = bus._batch_task
            bus.close()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
                assert task.done()

    asyncio.run(scenario())


def test_adjacent_different_users_never_share_authority_guard(tmp_path, monkeypatch):
    from contextlib import contextmanager

    db = UserDB(tmp_path / "users.db")
    alice = db.create_account("alice", {})["account_incarnation"]
    bob = db.create_account("bob", {})["account_incarnation"]
    bus = EventBus(tmp_path / "events.db", account_authority=db)
    original = db.account_guard
    seen = []

    @contextmanager
    def observed(username, incarnation):
        assert not bus._conn.in_transaction and not bus._db_lock.locked()
        seen.append((username, incarnation))
        with original(username, incarnation) as account:
            yield account

    monkeypatch.setattr(db, "account_guard", observed)
    bob_event = UserEvent(
        user_id="bob",
        event_type=EventType.BOOKMARK_ADD,
        payload={"account_incarnation": bob},
    )
    try:
        asyncio.run(
            bus._persist_batch([event(alice), bob_event, bob_event, event(alice)])
        )
        assert seen == [("alice", alice), ("bob", bob), ("alice", alice)]
        assert count(tmp_path / "events.db") == 4
    finally:
        bus.close()
