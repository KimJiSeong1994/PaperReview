"""Fire-and-forget emit helper. Centralizes event emission with GC-safe task tracking.

Handles three paths:
  (a) running asyncio loop → create_task, retain reference (fixes F4 regression)
  (b) no running loop but main loop registered → run_coroutine_threadsafe (fixes Risk-B)
  (c) no running loop and no main loop → sync persist only (subscriber fan-out skipped)
"""
from __future__ import annotations

import asyncio
import logging

from src.events.event_bus import get_event_bus
from src.events.event_types import UserEvent

logger = logging.getLogger(__name__)

# Module-level strong reference set so outer tasks scheduled via
# ``asyncio.create_task`` aren't garbage-collected before ``_persist`` runs.
# This closes the F4 race that the EventBus._inflight set would otherwise
# re-open for the *outer* ``bus.publish(event)`` task.
_pending: set[asyncio.Task[None]] = set()


def emit_or_warn(event: UserEvent) -> None:
    """Schedule ``bus.publish(event)`` without awaiting; never raises.

    Parameters
    ----------
    event:
        A fully-validated :class:`UserEvent` to publish.

    Notes
    -----
    Three execution paths (in order):

    (a) **Running asyncio loop** (async endpoint). Uses
        ``loop.create_task`` and retains a strong reference in
        ``_pending`` until completion so the outer publish task cannot
        be garbage-collected before it persists.

    (b) **No running loop, main loop registered** (sync endpoint running
        in the FastAPI threadpool). Uses
        :func:`asyncio.run_coroutine_threadsafe` to schedule the publish
        on the main event loop so subscribers still fan out.

    (c) **Neither available** (pure sync unit test or standalone
        script). Falls back to :meth:`EventBus.persist_only` so the
        event is still written to SQLite; subscriber fan-out is
        silently skipped.
    """
    try:
        bus = get_event_bus()
    except RuntimeError:
        logger.warning(
            "event bus not initialized; dropping %s", event.event_type.value
        )
        return

    # Path (a): inside a running event loop (async endpoint)
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        task = loop.create_task(bus.publish(event))
        _pending.add(task)
        task.add_done_callback(_pending.discard)
        return

    # Path (b): main loop registered (sync endpoint running in threadpool)
    main_loop = getattr(bus, "main_loop", None)
    if main_loop is not None and main_loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(bus.publish(event), main_loop)
            return
        except Exception:
            logger.exception(
                "run_coroutine_threadsafe failed for %s",
                event.event_type.value,
            )
            # fall through to path (c)

    # Path (c): no loop available — persist synchronously, skip fan-out.
    try:
        bus.persist_only(event)
    except Exception:
        logger.exception(
            "sync persist_only failed for %s", event.event_type.value
        )


__all__ = ["emit_or_warn"]
