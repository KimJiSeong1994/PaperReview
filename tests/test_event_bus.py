"""
Tests for :mod:`src.events.event_bus`.

Covers the five US-003 acceptance cases:

* Persistence before fan-out
* Subscriber invocation + drain semantics
* Subscriber exception isolation
* Concurrent publish correctness
* Unsubscribe idempotency

All tests create an isolated SQLite DB inside ``tmp_path`` so they run
hermetically, without the module-level singleton from
:func:`~src.events.event_bus.init_event_bus`.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure project root is importable when running with --noconftest.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.events.event_bus import (  # noqa: E402
    EventBus,
    Subscription,
    get_event_bus,
    init_event_bus,
)
from src.events.event_types import EventType, UserEvent  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    user_id: str = "alice",
    event_type: EventType = EventType.PAPER_OPEN,
    payload: dict[str, Any] | None = None,
    paper_id: str | None = "arxiv:1234.5678",
) -> UserEvent:
    """Build a ``UserEvent`` with reasonable test defaults."""
    return UserEvent(
        user_id=user_id,
        event_type=event_type,
        payload=payload if payload is not None else {"k": "v"},
        paper_id=paper_id,
    )


def _row_count(db_path: Path) -> int:
    """Return the number of rows in ``user_events``."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT COUNT(*) FROM user_events").fetchone()
        return int(row[0])
    finally:
        conn.close()


@pytest.fixture
def bus(tmp_path: Path) -> EventBus:
    """Yield a fresh EventBus backed by an isolated tmp_path DB."""
    db_path = tmp_path / "events.db"
    instance = EventBus(db_path)
    try:
        yield instance
    finally:
        instance.close()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def test_publish_persists_event(bus: EventBus, tmp_path: Path) -> None:
    """publish → DB contains exactly one row with all columns round-tripped."""
    event = _make_event(
        user_id="bob",
        event_type=EventType.BOOKMARK_ADD,
        payload={"note": "interesting"},
        paper_id="arxiv:2024.00001",
    )

    await bus.publish(event)
    await bus.wait_for_drain()

    db_path = tmp_path / "events.db"
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            """
            SELECT user_id, event_type, payload, paper_id, created_at, source
            FROM user_events
            """
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "event was not persisted"
    user_id, event_type, payload, paper_id, created_at, source = row
    assert user_id == "bob"
    assert event_type == EventType.BOOKMARK_ADD.value
    assert json.loads(payload) == {"note": "interesting"}
    assert paper_id == "arxiv:2024.00001"
    assert created_at == event.created_at.isoformat()
    assert source == "app"


# ---------------------------------------------------------------------------
# Subscriber + drain
# ---------------------------------------------------------------------------


async def test_subscriber_called_and_drained(bus: EventBus) -> None:
    """Registered subscriber must receive the published event after drain."""
    received: list[UserEvent] = []

    async def _cb(evt: UserEvent) -> None:
        received.append(evt)

    bus.subscribe(_cb)
    event = _make_event()

    await bus.publish(event)
    await bus.wait_for_drain()

    assert len(received) == 1
    assert received[0].user_id == event.user_id
    assert received[0].event_type == event.event_type


# ---------------------------------------------------------------------------
# Subscriber exception isolation
# ---------------------------------------------------------------------------


async def test_subscriber_exception_isolated(
    bus: EventBus, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """
    A raising subscriber must:

    * not prevent persistence,
    * not prevent other subscribers from running,
    * not raise out of publish().
    """
    good_calls: list[UserEvent] = []

    async def _bad(_: UserEvent) -> None:
        raise RuntimeError("boom")

    async def _good(evt: UserEvent) -> None:
        good_calls.append(evt)

    bus.subscribe(_bad)
    bus.subscribe(_good)

    event = _make_event(user_id="carol")

    # Must not raise despite the bad subscriber.
    await bus.publish(event)
    await bus.wait_for_drain()

    # Event is persisted even though one subscriber failed.
    assert _row_count(tmp_path / "events.db") == 1
    # Other subscriber still got the event.
    assert len(good_calls) == 1 and good_calls[0].user_id == "carol"


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


async def test_concurrent_publish(bus: EventBus, tmp_path: Path) -> None:
    """20 concurrent publishes must all persist (no lost writes)."""
    events = [
        _make_event(user_id=f"user_{i}", payload={"i": i}) for i in range(20)
    ]

    await asyncio.gather(*(bus.publish(e) for e in events))
    await bus.wait_for_drain()

    assert _row_count(tmp_path / "events.db") == 20


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------


async def test_unsubscribe(bus: EventBus) -> None:
    """After unsubscribe, subsequent publishes must not invoke the callback."""
    calls: list[UserEvent] = []

    async def _cb(evt: UserEvent) -> None:
        calls.append(evt)

    sub: Subscription = bus.subscribe(_cb)

    await bus.publish(_make_event(user_id="dora"))
    await bus.wait_for_drain()
    assert len(calls) == 1

    bus.unsubscribe(sub)

    await bus.publish(_make_event(user_id="dora"))
    await bus.wait_for_drain()
    assert len(calls) == 1, "callback fired after unsubscribe"

    # Unsubscribing twice must be a no-op.
    bus.unsubscribe(sub)


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------


def test_get_event_bus_before_init_raises() -> None:
    """get_event_bus() must raise RuntimeError when no init has happened."""
    import src.events.event_bus as module

    # Snapshot + clear so other tests that use the singleton aren't affected.
    previous = module._bus
    module._bus = None
    try:
        with pytest.raises(RuntimeError, match="event_bus not initialized"):
            get_event_bus()
    finally:
        module._bus = previous


def test_init_event_bus_returns_singleton(tmp_path: Path) -> None:
    """init_event_bus must install a bus retrievable via get_event_bus."""
    import src.events.event_bus as module

    previous = module._bus
    module._bus = None
    try:
        bus = init_event_bus(tmp_path / "events.db")
        assert get_event_bus() is bus
    finally:
        if module._bus is not None and module._bus is not previous:
            module._bus.close()
        module._bus = previous


# ---------------------------------------------------------------------------
# persist_only (sync path used by emit_or_warn when no loop is available)
# ---------------------------------------------------------------------------


def test_persist_only_writes_without_loop(bus: EventBus, tmp_path: Path) -> None:
    """persist_only must write the event synchronously and skip fan-out.

    Requirements:
      * one row lands in ``user_events`` after the call
      * no asyncio loop is required at the call site
      * subscribers are NOT invoked (fan-out is intentionally skipped)
    """
    subscriber_calls: list[UserEvent] = []

    async def _cb(evt: UserEvent) -> None:  # pragma: no cover - defensive
        subscriber_calls.append(evt)

    bus.subscribe(_cb)

    event = _make_event(user_id="zoe", payload={"sync": True})

    # Call synchronously from a plain (non-async) test function — no
    # running loop. Must not raise.
    bus.persist_only(event)

    # Row landed on disk.
    assert _row_count(tmp_path / "events.db") == 1

    # Fan-out was skipped.
    assert subscriber_calls == []

    # Payload round-trips correctly.
    conn = sqlite3.connect(str(tmp_path / "events.db"))
    try:
        row = conn.execute(
            "SELECT user_id, event_type, payload FROM user_events"
        ).fetchone()
    finally:
        conn.close()
    user_id, event_type, payload = row
    assert user_id == "zoe"
    assert event_type == EventType.PAPER_OPEN.value
    assert json.loads(payload) == {"sync": True}
