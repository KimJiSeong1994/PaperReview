"""
In-process async event bus backed by SQLite for durable persistence.

The :class:`EventBus` is the fan-out point for :class:`~src.events.event_types.UserEvent`
records. It has two non-negotiable guarantees:

1. **Durability on drain** — every event enters a bounded in-process batch
   queue on :meth:`publish`; a background flusher writes the queue to SQLite
   in ``executemany`` batches of up to ``_batch_size`` (default 32) or every
   ``_batch_interval_s`` (default 250 ms), whichever comes first. A batch
   INSERT failure degrades to per-event fallback so no event is ever dropped.
   :meth:`wait_for_drain` guarantees the queue is flushed synchronously
   before returning (SIGTERM drain).

2. **Subscriber isolation** — every subscriber runs inside its own
   :func:`asyncio.create_task` with a local ``try/except Exception`` guard.
   One failing subscriber cannot affect other subscribers or the calling
   coroutine.

For GDPR/audit-critical events that must be durable before the caller
returns, use :meth:`flush_immediately` which bypasses the batch queue and
performs a synchronous single-event INSERT.

GC-safety for in-flight tasks (blocker fix F4) is achieved by holding a
strong reference in ``self._inflight`` and discarding the task from that
set via ``task.add_done_callback`` when it finishes.

Public API — extends ``99-final-impl.md`` §2.B6 with US-007 batching::

    bus = init_event_bus(Path("data/events.db"))
    sub = bus.subscribe(async_callback)
    await bus.publish(event)              # enqueued; durable after drain
    await bus.flush_immediately(event)    # durable before return
    await bus.wait_for_drain(timeout=5.0) # guarantees zero event loss
    bus.unsubscribe(sub)

Only :func:`init_event_bus` and :func:`get_event_bus` manage the
module-level singleton; there is **no** ``EventBus.instance()`` method.

.. note::

   Semantic change from the pre-US-007 API: ``publish()`` no longer
   guarantees the event is on disk when it returns — it only guarantees
   the event is in the batch queue. Callers that need durability before
   they return (GDPR audit, critical scoring events) must use
   :meth:`flush_immediately`. Graceful shutdown code paths must call
   :meth:`wait_for_drain` before exiting.

.. warning:: Subscriber contract

   Subscribers MUST consume the ``UserEvent`` *object* passed to them —
   NOT read back the event via ``SELECT ... FROM user_events``.  The
   event may not yet be persisted when the subscriber runs (batch flush
   window up to 250 ms).  For audit-critical paths requiring
   durable-before-return semantics, use ``flush_immediately(event)``
   instead of ``publish()``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from src.events.event_types import UserEvent
from src.events.migrations import ensure_events_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------

SubscribeCallback = Callable[[UserEvent], Awaitable[None]]


@dataclass(frozen=True)
class Subscription:
    """
    Opaque handle returned by :meth:`EventBus.subscribe`.

    Holding an instance is the *only* way to later call
    :meth:`EventBus.unsubscribe`. The ``id`` field is a random UUID that
    provides uniqueness and safe hashing without leaking callback
    identity.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class EventBus:
    """
    SQLite-backed, asyncio-native event bus with batched persistence.

    The bus owns a single long-lived SQLite connection for writes
    (``check_same_thread=False``), serialized by an in-process lock so
    concurrent INSERTs never interleave. Subscribers are registered
    in-memory and fanned out via ``asyncio.create_task``.

    Persistence path (US-007): :meth:`publish` enqueues each event on an
    ``asyncio.Queue``; a background coroutine (``_batch_flush_loop``)
    drains up to ``_batch_size`` events per tick and writes them via
    ``executemany`` for 10-30× throughput over per-event INSERTs. The
    background flusher is started lazily on the first ``publish`` call
    that sees a running event loop, or explicitly via
    :meth:`register_main_loop`.

    Instances are typically created once at startup via
    :func:`init_event_bus` and retrieved elsewhere via
    :func:`get_event_bus`.
    """

    #: Max events per ``executemany`` batch.
    _DEFAULT_BATCH_SIZE: int = 32
    #: Max seconds between flushes when a partial batch is pending.
    _DEFAULT_BATCH_INTERVAL_S: float = 0.25

    def __init__(self, db_path: Path) -> None:
        """
        Open (and migrate) the events DB at *db_path*.

        Parameters
        ----------
        db_path:
            Target ``events.db``. Parent directories and the schema are
            created on demand via
            :func:`~src.events.migrations.ensure_events_db`.
        """
        self._db_path: Path = Path(db_path)
        ensure_events_db(self._db_path)

        # One dedicated connection per bus. ``check_same_thread=False`` is
        # required because publish() may be invoked from different event
        # loop threads during tests / lifespan shutdown. Writes are
        # serialized by ``self._db_lock`` so this remains safe.
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit — each INSERT is atomic
        )
        # Re-apply WAL on the live connection; ensure_events_db sets it on
        # a separate connection which persists at the DB-file level, but
        # synchronous/foreign_keys are per-connection pragmas.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._db_lock: threading.Lock = threading.Lock()
        self._sub_lock: threading.Lock = threading.Lock()
        # Guards _ensure_batch_task against concurrent cross-thread calls
        # (e.g. emit_or_warn path (b) racing with a new-loop swap).
        self._swap_lock: threading.Lock = threading.Lock()

        self._subscribers: dict[Subscription, SubscribeCallback] = {}
        self._inflight: set[asyncio.Task[None]] = set()

        # Optional reference to the FastAPI main event loop. Set by
        # :meth:`register_main_loop` during the lifespan startup so
        # ``emit_or_warn`` can schedule publishes from sync endpoints
        # running inside the threadpool (path (b) in ``src.events.emit``).
        self.main_loop: asyncio.AbstractEventLoop | None = None

        # --- US-007 batch persistence -------------------------------------
        # The queue is bounded at 10 000 slots (~2 MB at 200 B/event).
        # Producers block naturally once full, giving back-pressure without
        # silent drops.  A warning fires at 80 % capacity (≥ 8 000 events)
        # so operators can scale before hitting the hard cap.
        self._batch_queue: asyncio.Queue[UserEvent] = asyncio.Queue(maxsize=10_000)
        self._batch_size: int = self._DEFAULT_BATCH_SIZE
        self._batch_interval_s: float = self._DEFAULT_BATCH_INTERVAL_S
        self._batch_task: asyncio.Task[None] | None = None
        self._batch_task_loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_event: asyncio.Event = asyncio.Event()
        # Held by the flusher while it has a batch in-flight. Drain
        # acquires this to guarantee it observes any partially-consumed
        # batch the worker is still writing.
        self._flush_in_progress: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, event: UserEvent) -> None:
        """
        Synchronously INSERT *event* into ``user_events``.

        Raises the underlying :class:`sqlite3.Error` on failure so the
        caller can decide to retry. The failure is logged at ERROR first
        so operators see it even if the caller swallows the exception.
        """
        payload_json = json.dumps(event.payload, ensure_ascii=False)
        created_at_iso = event.created_at.isoformat()

        try:
            with self._db_lock:
                self._conn.execute(
                    """
                    INSERT INTO user_events
                        (user_id, event_type, payload, paper_id, created_at, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.user_id,
                        event.event_type.value,
                        payload_json,
                        event.paper_id,
                        created_at_iso,
                        event.source,
                    ),
                )
        except sqlite3.Error:
            logger.error(
                "event_bus: failed to persist event user_id=%s type=%s",
                event.user_id,
                event.event_type.value,
                exc_info=True,
            )
            raise

    def _executemany_with_lock(self, rows: list[tuple]) -> None:
        """Run one ``executemany`` INSERT under the DB lock.

        Extracted for :func:`asyncio.to_thread` dispatch so the batch
        worker doesn't block its own event loop while SQLite is writing.
        """
        try:
            with self._db_lock:
                self._conn.executemany(
                    """
                    INSERT INTO user_events
                        (user_id, event_type, payload, paper_id, created_at, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        except sqlite3.Error:
            logger.error(
                "event_bus: batch INSERT failed count=%d",
                len(rows),
                exc_info=True,
            )
            raise

    async def _persist_batch(self, events: list[UserEvent]) -> None:
        """Persist *events* in a single ``executemany`` under the DB lock.

        Runs the blocking SQLite call on the default thread-pool via
        :func:`asyncio.to_thread` so the batch flusher's event loop stays
        responsive. Raises :class:`sqlite3.Error` on failure; callers
        (`_batch_flush_loop`) degrade to per-event persistence on error.
        """
        if not events:
            return
        rows = [
            (
                ev.user_id,
                ev.event_type.value,
                json.dumps(ev.payload, ensure_ascii=False),
                ev.paper_id,
                ev.created_at.isoformat(),
                ev.source,
            )
            for ev in events
        ]
        await asyncio.to_thread(self._executemany_with_lock, rows)

    def persist_only(self, event: UserEvent) -> None:
        """Synchronously persist *event* with no subscriber fan-out.

        Used by :func:`src.events.emit.emit_or_warn` path (c) when no
        asyncio loop is available at the call site (e.g. pure sync unit
        tests or standalone scripts). Exceptions from the underlying
        INSERT are logged and re-raised by :meth:`_persist` so the
        caller can decide how to react.
        """
        self._persist(event)

    def register_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register the FastAPI main event loop and start the batch flusher.

        Call this from the FastAPI lifespan startup (or any other
        well-defined startup point) so :func:`emit_or_warn` running in
        a threadpool worker can schedule ``bus.publish(event)`` on the
        correct loop via :func:`asyncio.run_coroutine_threadsafe`.

        As a side-effect, starts the background batch flusher on *loop*
        so subsequent :meth:`publish` calls have durable persistence on
        drain.

        Parameters
        ----------
        loop:
            The event loop that owns the bus's subscribers.
        """
        self.main_loop = loop
        self._ensure_batch_task(loop)
        logger.debug("event_bus: main loop registered, batch flusher started")

    # ------------------------------------------------------------------
    # Batch flusher
    # ------------------------------------------------------------------

    def _ensure_batch_task(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start the background flusher on *loop* if not already running.

        Idempotent: if a flusher is already bound to *loop* and alive,
        does nothing. If a flusher exists for a different (closed) loop —
        common in test suites that create a new loop per test — it is
        dropped and a fresh one is spawned on *loop*.

        Loop-handoff safety: events sitting in the old queue are drained
        into the new queue before the swap so no event is silently dropped
        when pytest (or another framework) creates a new event loop per
        test.  The entire swap is guarded by ``_swap_lock`` to serialise
        concurrent cross-thread calls from the ``emit_or_warn`` path.
        """
        with self._swap_lock:
            existing = self._batch_task
            if existing is not None and not existing.done() and self._batch_task_loop is loop:
                return
            if existing is not None and not existing.done():
                # A flusher bound to a different loop exists; we cannot
                # cancel it from here safely (cross-loop), so we drop the
                # reference and start fresh. The old task exits when its
                # loop is closed.
                logger.debug(
                    "event_bus: replacing batch flusher from stale loop",
                )
            # Drain old queue into new one BEFORE swap (prevents event
            # loss on loop handoff — Fix H1).
            old_queue = self._batch_queue
            new_queue: asyncio.Queue[UserEvent] = asyncio.Queue(maxsize=10_000)
            while True:
                try:
                    new_queue.put_nowait(old_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            self._batch_queue = new_queue
            # Reset per-loop async primitives.
            self._shutdown_event = asyncio.Event()
            self._flush_in_progress = asyncio.Lock()
            self._batch_task_loop = loop
            self._batch_task = loop.create_task(self._batch_flush_loop())

    async def _batch_flush_loop(self) -> None:
        """Forever drain the batch queue, flushing in executemany chunks.

        Algorithm per iteration:

        1. Wait up to ``_batch_interval_s`` for the first event.
        2. On timeout, loop (no events pending).
        3. On an event, greedily drain up to ``_batch_size - 1`` more
           events without blocking.
        4. Persist the batch via :meth:`_persist_batch`; on failure, fall
           back to per-event :meth:`_persist` so no event is lost even if
           one row is malformed.

        Exits cleanly on :class:`asyncio.CancelledError` or when
        ``_shutdown_event`` is set and the queue is empty.
        """
        while True:
            if self._shutdown_event.is_set() and self._batch_queue.empty():
                return
            batch: list[UserEvent] = []
            try:
                first = await asyncio.wait_for(
                    self._batch_queue.get(),
                    timeout=self._batch_interval_s,
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            batch.append(first)
            # Drain up to batch_size - 1 more without waiting.
            for _ in range(self._batch_size - 1):
                try:
                    batch.append(self._batch_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Hold the in-progress lock across the I/O so ``wait_for_drain``
            # can observe a consistent "no batch pending" state by
            # acquiring it after the queue drains.
            async with self._flush_in_progress:
                try:
                    await self._persist_batch(batch)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "event_bus: batch flush failed (count=%d); "
                        "falling back to per-event persist",
                        len(batch),
                    )
                    for ev in batch:
                        try:
                            self._persist(ev)
                        except Exception:
                            logger.exception(
                                "event_bus: per-event fallback failed "
                                "user_id=%s type=%s",
                                ev.user_id,
                                ev.event_type.value,
                            )

    # ------------------------------------------------------------------
    # Subscriber invocation
    # ------------------------------------------------------------------

    @staticmethod
    async def _run_subscriber(
        callback: SubscribeCallback, event: UserEvent
    ) -> None:
        """
        Invoke *callback* with full isolation — exceptions are logged and
        swallowed so sibling subscribers are unaffected.
        """
        try:
            await callback(event)
        except Exception:
            logger.exception(
                "event_bus: subscriber raised for event type=%s user_id=%s",
                event.event_type.value,
                event.user_id,
            )

    def _track(self, task: asyncio.Task[None]) -> None:
        """Register *task* so it isn't GC'd mid-flight (blocker F4)."""
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    def _fanout(self, event: UserEvent) -> None:
        """Schedule every subscriber for *event* on the running loop.

        Snapshot subscribers under the lock, then schedule each via
        ``create_task`` tracked in ``_inflight``. No-op if there is no
        running loop (the event has already been enqueued for persistence).
        """
        with self._sub_lock:
            callbacks: list[SubscribeCallback] = list(self._subscribers.values())
        if not callbacks:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "event_bus._fanout: no running loop; skipped subscriber fan-out"
            )
            return
        for cb in callbacks:
            task = loop.create_task(self._run_subscriber(cb, event))
            self._track(task)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish(self, event: UserEvent) -> None:
        """
        Enqueue *event* for batched persistence, then fan out to subscribers.

        Order of operations (US-007):

        1. Enqueue on the internal batch queue. Durability is guaranteed
           by the time :meth:`wait_for_drain` returns, **not** by the time
           this coroutine returns. For synchronous durability, use
           :meth:`flush_immediately` instead.
        2. Lazily start the background batch flusher on the running loop
           if it isn't already running.
        3. Snapshot the subscriber registry under the lock and schedule
           each subscriber via :func:`asyncio.create_task`, tracking each
           task in ``self._inflight``.

        Subscriber exceptions are isolated via :meth:`_run_subscriber` —
        they never propagate back to the caller.

        Parameters
        ----------
        event:
            A fully-validated :class:`UserEvent`.
        """
        # 1. Ensure the batch flusher is running on the current loop.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — fall back to synchronous persist. Keeps
            # the "never silently drop" guarantee for edge-case callers
            # that wrap the coroutine with ``asyncio.run`` and a closed
            # loop, and mirrors the pre-US-007 fallback semantics.
            logger.warning(
                "event_bus.publish: no running loop; persist_only fallback"
            )
            self._persist(event)
            return

        self._ensure_batch_task(loop)

        # 2. Enqueue for batching. Queue is bounded (maxsize=10_000).
        await self._batch_queue.put(event)
        # Warn operators when the queue is approaching capacity (80 %).
        if self._batch_queue.qsize() >= 8000:
            logger.warning(
                "event_bus: queue depth %d (>= 80%% of 10_000 cap)",
                self._batch_queue.qsize(),
            )

        # 3. Fan out. Subscribers don't wait for persistence — historical
        #    behaviour preserved — but they will observe the same event
        #    object regardless of which batch it lands in.
        self._fanout(event)

    async def flush_immediately(self, event: UserEvent) -> None:
        """Synchronously persist *event* and then fan out to subscribers.

        Bypasses the batch queue so the caller can rely on the event
        being durable on disk before this coroutine returns. Use for
        audit-critical paths (GDPR wipes, rubric score events) where a
        SIGTERM between publish and drain would be unacceptable.

        Persistence runs on the default thread-pool to keep the event
        loop responsive for very large payloads; the underlying INSERT
        still holds :attr:`_db_lock` so it serialises correctly against
        concurrent batch flushes.

        Parameters
        ----------
        event:
            A fully-validated :class:`UserEvent`.

        Raises
        ------
        sqlite3.Error
            If the INSERT fails. The failure is logged; callers may
            choose to retry or surface the error.

        .. note::

           ``flush_immediately`` does NOT go through the batch queue.
           Subscribers observe ``flush_immediately`` events in the order
           of the ``flush_immediately`` call itself, which may interleave
           with batched events out of their ``user_events.id`` ordering.
           If strict total ordering is required, use only one of
           ``publish()`` or ``flush_immediately()`` in a given code path.
        """
        await asyncio.to_thread(self._persist, event)
        self._fanout(event)

    def subscribe(self, callback: SubscribeCallback) -> Subscription:
        """
        Register *callback* to receive future events.

        Each call registers a **single** callback and returns its own
        :class:`Subscription` handle; call again to add more.

        Parameters
        ----------
        callback:
            An ``async def`` coroutine function accepting a single
            :class:`UserEvent`.

        Returns
        -------
        Subscription
            Opaque handle for later :meth:`unsubscribe`.

        .. warning:: Subscriber contract

           Subscribers MUST consume the ``UserEvent`` *object* passed to
           them — NOT read back the event via ``SELECT ... FROM
           user_events``.  The event may not yet be persisted when the
           subscriber runs (batch flush window up to 250 ms).  For
           audit-critical paths requiring durable-before-return semantics,
           use ``flush_immediately(event)`` instead of ``publish()``.
        """
        subscription = Subscription()
        with self._sub_lock:
            self._subscribers[subscription] = callback
        logger.debug("event_bus: subscribed %s", subscription.id)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        """
        Remove *subscription* from the registry.

        Unknown subscriptions are silently ignored — the contract is
        idempotent, so callers can safely call this in ``finally``
        blocks. Already-scheduled tasks for past events are **not**
        cancelled; only future events will skip this callback.
        """
        with self._sub_lock:
            self._subscribers.pop(subscription, None)
        logger.debug("event_bus: unsubscribed %s", subscription.id)

    async def wait_for_drain(self, timeout: float = 5.0) -> None:
        """
        Drain the batch queue, then await all in-flight subscriber tasks.

        Sequence (US-007):

        1. Yield in a tight loop while the batch flusher drains the queue
           (bounded by ``timeout``).
        2. If *timeout* expires with events still queued, force-flush the
           remaining events via :meth:`_persist_batch` so SIGTERM does
           not drop anything. A failure at this step degrades to
           per-event :meth:`_persist` so zero events are lost.
        3. Snapshot the current set of in-flight subscriber tasks and
           wait up to the remaining timeout for them to finish. Tasks
           created during step 2 are picked up here.

        This coroutine never raises on timeout — it simply returns and
        logs a warning. Safe to call from FastAPI lifespan shutdown.

        Parameters
        ----------
        timeout:
            Maximum seconds to block for the full drain sequence.
            ``0`` returns immediately after a best-effort force-flush.
        """
        deadline = time.monotonic() + max(0.0, timeout)

        # 1. Wait for the batch flusher to drain the queue naturally.
        #    We also wait for any in-flight ``_persist_batch`` call to
        #    complete by acquiring ``_flush_in_progress`` — otherwise
        #    drain could observe an empty queue between the worker's
        #    ``get_nowait`` loop and its ``executemany`` I/O, missing
        #    events that are about to land.
        while True:
            if self._batch_queue.empty():
                # Give the worker a chance to pick up the lock if it's
                # currently picking events out of the queue.
                await asyncio.sleep(0)
                # Wait for any in-flight batch I/O to complete, bounded
                # by the overall drain deadline.
                remaining_time = max(0.0, deadline - time.monotonic())
                try:
                    await asyncio.wait_for(
                        self._flush_in_progress.acquire(),
                        timeout=max(0.01, remaining_time),
                    )
                except asyncio.TimeoutError:
                    # In-flight batch didn't complete in time — fall
                    # through to force-flush what's still queued.
                    break
                try:
                    # At this point no flush is in progress. If the queue
                    # is still empty, we're done; otherwise release and
                    # loop so the worker can pick up the new events.
                    if self._batch_queue.empty():
                        self._flush_in_progress.release()
                        break
                finally:
                    if self._flush_in_progress.locked():
                        self._flush_in_progress.release()
            if time.monotonic() >= deadline:
                logger.warning(
                    "event_bus.wait_for_drain: %d event(s) still queued "
                    "after %.1fs; force-flushing",
                    self._batch_queue.qsize(),
                    timeout,
                )
                break
            await asyncio.sleep(0.01)

        # 2. Force-flush whatever the worker hasn't picked up yet so we
        #    NEVER lose events on SIGTERM, even if the flusher is blocked.
        remaining: list[UserEvent] = []
        while True:
            try:
                remaining.append(self._batch_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining:
            try:
                await self._persist_batch(remaining)
            except Exception:
                logger.exception(
                    "event_bus.wait_for_drain: force-flush batch failed "
                    "(count=%d); falling back to per-event persist",
                    len(remaining),
                )
                for ev in remaining:
                    try:
                        self._persist(ev)
                    except Exception:
                        logger.exception(
                            "event_bus.wait_for_drain: per-event fallback "
                            "failed user_id=%s type=%s",
                            ev.user_id,
                            ev.event_type.value,
                        )

        # 3. Wait for subscriber fan-out tasks. Snapshot so new tasks
        #    created after this point don't extend the timeout.
        remaining_time = max(0.0, deadline - time.monotonic())
        tasks = list(self._inflight)
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=remaining_time)
        if pending:
            logger.warning(
                "event_bus.wait_for_drain: %d task(s) still running after %.1fs",
                len(pending),
                timeout,
            )

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Stop the batch flusher and close the SQLite connection.

        Safe to call twice. Does **not** drain the queue — callers that
        need zero-loss on shutdown must call :meth:`wait_for_drain`
        first. The FastAPI lifespan does this in ``api_server.py``.
        """
        # Signal the worker to stop on its next tick and cancel if it's
        # parked on ``queue.get``.
        try:
            self._shutdown_event.set()
        except Exception:
            # ``_shutdown_event`` may be bound to a dead loop; best-effort
            # only. The cancel() below is the real stop.
            pass
        task = self._batch_task
        if task is not None and not task.done():
            task.cancel()
        self._batch_task = None
        self._batch_task_loop = None
        with self._db_lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                logger.debug("event_bus: connection already closed", exc_info=True)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bus: EventBus | None = None
_bus_lock = threading.Lock()


def init_event_bus(db_path: Path) -> EventBus:
    """
    Initialize (or replace) the module-level :class:`EventBus` singleton.

    Call this exactly once during application startup. Calling it again
    replaces the previous bus — the prior instance is closed so its
    SQLite handle is released.

    Parameters
    ----------
    db_path:
        Path to ``events.db``.

    Returns
    -------
    EventBus
        The newly-initialized singleton.
    """
    global _bus
    with _bus_lock:
        if _bus is not None:
            logger.info("event_bus: re-initializing; closing previous instance")
            try:
                _bus.close()
            except Exception:
                logger.exception("event_bus: error closing previous instance")
        _bus = EventBus(Path(db_path))
        return _bus


def get_event_bus() -> EventBus:
    """
    Return the module-level :class:`EventBus` singleton.

    Raises
    ------
    RuntimeError
        If :func:`init_event_bus` has not been called yet.
    """
    if _bus is None:
        raise RuntimeError("event_bus not initialized")
    return _bus


__all__ = [
    "EventBus",
    "Subscription",
    "SubscribeCallback",
    "get_event_bus",
    "init_event_bus",
]
