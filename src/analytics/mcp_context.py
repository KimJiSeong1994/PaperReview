"""Request-local MCP claims and server-authenticated identity.

The User-Agent identifies a claimed adapter, never a verified MCP transport.
Only authentication dependencies may attach account identity. No request body,
query string, credential, or raw dynamic URL is retained.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
import logging
import re
import time
from typing import Any
from uuid import UUID

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)
_context: ContextVar[dict[str, Any] | None] = ContextVar("mcp_usage_context", default=None)
_UA = re.compile(r"^jiphyeonjeon-mcp/([0-9][A-Za-z0-9.+-]{0,31})(?:\s|$)")
_pending_records: set[asyncio.Task[Any]] = set()


async def _write_safely(**fields: Any) -> bool:
    from .mcp_usage import record_event_async
    try:
        return await record_event_async(**fields)
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise  # Preserve genuine caller cancellation, not writer failures.
        logger.warning("MCP measurement writer was cancelled")
    except Exception:
        logger.warning("MCP measurement unavailable")
    return False


def _schedule_record(**fields: Any) -> None:
    if len(_pending_records) >= 128:
        logger.warning("MCP request measurement capacity exhausted")
        return
    task = asyncio.create_task(_write_safely(**fields))
    _pending_records.add(task)
    task.add_done_callback(_pending_records.discard)


async def drain_measurements() -> None:
    """Flush bounded response measurements on graceful shutdown."""
    tasks = [task for task in _pending_records if task.get_loop() is asyncio.get_running_loop()]
    if tasks:
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=1.5)
        except TimeoutError:
            logger.warning("MCP measurement shutdown drain timed out")


def is_mcp_request(headers: Any) -> bool:
    return bool(_UA.match(headers.get("user-agent", "")))


def capture_context() -> dict[str, Any] | None:
    context = _context.get()
    return dict(context) if context is not None else None


def identify_actor(username: str, role: str | None) -> None:
    context = _context.get()
    if context is not None:
        context["actor_id"] = username
        context["actor_role"] = "admin" if role == "admin" else "user"


def _claims(scope: Scope) -> dict[str, Any] | None:
    headers = {key.decode("latin-1").lower(): value.decode("latin-1")
               for key, value in scope.get("headers", [])}
    matched = _UA.match(headers.get("user-agent", ""))
    if matched is None:
        return None
    invocation_id = None
    try:
        invocation_id = str(UUID(headers.get("x-jiphyeonjeon-invocation-id", "")))
    except (ValueError, AttributeError):
        pass
    return {
        "source": "ua_claim",
        "adapter_version": matched.group(1),
        "invocation_id": invocation_id,
        "client_name": headers.get("x-jiphyeonjeon-client-name"),
        "client_version": headers.get("x-jiphyeonjeon-client-version"),
    }


async def record_job_started(name: str, job_id: str) -> tuple[dict[str, Any], float] | None:
    context = capture_context()
    if context is None:
        return None
    context["source"] = "server_observed"
    started = time.perf_counter()
    await _write_safely(**context, kind="job", name=name, status="started", job_id=job_id)
    return context, started


def record_job_finished(
    measurement: tuple[dict[str, Any], float] | None,
    name: str,
    job_id: str,
    status: str,
) -> None:
    """Used in worker threads; the bounded ledger writer is fail-open."""
    if measurement is None:
        return
    from .mcp_usage import record_event

    context, started = measurement
    try:
        record_event(**context, kind="job", name=name, job_id=job_id, status=status,
                     duration_ms=max(0, (time.perf_counter() - started) * 1000))
    except (Exception, asyncio.CancelledError):
        logger.warning("MCP job measurement unavailable")


async def record_job_finished_async(
    measurement: tuple[dict[str, Any], float] | None,
    name: str,
    job_id: str,
    status: str,
) -> None:
    if measurement is not None:
        context, started = measurement
        await _write_safely(**context, kind="job", name=name, job_id=job_id, status=status,
                            duration_ms=max(0, (time.perf_counter() - started) * 1000))


class McpUsageMiddleware:
    """Record the response boundary, before long-running background tasks.

    Contexts are isolated per request and copied into background work. Probe,
    ingestion, and admin traffic never count as business HTTP requests.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        context = _claims(scope)
        token = _context.set(context)
        path = scope.get("path", "")
        measure = context is not None and path.startswith("/api/") and not (
            path.startswith(("/api/admin", "/api/mcp/telemetry", "/api/analytics"))
            or path in {"/api/version", "/api/auth/verify"}
        )
        started = time.perf_counter()
        status = 500
        recorded = False
        interrupted = False

        def record_response() -> None:
            nonlocal recorded
            if not measure or recorded:
                return
            recorded = True
            route = getattr(scope.get("route"), "path", "(unmatched)")
            _schedule_record(
                **(capture_context() or {}), kind="request",
                name=f"{scope.get('method', 'GET')} {route}",
                status="succeeded" if 200 <= status < 400 and not interrupted else "failed",
                http_status=status, duration_ms=max(0, (time.perf_counter() - started) * 1000),
            )

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                record_response()

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException:
            interrupted = True
            raise
        finally:
            try:
                record_response()
            finally:
                _context.reset(token)
