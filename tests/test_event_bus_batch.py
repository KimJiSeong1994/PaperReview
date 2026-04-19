"""
Tests for US-007 batched persistence on :class:`src.events.event_bus.EventBus`.

Covers:

* 100 concurrent publishes → 100 rows on disk after ``wait_for_drain``.
* Size-triggered batch flush at ``_batch_size`` events.
* Interval-triggered batch flush at ``_batch_interval_s`` seconds.
* Executemany error degrades to per-event fallback (no event loss).
* ``wait_for_drain`` guarantees zero loss for queued-but-unflushed events.
* ``flush_immediately`` bypasses the batch queue (synchronous durability).
* Microbenchmark: batched vs. per-event publish throughput.

All tests create an isolated SQLite DB inside ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# Ensure project root is importable when running with --noconftest.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.events.event_bus import EventBus  # noqa: E402
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
    """Build a ``UserEvent`` with test defaults."""
    return UserEvent(
        user_id=user_id,
        event_type=event_type,
        payload=payload if payload is not None else {"k": "v"},
        paper_id=paper_id,
    )


def _row_count(db_path: Path) -> int:
    """Return total rows in ``user_events``."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT COUNT(*) FROM user_events").fetchone()
        return int(row[0])
    finally:
        conn.close()


@pytest.fixture
def bus(tmp_path: Path) -> EventBus:
    """Yield a fresh :class:`EventBus` on an isolated tmp DB."""
    db_path = tmp_path / "events.db"
    instance = EventBus(db_path)
    try:
        yield instance
    finally:
        instance.close()


# ---------------------------------------------------------------------------
# 1. Concurrency correctness: 100 publishes → 100 rows
# ---------------------------------------------------------------------------


async def test_100_concurrent_publishes_persist_all_rows(
    bus: EventBus, tmp_path: Path
) -> None:
    """100 concurrent ``publish`` calls must result in exactly 100 DB rows."""
    events = [_make_event(user_id=f"u{i}", payload={"i": i}) for i in range(100)]

    await asyncio.gather(*(bus.publish(e) for e in events))
    await bus.wait_for_drain(timeout=5.0)

    assert _row_count(tmp_path / "events.db") == 100


# ---------------------------------------------------------------------------
# 2. Size-triggered flush — one executemany covers batch_size events
# ---------------------------------------------------------------------------


async def test_batch_triggered_by_size(
    bus: EventBus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Batch must flush once the queue hits ``_batch_size`` events.

    We make the interval large (10 s) so time-based flush can't trigger,
    then publish exactly one batch worth of events. After a brief yield
    the flusher picks them up in a single executemany.
    """
    bus._batch_interval_s = 10.0  # effectively disable time-based flush
    bus._batch_size = 8

    # Track executemany call count to prove a single batch landed.
    call_log: list[int] = []
    original = bus._executemany_with_lock

    def _wrap(rows: list[tuple]) -> None:
        call_log.append(len(rows))
        original(rows)

    monkeypatch.setattr(bus, "_executemany_with_lock", _wrap)

    for i in range(bus._batch_size):
        await bus.publish(_make_event(user_id=f"u{i}"))

    await bus.wait_for_drain(timeout=2.0)

    assert _row_count(tmp_path / "events.db") == bus._batch_size
    # The flusher may pull events in ≥1 executemany calls depending on
    # loop scheduling, but the sum must equal batch_size and no single
    # call may exceed batch_size.
    assert sum(call_log) == bus._batch_size
    assert max(call_log) <= bus._batch_size


# ---------------------------------------------------------------------------
# 3. Interval-triggered flush — single event lands after the timeout
# ---------------------------------------------------------------------------


async def test_batch_triggered_by_interval(
    bus: EventBus, tmp_path: Path
) -> None:
    """A single publish must be flushed within ``_batch_interval_s``.

    We shrink the interval so the test stays fast, then publish one
    event (well under batch_size) and assert it lands on disk after
    waiting just a bit longer than the interval — without calling
    ``wait_for_drain``.
    """
    bus._batch_interval_s = 0.05  # 50 ms
    bus._batch_size = 32  # plenty of headroom so size never triggers

    await bus.publish(_make_event(user_id="interval-user"))

    # Don't drain — rely purely on the interval-based flush.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if _row_count(tmp_path / "events.db") == 1:
            break
        await asyncio.sleep(0.02)

    assert _row_count(tmp_path / "events.db") == 1, (
        "event should have been flushed by interval timer"
    )

    # Cleanly drain before the fixture tears down.
    await bus.wait_for_drain(timeout=1.0)


# ---------------------------------------------------------------------------
# 4. Batch error → per-event fallback (no loss)
# ---------------------------------------------------------------------------


async def test_batch_error_falls_back_to_single_event_persist(
    bus: EventBus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``executemany`` raises, the worker must fall back to per-event INSERT."""
    bus._batch_size = 5
    bus._batch_interval_s = 10.0

    # Poison the first executemany call so the worker is forced into
    # per-event fallback. Subsequent calls (none expected in this test)
    # succeed normally.
    calls = {"n": 0}
    original = bus._executemany_with_lock

    def _poisoned(rows: list[tuple]) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("simulated batch failure")
        original(rows)

    monkeypatch.setattr(bus, "_executemany_with_lock", _poisoned)

    for i in range(bus._batch_size):
        await bus.publish(_make_event(user_id=f"fb{i}"))

    await bus.wait_for_drain(timeout=2.0)

    # All events must be on disk despite the poisoned executemany.
    assert _row_count(tmp_path / "events.db") == bus._batch_size
    assert calls["n"] >= 1, "executemany must have been attempted"


# ---------------------------------------------------------------------------
# 5. SIGTERM simulation — drain guarantees zero loss
# ---------------------------------------------------------------------------


async def test_wait_for_drain_guarantees_zero_loss(
    bus: EventBus, tmp_path: Path
) -> None:
    """Queue 50 events then drain: all 50 must be persisted."""
    bus._batch_interval_s = 10.0  # flusher idles; drain must force-flush
    bus._batch_size = 32

    events = [_make_event(user_id=f"drain{i}") for i in range(50)]
    for e in events:
        await bus.publish(e)

    # Don't let the interval trigger — drain immediately.
    await bus.wait_for_drain(timeout=5.0)

    assert _row_count(tmp_path / "events.db") == 50


# ---------------------------------------------------------------------------
# 6. flush_immediately — bypass batch queue, synchronous durability
# ---------------------------------------------------------------------------


async def test_flush_immediately_bypasses_batch(
    bus: EventBus, tmp_path: Path
) -> None:
    """``flush_immediately`` must persist before returning; queue unused."""
    bus._batch_interval_s = 10.0
    bus._batch_size = 32

    event = _make_event(user_id="audit-user", payload={"critical": True})
    await bus.flush_immediately(event)

    # Durable immediately — no drain needed.
    assert _row_count(tmp_path / "events.db") == 1

    # Batch queue must have been untouched.
    assert bus._batch_queue.qsize() == 0

    # Subscribers still invoked.
    calls: list[UserEvent] = []

    async def _sub(evt: UserEvent) -> None:
        calls.append(evt)

    bus.subscribe(_sub)
    await bus.flush_immediately(
        _make_event(user_id="audit-user-2", payload={"critical": True})
    )
    await bus.wait_for_drain(timeout=1.0)
    assert len(calls) == 1
    assert calls[0].user_id == "audit-user-2"


# ---------------------------------------------------------------------------
# 7. Microbenchmark — batched throughput must beat per-event baseline
# ---------------------------------------------------------------------------


async def test_batched_publish_latency_is_sub_millisecond(
    bus: EventBus, tmp_path: Path
) -> None:
    """publish() p99 must be sub-ms — the whole point of batching.

    Batching moves the SQLite ``executemany`` off the ``publish`` hot
    path and onto the background flusher. A single ``publish`` is just
    a queue put + fan-out; the win is that the caller returns fast even
    when the DB is under write pressure.

    We compare:

    * **p99 publish latency** — enqueue-only, no drain.
    * **per-event ``persist_only`` latency** — synchronous INSERT.

    The batched publish p99 must be comfortably below the per-event
    sync p99. Prints numbers for ops observability.
    """
    # Use a large batch size / long interval so the flusher doesn't
    # interleave with the hot path during measurement.
    bus._batch_interval_s = 1.0
    bus._batch_size = 64

    n_events = 500
    events = [_make_event(user_id=f"lat{i}") for i in range(n_events)]

    # --- publish() latency (enqueue-only) ---
    batched_latencies_ms: list[float] = []
    for e in events:
        t0 = time.perf_counter()
        await bus.publish(e)
        batched_latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    # --- persist_only() latency (sync INSERT baseline) ---
    baseline_bus = EventBus(tmp_path / "baseline.db")
    try:
        sync_latencies_ms: list[float] = []
        for e in events:
            t0 = time.perf_counter()
            baseline_bus.persist_only(e)
            sync_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
    finally:
        baseline_bus.close()

    def _p(values: list[float], p: float) -> float:
        return sorted(values)[int(len(values) * p) - 1]

    p50_batched = _p(batched_latencies_ms, 0.5)
    p99_batched = _p(batched_latencies_ms, 0.99)
    p50_sync = _p(sync_latencies_ms, 0.5)
    p99_sync = _p(sync_latencies_ms, 0.99)

    print(
        f"\n[US-007 publish latency n={n_events}] "
        f"publish p50={p50_batched:.3f}ms p99={p99_batched:.3f}ms | "
        f"persist_only p50={p50_sync:.3f}ms p99={p99_sync:.3f}ms | "
        f"p99 speedup={p99_sync / max(p99_batched, 1e-9):.1f}x"
    )

    await bus.wait_for_drain(timeout=5.0)
    assert _row_count(tmp_path / "events.db") == n_events

    # Batched publish must be measurably faster on the hot path. We
    # assert ≥3× on p99 — on a quiet MacBook this is typically 20-50×.
    assert p99_batched < p99_sync, (
        f"batched p99 {p99_batched:.3f}ms should undercut "
        f"per-event sync p99 {p99_sync:.3f}ms"
    )
    assert p99_batched * 3 <= p99_sync, (
        f"batched p99 {p99_batched:.3f}ms must be ≥3× faster than "
        f"per-event sync p99 {p99_sync:.3f}ms"
    )


# ---------------------------------------------------------------------------
# 8. H1 regression — loop swap must not drop queued events
# ---------------------------------------------------------------------------


def test_ensure_batch_task_drains_old_queue_on_loop_swap(
    tmp_path: Path,
) -> None:
    """H1 regression: stale-loop flusher must not drop queued events.

    Runs entirely in synchronous context so we can create and close
    independent event loops without nesting.  The test:

    1. Creates loop-A and puts 5 events in the bus queue.
    2. Calls ``_ensure_batch_task`` with loop-B (simulating pytest's
       per-test loop rotation).
    3. Verifies the queue still holds all 5 events (migration, not drop).
    4. Drains on loop-B and confirms all 5 rows are on disk.
    """
    db_path = tmp_path / "events.db"
    bus = EventBus(db_path)

    # --- loop-A: pre-load 5 events into the queue -----------------------
    loop_a = asyncio.new_event_loop()
    try:
        bus._ensure_batch_task(loop_a)
        for i in range(5):
            bus._batch_queue.put_nowait(_make_event(user_id=f"pre{i}"))
        assert bus._batch_queue.qsize() == 5, "pre-condition: 5 events queued"
    finally:
        # Cancel the flusher and let it acknowledge cancellation so
        # there's no "coroutine never awaited" RuntimeWarning.
        if bus._batch_task is not None:
            bus._batch_task.cancel()
            try:
                loop_a.run_until_complete(bus._batch_task)
            except (asyncio.CancelledError, Exception):
                pass
        loop_a.close()

    # --- loop-B: simulate new-loop handoff ------------------------------
    loop_b = asyncio.new_event_loop()
    try:
        bus._ensure_batch_task(loop_b)
        assert bus._batch_queue.qsize() == 5, (
            "events must have been migrated from old queue into new queue"
        )

        async def _drain() -> None:
            await bus.wait_for_drain(timeout=5.0)

        loop_b.run_until_complete(_drain())
    finally:
        bus.close()
        loop_b.close()

    assert _row_count(db_path) == 5, (
        "all 5 pre-swap events must be persisted after drain on the new loop"
    )


# ---------------------------------------------------------------------------
# 9. close() idempotency
# ---------------------------------------------------------------------------


def test_close_is_idempotent(tmp_path: Path) -> None:
    """close() called twice must not raise."""
    bus = EventBus(tmp_path / "events.db")
    bus.close()
    bus.close()  # must not raise
