"""Optional model warmup must not hold public blog readiness hostage."""

import asyncio
import threading

import pytest

import api_server as server
import routers.pdf_proxy as pdf_proxy
import src.analytics.mcp_usage as mcp_usage
import src.events.event_bus as event_bus


@pytest.fixture
def startup(monkeypatch):
    events = []

    class Bus:
        def register_main_loop(self, loop):
            events.append("bus_ready")

        async def wait_for_drain(self, timeout):
            events.append("bus_drained")

    async def drain():
        events.append("measurements_drained")

    async def close():
        events.append("http_closed")

    monkeypatch.setattr(
        mcp_usage, "initialize_mcp_usage", lambda: events.append("db_ready")
    )
    monkeypatch.setattr(
        server, "_ensure_faiss_index", lambda: events.append("index_ready")
    )
    monkeypatch.setattr(server, "INDEXNOW_ENABLED", False)
    monkeypatch.setattr(event_bus, "get_event_bus", lambda: Bus())
    monkeypatch.setattr(
        server,
        "start_search_background_workers",
        lambda: events.append("workers_started"),
    )
    monkeypatch.setattr(
        server,
        "stop_search_background_workers",
        lambda: events.append("workers_stopped") or True,
    )
    monkeypatch.setattr(server, "drain_measurements", drain)
    monkeypatch.setattr(pdf_proxy, "close_http_client", close)
    return events


@pytest.mark.asyncio
async def test_slow_optional_warmup_does_not_delay_readiness(startup, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def warm():
        started.set()
        release.wait(timeout=3)

    monkeypatch.setattr(server, "_warm_cross_encoder", warm)
    context = server.lifespan(server.app)
    entering = asyncio.create_task(context.__aenter__())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.wait_for(asyncio.shield(entering), timeout=0.2)
        assert "db_ready" in startup and "workers_started" in startup
        assert not release.is_set()
    finally:
        release.set()
        await entering
        await context.__aexit__(None, None, None)
    assert "workers_stopped" in startup
    assert "measurements_drained" in startup
    assert "bus_drained" in startup and "http_closed" in startup


@pytest.mark.asyncio
async def test_optional_warmup_exception_does_not_fail_startup(
    startup, monkeypatch, caplog
):
    attempted = threading.Event()

    def fail():
        attempted.set()
        raise RuntimeError("optional model unavailable")

    monkeypatch.setattr(server, "_warm_cross_encoder", fail)
    async with server.lifespan(server.app):
        assert await asyncio.to_thread(attempted.wait, 1)
        await asyncio.sleep(0.01)
        assert "workers_started" in startup
    assert "optional model unavailable" in caplog.text
    assert "bus_drained" in startup


@pytest.mark.asyncio
async def test_required_database_initialization_still_blocks_startup(
    startup, monkeypatch
):
    def fail():
        raise RuntimeError("required database unavailable")

    monkeypatch.setattr(mcp_usage, "initialize_mcp_usage", fail)
    with pytest.raises(RuntimeError, match="required database"):
        async with server.lifespan(server.app):
            pytest.fail("Required initialization was bypassed")
    assert "workers_started" not in startup


@pytest.mark.asyncio
async def test_stalled_optional_warmup_does_not_hold_process_shutdown(
    startup, monkeypatch
):
    started, release = threading.Event(), threading.Event()
    threads = []

    def stalled():
        threads.append(threading.current_thread())
        started.set()
        release.wait(timeout=3)

    monkeypatch.setattr(server, "_warm_cross_encoder", stalled)
    context = server.lifespan(server.app)
    try:
        await context.__aenter__()
        assert await asyncio.to_thread(started.wait, 1)
        assert threads[0].is_alive() and threads[0].daemon
        await asyncio.wait_for(context.__aexit__(None, None, None), timeout=0.2)
        assert not release.is_set()
        assert "workers_stopped" in startup and "bus_drained" in startup
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=1)
