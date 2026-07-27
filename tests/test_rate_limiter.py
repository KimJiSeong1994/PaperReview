"""Thread-safety of the shared source throttle.

The searchers are process-wide singletons driven from thread-pool workers. The
concurrency test below is the point of the module: the previous per-searcher
implementation passed a serial test and still let every concurrent caller
through at once, which is how production earned sustained HTTP 429s.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.collector.paper.rate_limiter import RateLimiter


def _departure_times(limiter: RateLimiter, callers: int) -> list[float]:
    """Return the monotonic time at which each caller left the throttle."""
    barrier = threading.Barrier(callers)

    def call() -> float:
        barrier.wait()  # make every caller contend at the same instant
        limiter.wait()
        return time.monotonic()

    with ThreadPoolExecutor(max_workers=callers) as pool:
        return sorted(f.result() for f in [pool.submit(call) for _ in range(callers)])


def test_concurrent_callers_are_spaced_not_burst():
    interval = 0.05
    times = _departure_times(RateLimiter(interval), callers=5)

    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(g >= interval * 0.9 for g in gaps), f"burst detected: {gaps}"


def test_serial_calls_are_spaced():
    limiter = RateLimiter(0.05)
    limiter.wait()
    start = time.monotonic()
    limiter.wait()

    assert time.monotonic() - start >= 0.045


def test_first_call_does_not_block():
    start = time.monotonic()
    RateLimiter(30.0).wait()

    assert time.monotonic() - start < 1.0


def test_jitter_widens_the_interval():
    limiter = RateLimiter(0.02, jitter=(0.03, 0.04))
    limiter.wait()
    start = time.monotonic()
    limiter.wait()

    assert time.monotonic() - start >= 0.05


THROTTLED_CLIENTS = [
    ("src.collector.paper.openalex_searcher", "OpenAlexSearcher"),
    ("src.collector.paper.dblp_searcher", "DBLPSearcher"),
    ("src.collector.paper.google_scholar_searcher", "GoogleScholarSearcher"),
    ("src.collector.paper.semantic_scholar_client", "SemanticScholarClient"),
]


def _client_class(module_path: str, attr: str):
    return getattr(__import__(module_path, fromlist=[attr]), attr)


@pytest.mark.parametrize("module_path,attr", THROTTLED_CLIENTS)
def test_searchers_use_the_shared_limiter(module_path, attr):
    """Every throttled client must route through the locked implementation."""
    assert isinstance(_client_class(module_path, attr)()._rate_limiter, RateLimiter)


@pytest.mark.parametrize("module_path,attr", THROTTLED_CLIENTS)
def test_limiter_is_shared_across_instances(module_path, attr):
    """The throttle must be process-wide, not per-instance.

    Upstream quotas are per-IP, and several call sites build their own client
    (curriculum, related-paper wiki, exploration routers). A per-instance
    limiter lets those bypass each other's spacing and burst the upstream.
    """
    cls = _client_class(module_path, attr)

    assert cls()._rate_limiter is cls()._rate_limiter
    assert "_rate_limiter" in vars(cls), "limiter must be a class attribute"
    assert "_rate_limiter" not in vars(cls()), "limiter must not be per-instance"
