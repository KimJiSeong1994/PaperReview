"""
In-process async event bus backed by SQLite for durable persistence.

The :class:`EventBus` is the fan-out point for :class:`~src.events.event_types.UserEvent`
records. It has two non-negotiable guarantees:

1. **Persist-before-fan-out** — each event is synchronously written to the
   ``user_events`` table *before* any subscriber is scheduled. A subscriber
   crash can therefore never drop an event (the event is already on disk).

2. **Subscriber isolation** — every subscriber runs inside its own
   :func:`asyncio.create_task` with a local ``try/except Exception`` guard.
   One failing subscriber cannot affect other subscribers or the calling
   coroutine.

GC-safety for in-flight tasks (blocker fix F4) is achieved by holding a
strong reference in ``self._inflight`` and discarding the task from that
set via ``task.add_done_callback`` when it finishes.

Public API — exactly as specified in ``99-final-impl.md`` §2.B6::

    bus = init_event_bus(Path("data/events.db"))
    sub = bus.subscribe(async_callback)
    await bus.publish(event)
    await bus.wait_for_drain(timeout=5.0)
    bus.unsubscribe(sub)

Only :func:`init_event_bus` and :func:`get_event_bus` manage the
module-level singleton; there is **no** ``EventBus.instance()`` method.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
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
    SQLite-backed, asyncio-native event bus.

    The bus owns a single long-lived SQLite connection for writes
    (``check_same_thread=False``), serialized by an in-process lock so
    concurrent ``publish`` calls never interleave INSERTs. Subscribers are
    registered in-memory and fanned out via ``asyncio.create_task``.

    Instances are typically created once at startup via
    :func:`init_event_bus` and retrieved elsewhere via
    :func:`get_event_bus`.
    """

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

        self._subscribers: dict[Subscription, SubscribeCallback] = {}
        self._inflight: set[asyncio.Task[None]] = set()

        # Optional reference to the FastAPI main event loop. Set by
        # :meth:`register_main_loop` during the lifespan startup so
        # ``emit_or_warn`` can schedule publishes from sync endpoints
        # running inside the threadpool (path (b) in ``src.events.emit``).
        self.main_loop: asyncio.AbstractEventLoop | None = None

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
        """Register the FastAPI main event loop for cross-thread emits.

        Call this from the FastAPI lifespan startup (or any other
        well-defined startup point) so :func:`emit_or_warn` running in
        a threadpool worker can schedule ``bus.publish(event)`` on the
        correct loop via :func:`asyncio.run_coroutine_threadsafe`.

        Parameters
        ----------
        loop:
            The event loop that owns the bus's subscribers.
        """
        self.main_loop = loop
        logger.debug("event_bus: main loop registered")

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish(self, event: UserEvent) -> None:
        """
        Persist *event*, then fan out to every subscriber.

        Order of operations:

        1. Synchronous INSERT into ``user_events`` (raises on DB failure
           so the caller can retry; the event is **not** lost silently).
        2. Snapshot the subscriber registry under the lock so
           subscribe/unsubscribe during fan-out cannot mutate it.
        3. Schedule each subscriber via :func:`asyncio.create_task`,
           tracking the task in ``self._inflight``.

        Subscriber exceptions are isolated via :meth:`_run_subscriber` —
        they never propagate back to the caller.

        Parameters
        ----------
        event:
            A fully-validated :class:`UserEvent`.
        """
        # 1. Durable write first.
        self._persist(event)

        # 2. Snapshot subscribers to avoid holding the lock across create_task.
        with self._sub_lock:
            callbacks: list[SubscribeCallback] = list(self._subscribers.values())

        # 3. Fan out. If we're somehow not inside a running loop, skip
        #    fan-out rather than crash — the event is already persisted.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "event_bus.publish: no running loop; persisted but skipped fan-out"
            )
            return

        for cb in callbacks:
            task = loop.create_task(self._run_subscriber(cb, event))
            self._track(task)

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
        Wait up to *timeout* seconds for all in-flight subscriber tasks.

        This never raises on timeout — it simply returns, leaving any
        still-running tasks to finish in the background. Useful for
        tests and for graceful shutdown before process exit.

        Parameters
        ----------
        timeout:
            Maximum seconds to block; ``0`` returns immediately.
        """
        # Snapshot so new tasks created during the wait don't extend it.
        tasks = list(self._inflight)
        if not tasks:
            return

        done, pending = await asyncio.wait(tasks, timeout=timeout)
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
        """Close the underlying SQLite connection. Safe to call twice."""
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
