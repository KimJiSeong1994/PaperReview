"""Thread-safe minimum-interval throttle shared by the paper searchers."""
import random
import threading
import time
from typing import Optional, Tuple


class RateLimiter:
    """Space out requests to one upstream by at least ``min_interval`` seconds.

    Searcher instances are process-wide singletons (see ``routers/deps/agents``)
    driven from thread-pool workers, so the interval must be enforced under a
    lock. Without one, concurrent callers all read the same stale timestamp, all
    conclude that enough time has passed, and the upstream receives a burst —
    which is how the searchers earned sustained HTTP 429s in production.

    The lock is held across the sleep on purpose: callers queue up and leave at
    the intended spacing instead of stampeding once the sleep ends.
    """

    def __init__(
        self,
        min_interval: float,
        jitter: Optional[Tuple[float, float]] = None,
    ) -> None:
        self.min_interval = min_interval
        self.jitter = jitter
        self._lock = threading.Lock()
        # monotonic, so a wall-clock adjustment cannot make the gap look huge
        # (skipping the throttle) or negative (sleeping far too long).
        self._last_request = float("-inf")

    def wait(self) -> None:
        """Block until this caller may issue its request."""
        # ponytail: one lock per upstream serialises every caller of that
        # source. If queueing ever eats the per-source timeout budget, swap the
        # body for a token bucket — the call sites do not need to change.
        with self._lock:
            interval = self.min_interval
            if self.jitter:
                interval += random.uniform(*self.jitter)
            elapsed = time.monotonic() - self._last_request
            if elapsed < interval:
                time.sleep(interval - elapsed)
            self._last_request = time.monotonic()
