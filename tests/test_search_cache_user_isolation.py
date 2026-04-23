"""F-03 regression: search cache must not leak ``searched_by`` across users.

The search cache key is deliberately user-agnostic (one entry per query, not
per-query-per-user), so the cache body must also be user-agnostic. The stamp
``searched_by=<username>`` is applied per-request at response time:

* On cache MISS: results are stamped for the caller, then a stripped copy is
  persisted.
* On cache HIT: the cache body is loaded, any stale stamp (e.g. from a
  pre-fix on-disk entry) is stripped defensively, then the results are
  re-stamped for the current caller before being returned.

These tests pin that contract using the module-level cache helpers directly
(no FastAPI/network round-trip needed — the semantics live entirely in
``_set_cache`` / ``_get_cached_result`` / ``_stamp_searched_by``).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List


def _fresh_results(titles: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Build a minimal results payload shaped like the real search response."""
    return {"arxiv": [{"title": t, "year": 2024} for t in titles]}


def _reset_cache_state(rs) -> None:
    with rs._cache_lock:
        rs._search_cache.clear()


def test_cache_miss_stamp_applied(monkeypatch, tmp_path):
    """A first-time caller (cache miss path) must see ``searched_by`` = them."""
    import routers.search as rs

    monkeypatch.setattr(rs, "SEARCH_CACHE_DIR", tmp_path)
    _reset_cache_state(rs)

    # Simulate the main handler's miss flow: stamp -> _set_cache.
    results = _fresh_results(["Paper A", "Paper B"])
    rs._stamp_searched_by(results, "alice")
    assert all(p["searched_by"] == "alice" for p in results["arxiv"])

    cache_key = "f03-miss"
    rs._set_cache(cache_key, results)

    # The live response the caller is about to return is still stamped for
    # alice — the write path must not strip it in-place.
    assert all(p["searched_by"] == "alice" for p in results["arxiv"]), (
        "_set_cache must not mutate the caller's in-flight response"
    )

    # But the persisted file body must have NO stamp at all.
    cache_file = tmp_path / f"{cache_key}.json"
    assert cache_file.exists()
    persisted = json.loads(cache_file.read_text(encoding="utf-8"))
    for paper in persisted["results"]["arxiv"]:
        assert "searched_by" not in paper, (
            "on-disk cache body must be user-agnostic (no searched_by key)"
        )


def test_cache_hit_restamps_for_new_user(monkeypatch, tmp_path):
    """User B hitting alice's cached query must get searched_by=B, not A."""
    import routers.search as rs

    monkeypatch.setattr(rs, "SEARCH_CACHE_DIR", tmp_path)
    _reset_cache_state(rs)

    # 1) User A populates cache (miss -> stamp -> set).
    results_a = _fresh_results(["Paper A", "Paper B"])
    rs._stamp_searched_by(results_a, "alice")
    cache_key = "f03-hit"
    rs._set_cache(cache_key, results_a)

    # 2) User B hits the same key. Simulate the handler's cache-hit path:
    #    _get_cached_result returns a stripped body, then the handler stamps
    #    the current caller's username.
    cached = rs._get_cached_result(cache_key)
    assert cached is not None, "B should hit the cache key A just populated"
    # Before re-stamping, there must be no leftover 'alice' anywhere.
    for paper in cached["arxiv"]:
        assert "searched_by" not in paper, (
            "cache read must strip searched_by before handing results back"
        )

    rs._stamp_searched_by(cached, "bob")
    for paper in cached["arxiv"]:
        assert paper["searched_by"] == "bob", (
            "post-hit stamp must reflect the current caller, not the populator"
        )
        assert paper["searched_by"] != "alice"


def test_on_disk_cache_stripped_on_read(monkeypatch, tmp_path):
    """Legacy on-disk entries (pre-F-03) carrying searched_by must be scrubbed."""
    import routers.search as rs

    monkeypatch.setattr(rs, "SEARCH_CACHE_DIR", tmp_path)
    _reset_cache_state(rs)

    # Hand-write a legacy cache file that still carries a stale searched_by
    # stamp (this is what the disk looks like for entries written by the
    # pre-fix code path).
    cache_key = "f03-legacy"
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    legacy_entry = {
        "results": {
            "arxiv": [
                {"title": "Legacy Paper", "year": 2023, "searched_by": "old_user"},
                {"title": "Another", "year": 2024, "searched_by": "old_user"},
            ]
        },
        "expires_at": future,
        "cached_at": datetime.now().isoformat(),
    }
    (tmp_path / f"{cache_key}.json").write_text(
        json.dumps(legacy_entry), encoding="utf-8"
    )

    # A new caller reads it. The defensive strip in _get_cached_result must
    # remove the stale 'old_user' stamp before any re-stamp happens.
    cached = rs._get_cached_result(cache_key)
    assert cached is not None
    for paper in cached["arxiv"]:
        assert "searched_by" not in paper, (
            "legacy on-disk searched_by must be stripped on read"
        )

    # The handler then stamps the new caller.
    rs._stamp_searched_by(cached, "new_user")
    for paper in cached["arxiv"]:
        assert paper["searched_by"] == "new_user"
        assert paper["searched_by"] != "old_user"

    # Subsequent read (now from in-memory cache populated by the file read
    # above) must also be stamp-free before re-stamping — i.e. the strip
    # persisted into the memoized entry too.
    cached2 = rs._get_cached_result(cache_key)
    assert cached2 is not None
    for paper in cached2["arxiv"]:
        assert "searched_by" not in paper
