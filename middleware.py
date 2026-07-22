"""ASGI middleware for request timing and security header injection.

Implemented as a raw ASGI class (not BaseHTTPMiddleware) so streaming
responses (SSE) are not buffered through anyio memory streams — keepalive
chunks must reach the proxy in real time to prevent proxy_read_timeout.
"""

from __future__ import annotations

import logging
import os
import re
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("PaperReview")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))
# 이 시간을 넘긴 요청만 INFO로 남긴다. 정상 트래픽까지 INFO로 올리면 로그가
# 검색 한 건에 수십 줄씩 불어난다.
SLOW_REQUEST_LOG_THRESHOLD = float(os.getenv("SLOW_REQUEST_LOG_THRESHOLD", "1.0"))

# Known AI crawler user-agents and AI-engine referer hosts (case-insensitive).
_AI_BOT_RE = re.compile(
    r"GPTBot|OAI-SearchBot|ChatGPT-User|ClaudeBot|Claude-User|Claude-SearchBot|"
    r"anthropic-ai|PerplexityBot|Perplexity-User|Googlebot|Google-Extended|"
    r"Bingbot|Applebot|Bytespider|CCBot|Amazonbot|Yeti",
    re.IGNORECASE,
)
_AI_REFERRER_RE = re.compile(
    r"chatgpt\.com|perplexity\.ai|claude\.ai|anthropic\.com|gemini\.google|"
    r"copilot\.microsoft|you\.com|deepseek\.com",
    re.IGNORECASE,
)

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
            elif duration_s > SLOW_REQUEST_LOG_THRESHOLD:
                # 앱 로거는 INFO 레벨이라 debug 로그는 버려진다. 그 결과 120초
                # 상한에 걸리지 않은 느린 요청은 프로덕션에 흔적이 남지 않았다.
                # 임계값을 넘는 것만 INFO로 올려 정상 트래픽은 조용히 둔다.
                logger.info(
                    "Slow request: %s %s → %s (%.1fms)",
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

            self._log_ai_traffic(scope, status_holder["code"] or 0)

    @staticmethod
    def _log_ai_traffic(scope: Scope, status: int) -> None:
        """Log requests from known AI crawlers or carrying an AI-engine referer."""
        user_agent = ""
        referer = ""
        for key, value in scope.get("headers") or []:
            name = key.decode("latin-1").lower()
            if name == "user-agent":
                user_agent = value.decode("latin-1")
            elif name == "referer":
                referer = value.decode("latin-1")

        path = scope.get("path", "?")
        bot_match = _AI_BOT_RE.search(user_agent) if user_agent else None
        if bot_match:
            logger.info(
                "AI bot: bot=%s path=%s status=%s",
                bot_match.group(0),
                path,
                status,
            )
        if referer and _AI_REFERRER_RE.search(referer):
            logger.info("AI referral: referer=%s path=%s", referer, path)
