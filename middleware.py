"""ASGI middleware for request timing and security header injection.

Implemented as a raw ASGI class (not BaseHTTPMiddleware) so streaming
responses (SSE) are not buffered through anyio memory streams — keepalive
chunks must reach the proxy in real time to prevent proxy_read_timeout.
"""

from __future__ import annotations

import logging
import os
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("PaperReview")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class TimingSecurityHeadersMiddleware:
    """Pure ASGI middleware: logs duration and injects security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_holder = {"code": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                headers = list(message.get("headers") or [])
                existing = {k.lower() for k, _ in headers}
                for hdr, val in _SECURITY_HEADERS.items():
                    hb = hdr.lower().encode("latin-1")
                    if hb not in existing:
                        headers.append((hb, val.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_s = time.perf_counter() - start
            duration_ms = duration_s * 1000
            if duration_s > REQUEST_TIMEOUT:
                logger.warning(
                    "Slow request (%ds limit exceeded): %s %s → %s (%.1fms)",
                    REQUEST_TIMEOUT,
                    scope.get("method", "?"),
                    scope.get("path", "?"),
                    status_holder["code"] or 0,
                    duration_ms,
                )
            else:
                logger.debug(
                    "%s %s → %s (%.1fms)",
                    scope.get("method", "?"),
                    scope.get("path", "?"),
                    status_holder["code"] or 0,
                    duration_ms,
                )
