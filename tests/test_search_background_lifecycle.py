"""Regression tests for lifespan-owned search background workers."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from routers import search as search_module


WORKER_NAMES = {"cache-maintenance", "query-prefetch"}
REPO_ROOT = Path(__file__).resolve().parents[1]


def _worker_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name in WORKER_NAMES]


def _wait_until(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


@pytest.fixture(autouse=True)
def _stop_lifecycle_workers():
    assert search_module.stop_search_background_workers(join_timeout=1.0)
    yield
    assert search_module.stop_search_background_workers(join_timeout=1.0)


@pytest.fixture
def isolated_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_module, "_cleanup_expired_cache", lambda: None)
    monkeypatch.setattr(search_module, "_log_cache_file_count", lambda: None)
    monkeypatch.setattr(search_module, "_load_query_freq_once", lambda: None)


def test_plain_import_starts_no_search_background_workers() -> None:
    script = """
import json
import threading
import routers.search

names = [
    thread.name
    for thread in threading.enumerate()
    if thread.name in {"cache-maintenance", "query-prefetch"}
]
print(json.dumps(names))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert json.loads(result.stdout.strip().splitlines()[-1]) == []


def test_start_stop_are_idempotent_and_restartable(
    monkeypatch: pytest.MonkeyPatch,
    isolated_lifecycle: None,
) -> None:
    started: list[tuple[str, threading.Event]] = []

    def worker(stop_event: threading.Event) -> None:
        started.append((threading.current_thread().name, stop_event))
        stop_event.wait()

    monkeypatch.setattr(search_module, "_periodic_cache_maintenance", worker)
    monkeypatch.setattr(search_module, "_prefetch_popular_queries", worker)

    assert search_module.start_search_background_workers() is True
    first_generation = search_module._background_generation
    assert first_generation is not None
    assert _wait_until(lambda: len(started) == 2)
    assert {name for name, _ in started} == WORKER_NAMES
    assert len({id(event) for _, event in started}) == 1

    assert search_module.start_search_background_workers() is False
    assert search_module._background_generation is first_generation
    assert len(_worker_threads()) == 2

    assert search_module.stop_search_background_workers(join_timeout=1.0) is True
    assert search_module.stop_search_background_workers(join_timeout=1.0) is True
    assert _worker_threads() == []

    assert search_module.start_search_background_workers() is True
    second_generation = search_module._background_generation
    assert second_generation is not None
    assert second_generation is not first_generation
    assert second_generation.stop_event is not first_generation.stop_event
    assert search_module.stop_search_background_workers(join_timeout=1.0) is True


def test_timed_out_generation_stays_signaled_and_blocks_restart(
    monkeypatch: pytest.MonkeyPatch,
    isolated_lifecycle: None,
) -> None:
    stubborn_started = threading.Event()
    release_stubborn = threading.Event()

    def cooperative(stop_event: threading.Event) -> None:
        stop_event.wait()

    def stubborn(_stop_event: threading.Event) -> None:
        stubborn_started.set()
        release_stubborn.wait()

    monkeypatch.setattr(search_module, "_periodic_cache_maintenance", cooperative)
    monkeypatch.setattr(search_module, "_prefetch_popular_queries", stubborn)

    assert search_module.start_search_background_workers() is True
    assert stubborn_started.wait(1.0)
    generation = search_module._background_generation
    assert generation is not None

    started_at = time.monotonic()
    assert search_module.stop_search_background_workers(join_timeout=0.02) is False
    assert time.monotonic() - started_at < 0.5
    assert generation.stop_event.is_set()
    assert search_module._background_generation is generation
    assert search_module.start_search_background_workers() is False
    assert search_module._background_generation is generation
    assert generation.stop_event.is_set()

    release_stubborn.set()
    assert _wait_until(
        lambda: not any(thread.is_alive() for thread in generation.threads)
    )

    monkeypatch.setattr(search_module, "_prefetch_popular_queries", cooperative)
    assert search_module.start_search_background_workers() is True
    assert search_module._background_generation is not generation
    assert search_module.stop_search_background_workers(join_timeout=1.0) is True


def test_long_worker_waits_are_interruptible(monkeypatch: pytest.MonkeyPatch) -> None:
    cache_stop = threading.Event()
    cache_thread = threading.Thread(
        target=search_module._periodic_cache_maintenance,
        args=(cache_stop,),
    )
    cache_thread.start()
    cache_stop.set()
    cache_thread.join(timeout=0.5)
    assert not cache_thread.is_alive()

    prefetch_stop = threading.Event()
    prefetch_thread = threading.Thread(
        target=search_module._prefetch_popular_queries,
        args=(prefetch_stop,),
    )
    prefetch_thread.start()
    prefetch_stop.set()
    prefetch_thread.join(timeout=0.5)
    assert not prefetch_thread.is_alive()

    searched = threading.Event()
    query_stop = threading.Event()
    monkeypatch.setattr(search_module, "_get_popular_queries", lambda: ["query"])
    monkeypatch.setattr(search_module, "_get_cached_result", lambda _key: None)
    monkeypatch.setattr(search_module, "_set_cache", lambda *_args, **_kwargs: None)

    def search_with_filters(_query, _filters):
        searched.set()
        return {}

    monkeypatch.setattr(
        search_module.search_agent, "search_with_filters", search_with_filters
    )
    query_thread = threading.Thread(
        target=search_module._prefetch_popular_queries_once,
        args=(query_stop,),
    )
    query_thread.start()
    assert searched.wait(1.0)
    query_stop.set()
    query_thread.join(timeout=0.5)
    assert not query_thread.is_alive()

    cycle_started = threading.Event()
    cycle_stop = threading.Event()

    def one_cycle(_stop_event: threading.Event) -> int:
        cycle_started.set()
        return 0

    monkeypatch.setattr(search_module, "_PREFETCH_STARTUP_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(search_module, "_prefetch_popular_queries_once", one_cycle)
    cycle_thread = threading.Thread(
        target=search_module._prefetch_popular_queries,
        args=(cycle_stop,),
    )
    cycle_thread.start()
    assert cycle_started.wait(1.0)
    cycle_stop.set()
    cycle_thread.join(timeout=0.5)
    assert not cycle_thread.is_alive()


@pytest.mark.asyncio
async def test_manual_prefetch_runs_one_bounded_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[threading.Event] = []

    def one_cycle(stop_event: threading.Event) -> int:
        calls.append(stop_event)
        return 3

    monkeypatch.setattr(search_module, "_get_popular_queries", lambda: ["a", "b"])
    monkeypatch.setattr(search_module, "_prefetch_popular_queries_once", one_cycle)

    response = await search_module.trigger_prefetch()

    assert response == {
        "message": "Prefetch completed",
        "queries": 2,
        "fetched": 3,
    }
    assert len(calls) == 1
    assert not calls[0].is_set()


@pytest.mark.asyncio
async def test_lifespan_starts_workers_and_always_stops_in_finally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api_server
    from routers import pdf_proxy
    from src.events import event_bus

    calls: list[str] = []

    class FakeBus:
        def register_main_loop(self, _loop) -> None:
            calls.append("register")

        async def wait_for_drain(self, timeout: float) -> None:
            assert timeout == 5.0
            calls.append("drain")

    async def close_http_client() -> None:
        calls.append("close")

    monkeypatch.setattr(api_server, "_ensure_faiss_index", lambda: None)
    monkeypatch.setattr(api_server, "_warm_cross_encoder", lambda: None)
    monkeypatch.setattr(api_server, "INDEXNOW_ENABLED", False)
    monkeypatch.setattr(event_bus, "get_event_bus", lambda: FakeBus())
    monkeypatch.setattr(pdf_proxy, "close_http_client", close_http_client)
    monkeypatch.setattr(
        api_server,
        "start_search_background_workers",
        lambda: calls.append("start") or True,
    )
    monkeypatch.setattr(
        api_server,
        "stop_search_background_workers",
        lambda: calls.append("stop") or True,
    )

    with pytest.raises(RuntimeError, match="lifespan body failed"):
        async with api_server.lifespan(api_server.app):
            assert calls[-1] == "start"
            raise RuntimeError("lifespan body failed")

    assert calls[-3:] == ["stop", "drain", "close"]
    assert calls.count("start") == 1
    assert calls.count("stop") == 1
