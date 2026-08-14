"""Poster rate-limit public error contract regressions."""

from __future__ import annotations

import json
from typing import Any

import pytest
from limits import parse
from slowapi.errors import RateLimitExceeded
from slowapi.wrappers import Limit
from starlette.requests import Request

from app.DeepAgent.poster.result_contract import CODE_RATE_LIMITED
from routers.deps import limiter as real_limiter


class _StubPosterService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "poster_status": "succeeded",
            "status": "succeeded",
            "success": True,
            "session_id": "",
            "poster_html": "<main>stub poster</main>",
            "poster_path": "",
            "error": "",
            "warnings": [],
            "error_code": "",
            "retryable": False,
            "generation_id": "poster_stub123456",
            "timings": {"total_ms": 1.0},
            "provenance": {"route": "deep-review/visualize-direct"},
            "quality": {"validation_score": 0.9},
            "artifacts": {"html_bytes": 24},
        }


def _limit_exceeded() -> RateLimitExceeded:
    return RateLimitExceeded(
        Limit(
            limit=parse("3/minute"),
            key_func=lambda request: "test-client",
            scope="poster-test",
            per_method=False,
            methods=None,
            error_message=None,
            exempt_when=None,
            cost=1,
            override_defaults=True,
        )
    )


def _request(app: Any, path: str) -> Request:
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "POST",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "app": app,
        }
    )
    request.state.view_rate_limit = None
    return request


async def _invoke_rate_limit_handler(app: Any, path: str):
    from slowapi.errors import RateLimitExceeded

    handler = app.exception_handlers[RateLimitExceeded]
    return await handler(_request(app, path), _limit_exceeded())


@pytest.mark.asyncio
async def test_visualize_direct_http_reaches_stubbed_service_with_slowapi_request_param(
    app,
    client,
    auth_headers,
    monkeypatch,
) -> None:
    stub = _StubPosterService()
    monkeypatch.setattr("routers.reviews._poster_service", stub)
    real_limiter._storage.reset()
    app.state.limiter.enabled = True

    try:
        response = await client.post(
            "/api/deep-review/visualize-direct",
            json={"report_content": "# Report\n\nBody", "num_papers": 1},
            headers=auth_headers,
        )
    finally:
        real_limiter._storage.reset()

    body = response.json()
    assert response.status_code == 200, body
    assert body["status"] == "succeeded"
    assert body["success"] is True
    assert body["poster_html"] == "<main>stub poster</main>"
    assert stub.calls
    assert stub.calls[0]["report_content"] == "# Report\n\nBody"
    assert stub.calls[0]["num_papers"] == 1


@pytest.mark.asyncio
async def test_poster_visualize_rate_limit_uses_v2_error_detail(app) -> None:
    response = await _invoke_rate_limit_handler(
        app, "/api/deep-review/visualize/session-1"
    )
    body = json.loads(response.body)

    assert response.status_code == 429
    assert body["detail"]["error_code"] == CODE_RATE_LIMITED
    assert body["detail"]["status"] == "failed"
    assert body["detail"]["poster_status"] == "failed"
    assert body["detail"]["success"] is False
    assert body["detail"]["retryable"] is True
    assert body["detail"]["generation_id"].startswith("poster_")


@pytest.mark.asyncio
async def test_poster_visualize_direct_rate_limit_uses_v2_error_detail(app) -> None:
    response = await _invoke_rate_limit_handler(app, "/api/deep-review/visualize-direct")
    body = json.loads(response.body)

    assert response.status_code == 429
    assert body["detail"]["error_code"] == CODE_RATE_LIMITED
    assert body["detail"]["status"] == "failed"
    assert body["detail"]["success"] is False
    assert body["detail"]["retryable"] is True
    assert body["detail"]["generation_id"].startswith("poster_")


@pytest.mark.asyncio
async def test_non_poster_rate_limit_keeps_generic_handler_shape(app) -> None:
    response = await _invoke_rate_limit_handler(app, "/api/search")
    body = json.loads(response.body)

    assert response.status_code == 429
    assert set(body) == {"error"}
    assert body["error"].startswith("Rate limit exceeded:")
