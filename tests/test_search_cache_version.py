"""Tests for search result cache versioning (US-012).

Verifies that _CACHE_SCHEMA_VERSION is embedded in cache keys so that
bumping the version constant invalidates all pre-existing cache entries.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_module():
    """Import routers.search with the real module (no reload needed)."""
    import routers.search as rs
    return rs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cache_schema_version_constant_exists():
    rs = _get_module()
    assert hasattr(rs, "_CACHE_SCHEMA_VERSION"), "_CACHE_SCHEMA_VERSION must be defined"
    assert isinstance(rs._CACHE_SCHEMA_VERSION, str)
    assert len(rs._CACHE_SCHEMA_VERSION) > 0


def test_cache_key_embeds_schema_version():
    """_compute_cache_key must produce different hashes for different schema versions."""
    import routers.search as rs

    original_version = rs._CACHE_SCHEMA_VERSION
    try:
        key_v2 = rs._compute_cache_key("transformer attention", ["arxiv"], {})
        rs._CACHE_SCHEMA_VERSION = "v3-future"
        key_v3 = rs._compute_cache_key("transformer attention", ["arxiv"], {})
        assert key_v2 != key_v3, (
            "Cache keys must differ when _CACHE_SCHEMA_VERSION changes"
        )
    finally:
        rs._CACHE_SCHEMA_VERSION = original_version


def test_same_version_same_key():
    """Identical query + version always yields the same key (determinism)."""
    import routers.search as rs

    key1 = rs._compute_cache_key("neural network", ["arxiv"], {})
    key2 = rs._compute_cache_key("neural network", ["arxiv"], {})
    assert key1 == key2


def test_cache_version_change_invalidates_file_cache(monkeypatch, tmp_path):
    """Old cache files (wrong version key) must not be read after version bump."""
    import routers.search as rs
    from datetime import datetime, timedelta

    monkeypatch.setattr(rs, "SEARCH_CACHE_DIR", tmp_path)
    monkeypatch.setattr(rs, "_CACHE_SCHEMA_VERSION", "v2-hybrid-rrf-semantic")

    # Write a cache entry under the current (old) version key
    old_key = rs._compute_cache_key("query versioning test", ["arxiv"], {})
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    old_entry = {
        "results": {"papers": [{"title": "stale paper"}]},
        "expires_at": future,
        "cached_at": datetime.now().isoformat(),
    }
    cache_file = tmp_path / f"{old_key}.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(old_entry, f)

    # Also seed in-memory cache
    with rs._cache_lock:
        rs._search_cache[old_key] = old_entry

    # Bump version — new key must differ
    monkeypatch.setattr(rs, "_CACHE_SCHEMA_VERSION", "v3-future")
    new_key = rs._compute_cache_key("query versioning test", ["arxiv"], {})
    assert new_key != old_key, "New version must produce a different key"

    # Reading via the new key must return None (cache miss)
    result = rs._get_cached_result(new_key)
    assert result is None, "New-version key must not hit old-version cache file"

    # Cleanup in-memory cache entry seeded above
    with rs._cache_lock:
        rs._search_cache.pop(old_key, None)


def test_legacy_key_still_in_cache_but_unreachable_via_new_key():
    """After version bump, old in-memory entry is present but new key misses."""
    import routers.search as rs

    original_version = rs._CACHE_SCHEMA_VERSION
    try:
        old_key = rs._compute_cache_key("some query", ["arxiv"], {})

        from datetime import datetime, timedelta
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        with rs._cache_lock:
            rs._search_cache[old_key] = {
                "results": {"papers": []},
                "expires_at": future,
                "cached_at": datetime.now().isoformat(),
            }

        rs._CACHE_SCHEMA_VERSION = "v3-future"
        new_key = rs._compute_cache_key("some query", ["arxiv"], {})
        assert new_key != old_key

        # The new key misses even though old key is in memory
        with rs._cache_lock:
            miss = new_key not in rs._search_cache
        assert miss, "New key must not resolve to old in-memory entry"

    finally:
        rs._CACHE_SCHEMA_VERSION = original_version
        with rs._cache_lock:
            rs._search_cache.pop(old_key, None)
