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


@pytest.mark.parametrize(
    "module_path,attr",
    [
        ("src.collector.paper.openalex_searcher", "OpenAlexSearcher"),
        ("src.collector.paper.dblp_searcher", "DBLPSearcher"),
        ("src.collector.paper.google_scholar_searcher", "GoogleScholarSearcher"),
        ("src.collector.paper.semantic_scholar_client", "SemanticScholarClient"),
    ],
)
def test_searchers_use_the_shared_limiter(module_path, attr):
    """Every throttled client must route through the locked implementation."""
    module = __import__(module_path, fromlist=[attr])
    limiter = getattr(module, attr)()._rate_limiter

    assert isinstance(limiter, RateLimiter)
