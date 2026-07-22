"""느린 요청이 프로덕션 로그에 남는지 검증.

배경: 앱 로거는 INFO 레벨인데 요청 타이밍 로그가 DEBUG였다. 그래서 120초
상한(REQUEST_TIMEOUT)에 걸리지 않은 느린 요청은 프로덕션에 아무 흔적도
남기지 않았고, 지연 원인을 사후에 추적할 수단이 없었다.

검증:
- 임계값을 넘는 요청은 INFO로 남는다
- 정상 속도 요청은 INFO를 오염시키지 않는다
- 상한 초과는 기존대로 WARNING을 유지한다
"""

from __future__ import annotations

import logging

import pytest

import middleware as mw
from middleware import TimingSecurityHeadersMiddleware


async def _noop_app(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def _drive(app, monkeypatch, elapsed: float) -> None:
    """perf_counter를 조작해 원하는 소요시간을 만든다."""
    ticks = iter([0.0, elapsed])
    monkeypatch.setattr(mw.time, "perf_counter", lambda: next(ticks))

    scope = {"type": "http", "method": "GET", "path": "/api/search", "headers": []}

    async def receive():
        return {"type": "http.request"}

    sent = []

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)


@pytest.mark.asyncio
async def test_slow_request_logs_at_info(monkeypatch, caplog) -> None:
    app = TimingSecurityHeadersMiddleware(_noop_app)
    monkeypatch.setattr(mw, "SLOW_REQUEST_LOG_THRESHOLD", 1.0)
    monkeypatch.setattr(mw, "REQUEST_TIMEOUT", 120)

    with caplog.at_level(logging.INFO, logger=mw.logger.name):
        await _drive(app, monkeypatch, elapsed=3.5)

    records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert records, "임계값을 넘겼는데 INFO 로그가 없다"
    assert "Slow request" in records[0].getMessage()
    assert "/api/search" in records[0].getMessage()


@pytest.mark.asyncio
async def test_fast_request_does_not_log_at_info(monkeypatch, caplog) -> None:
    """정상 트래픽까지 INFO로 올리면 검색 한 건에 로그가 수십 줄씩 불어난다."""
    app = TimingSecurityHeadersMiddleware(_noop_app)
    monkeypatch.setattr(mw, "SLOW_REQUEST_LOG_THRESHOLD", 1.0)
    monkeypatch.setattr(mw, "REQUEST_TIMEOUT", 120)

    with caplog.at_level(logging.INFO, logger=mw.logger.name):
        await _drive(app, monkeypatch, elapsed=0.05)

    assert not [r for r in caplog.records if r.levelno >= logging.INFO]


@pytest.mark.asyncio
async def test_over_limit_still_warns(monkeypatch, caplog) -> None:
    """상한 초과는 기존 WARNING 동작을 유지해야 한다."""
    app = TimingSecurityHeadersMiddleware(_noop_app)
    monkeypatch.setattr(mw, "SLOW_REQUEST_LOG_THRESHOLD", 1.0)
    monkeypatch.setattr(mw, "REQUEST_TIMEOUT", 120)

    with caplog.at_level(logging.INFO, logger=mw.logger.name):
        await _drive(app, monkeypatch, elapsed=150.0)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings
    assert "limit exceeded" in warnings[0].getMessage()
