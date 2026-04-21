"""Regression test: TimingSecurityHeadersMiddleware must not buffer chunks.

Guards against a re-introduction of ``@app.middleware("http")`` (which wraps
Starlette's ``BaseHTTPMiddleware`` and buffers small chunks through an anyio
memory stream queue). In production this broke SSE keepalives — nginx's
``proxy_read_timeout`` fired before ``: keepalive`` comment chunks could reach
it, and the FE surfaced the cryptic "스트림이 중단되었습니다" error.

Strategy: drive the middleware at the raw ASGI layer with a fake downstream
app that emits timestamped chunks, and record when each chunk reaches the
outer ``send``. A pure ASGI middleware forwards each chunk immediately (delta
near zero); a buffering middleware holds them until the downstream generator
completes.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from middleware import TimingSecurityHeadersMiddleware


_CHUNK_INTERVAL_S = 0.2
_NUM_CHUNKS = 5
# 500 ms tolerance: easily distinguishes immediate forwarding from the buffered
# case (where all chunks would arrive at ~_NUM_CHUNKS * _CHUNK_INTERVAL_S = 1.0s)
# while tolerating scheduler jitter on shared CI runners.
_MAX_ALLOWED_LAG_S = 0.5


async def _downstream_app(scope, receive, send):
    """Emit a start message then N body chunks spaced by _CHUNK_INTERVAL_S."""
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/event-stream")],
    })
    for i in range(_NUM_CHUNKS):
        await send({
            "type": "http.response.body",
            "body": f"chunk-{i}\n".encode(),
            "more_body": i < _NUM_CHUNKS - 1,
        })
        if i < _NUM_CHUNKS - 1:
            await asyncio.sleep(_CHUNK_INTERVAL_S)


def _build_scope(method: str = "GET", path: str = "/test") -> dict:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
        "http_version": "1.1",
    }


@pytest.mark.asyncio
async def test_middleware_forwards_chunks_immediately() -> None:
    """Each downstream chunk must reach outer send() within _MAX_ALLOWED_LAG_S.

    This asserts true ASGI pass-through semantics — the middleware must not
    queue chunks through an intermediate buffer.
    """
    middleware = TimingSecurityHeadersMiddleware(_downstream_app)

    send_times: list[tuple[str, float]] = []
    t_start = time.perf_counter()

    async def recording_send(message):
        send_times.append((message["type"], time.perf_counter() - t_start))

    async def empty_receive():
        return {"type": "http.disconnect"}

    await middleware(_build_scope(), empty_receive, recording_send)

    # Expect 1 start + N body messages.
    start_events = [t for typ, t in send_times if typ == "http.response.start"]
    body_events = [t for typ, t in send_times if typ == "http.response.body"]

    assert len(start_events) == 1, f"expected 1 start, got {len(start_events)}"
    assert len(body_events) == _NUM_CHUNKS, (
        f"expected {_NUM_CHUNKS} body chunks, got {len(body_events)}. "
        "Middleware is merging/dropping chunks."
    )

    # Each chunk i should be forwarded at approximately i * _CHUNK_INTERVAL_S.
    for i, actual in enumerate(body_events):
        expected = i * _CHUNK_INTERVAL_S
        lag = actual - expected
        assert lag < _MAX_ALLOWED_LAG_S, (
            f"chunk {i} forwarded at {actual:.3f}s (lag={lag:.3f}s > "
            f"{_MAX_ALLOWED_LAG_S}s). Middleware is BUFFERING — check that "
            "api_server.py uses middleware.TimingSecurityHeadersMiddleware, "
            "NOT @app.middleware('http') / BaseHTTPMiddleware."
        )


@pytest.mark.asyncio
async def test_middleware_injects_security_headers() -> None:
    """Behavioural parity with the previous middleware."""
    middleware = TimingSecurityHeadersMiddleware(_downstream_app)
    captured_headers: list[tuple[bytes, bytes]] = []

    async def capturing_send(message):
        if message["type"] == "http.response.start":
            captured_headers.extend(message.get("headers") or [])

    async def empty_receive():
        return {"type": "http.disconnect"}

    await middleware(_build_scope(), empty_receive, capturing_send)

    header_map = {k.decode("latin-1").lower(): v.decode("latin-1")
                  for k, v in captured_headers}
    assert header_map.get("x-content-type-options") == "nosniff"
    assert header_map.get("x-frame-options") == "DENY"
    assert header_map.get("strict-transport-security", "").startswith("max-age=")


def test_api_server_uses_pure_asgi_middleware() -> None:
    """Source-level guard: api_server.py must not reintroduce @app.middleware('http').

    ``@app.middleware("http")`` expands to ``BaseHTTPMiddleware``, which buffers
    streaming responses and broke SSE in production. Enforce that the decorator
    is never used on the main app.
    """
    src = (_ROOT / "api_server.py").read_text(encoding="utf-8")
    assert '@app.middleware("http")' not in src, (
        'api_server.py uses @app.middleware("http") (BaseHTTPMiddleware) — '
        "this buffers streaming responses and will break SSE keepalives. "
        "Use a pure ASGI middleware class registered via app.add_middleware(...)."
    )
    assert "TimingSecurityHeadersMiddleware" in src, (
        "TimingSecurityHeadersMiddleware is missing from api_server.py — "
        "timing log and security headers will not be injected."
    )


@pytest.mark.asyncio
async def test_middleware_preserves_existing_headers() -> None:
    """If downstream already sets a security header, do not overwrite it."""
    async def app_with_override(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"x-frame-options", b"SAMEORIGIN")],
        })
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    middleware = TimingSecurityHeadersMiddleware(app_with_override)
    captured: list[tuple[bytes, bytes]] = []

    async def capturing_send(message):
        if message["type"] == "http.response.start":
            captured.extend(message.get("headers") or [])

    async def empty_receive():
        return {"type": "http.disconnect"}

    await middleware(_build_scope(), empty_receive, capturing_send)

    xfo_values = [v for k, v in captured if k.lower() == b"x-frame-options"]
    assert xfo_values == [b"SAMEORIGIN"], (
        f"expected existing X-Frame-Options preserved, got {xfo_values}"
    )
