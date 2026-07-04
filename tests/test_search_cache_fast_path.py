from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_search_cache_hit_bypasses_query_analysis(client):
    """Warm search cache hits should return before the LLM analyzer runs."""
    from routers import search as rs

    cached = {
        "arxiv": [
            {
                "title": "Cached Paper",
                "authors": [],
                "abstract": "cached",
                "source": "arxiv",
            }
        ]
    }
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.side_effect = AssertionError("query analysis should be skipped")

    search_agent = MagicMock()
    search_agent.async_search_with_filters.side_effect = AssertionError("source search should be skipped")

    with (
        patch.object(rs, "query_analyzer", analyzer),
        patch.object(rs, "search_agent", search_agent),
        patch.object(rs, "_get_cached_result", return_value=cached) as get_cached,
        patch.object(rs, "_set_cache", return_value=None),
    ):
        resp = await client.post(
            "/api/search",
            json={"query": "machine learning", "fast_mode": True, "save_papers": False},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cache_hit"] is True
    assert body["quality_mode"] == "cache_fast_path"
    assert body["query_analysis"] is None
    assert body["total"] == 1
    assert body["stage_modes"]["query_analysis_mode"] == "skipped_cache_hit"
    assert body["stage_modes"]["source_search_mode"] == "skipped_cache_hit"
    assert "cache_lookup" in body["stage_timings"]
    assert body["metadata"]["cache_hit"] is True
    assert body["metadata"]["quality_mode"] == "cache_fast_path"
    assert body["metadata"]["stage_modes"]["cache_fast_path"] is True
    assert get_cached.call_args.kwargs["require_academic_guard"] is True
    analyzer.analyze_and_prepare.assert_not_called()
    search_agent.async_search_with_filters.assert_not_called()


def test_pre_analysis_cache_hit_requires_academic_guard(monkeypatch, tmp_path):
    """Only academically-guarded entries may use the pre-analysis fast path."""
    from routers import search as rs

    monkeypatch.setattr(rs, "SEARCH_CACHE_DIR", tmp_path)
    with rs._cache_lock:
        rs._search_cache.clear()

    unguarded_key = "unguarded-cache"
    guarded_key = "guarded-cache"
    results = {"arxiv": [{"title": "Guarded Paper"}]}

    rs._set_cache(unguarded_key, results)
    assert rs._get_cached_result(unguarded_key, require_academic_guard=True) is None
    assert rs._get_cached_result(unguarded_key) == results

    rs._set_cache(guarded_key, results, academic_guard_passed=True)
    assert rs._get_cached_result(guarded_key, require_academic_guard=True) == results


@pytest.mark.asyncio
async def test_unguarded_cache_does_not_bypass_non_academic_guard(client, monkeypatch, tmp_path):
    """Legacy/prefetch cache entries must not bypass current non-academic blocking."""
    from routers import search as rs

    monkeypatch.setattr(rs, "SEARCH_CACHE_DIR", tmp_path)
    with rs._cache_lock:
        rs._search_cache.clear()

    query = "today weather"
    sources = ["arxiv"]
    cache_key = rs._compute_cache_key(
        query,
        sources,
        {
            "sort_by": "relevance",
            "year_start": None,
            "year_end": None,
            "author": None,
            "category": None,
            "fast_mode": False,
        },
    )
    rs._set_cache(cache_key, {"arxiv": [{"title": "Should Not Return"}]})

    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {
        "is_academic": False,
        "intent": "non_academic",
        "keywords": [],
        "improved_query": query,
        "search_filters": {},
        "confidence": 0.99,
        "original_query": query,
        "source_queries": {},
    }
    search_agent = MagicMock()
    search_agent.async_search_with_filters.side_effect = AssertionError("source search should be skipped")

    with (
        patch.object(rs, "query_analyzer", analyzer),
        patch.object(rs, "search_agent", search_agent),
    ):
        resp = await client.post(
            "/api/search",
            json={"query": query, "sources": sources, "save_papers": False},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["query_analysis"]["is_academic"] is False
    assert body["results"] == {"arxiv": []}
    analyzer.analyze_and_prepare.assert_called_once()
    search_agent.async_search_with_filters.assert_not_called()


@pytest.mark.asyncio
async def test_query_analysis_fallback_cache_is_not_pre_analysis_guarded(client):
    """Analyzer timeout/error fallbacks may cache results but not as guarded fast-path entries."""
    from routers import search as rs

    analyzer = MagicMock()
    analyzer.analyze_and_prepare.side_effect = RuntimeError("analyzer unavailable")
    analyzer.classify_difficulty.return_value = "easy"

    search_agent = MagicMock()

    async def _async_search(query, filters):  # noqa: ANN001
        return {"arxiv": [{"title": "Fallback Paper", "source": "arxiv"}]}

    search_agent.async_search_with_filters.side_effect = _async_search
    search_agent.deduplicator = MagicMock()
    search_agent.deduplicator.deduplicate.side_effect = lambda papers: papers
    search_agent.save_papers.return_value = {"new_papers": 0, "duplicates": 0}
    search_agent.similarity_calculator = MagicMock()

    with (
        patch.object(rs, "query_analyzer", analyzer),
        patch.object(rs, "search_agent", search_agent),
        patch.object(rs, "relevance_filter", None),
        patch.object(rs, "_hybrid_ranker", None),
        patch.object(rs, "_get_cached_result", return_value=None),
        patch.object(rs, "_set_cache", return_value=None) as set_cache,
        patch("routers.search.json.dump", return_value=None),
    ):
        resp = await client.post(
            "/api/search",
            json={
                "query": "today weather",
                "sources": ["arxiv"],
                "fast_mode": True,
                "save_papers": False,
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["stage_modes"]["query_analysis_mode"] == "unified_error_fallback"
    assert body["stage_modes"]["academic_guard_passed"] is False
    assert set_cache.call_args.kwargs["academic_guard_passed"] is False


@pytest.mark.asyncio
async def test_search_response_includes_source_timing_metadata(client):
    """The API should expose per-source timing metadata from async source search."""
    from routers import search as rs

    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {
        "is_academic": True,
        "intent": "paper_search",
        "keywords": ["transformer"],
        "improved_query": "transformer",
        "search_filters": {},
        "confidence": 0.9,
        "original_query": "transformer",
        "source_queries": {},
    }
    analyzer.classify_difficulty.return_value = "easy"

    search_agent = MagicMock()

    async def _async_search(query, filters):  # noqa: ANN001
        metadata = filters["_metadata"]
        metadata["timings"]["arxiv"] = 0.012
        metadata["timeouts"]["arxiv"] = False
        metadata["modes"]["arxiv"] = "searched"
        return {"arxiv": [{"title": "Timed Paper", "source": "arxiv"}]}

    search_agent.async_search_with_filters.side_effect = _async_search
    search_agent.deduplicator = MagicMock()
    search_agent.deduplicator.deduplicate.side_effect = lambda papers: papers
    search_agent.save_papers.return_value = {"new_papers": 0, "duplicates": 0}
    search_agent.similarity_calculator = MagicMock()

    with (
        patch.object(rs, "query_analyzer", analyzer),
        patch.object(rs, "search_agent", search_agent),
        patch.object(rs, "relevance_filter", None),
        patch.object(rs, "_hybrid_ranker", None),
        patch.object(rs, "_get_cached_result", return_value=None),
        patch.object(rs, "_set_cache", return_value=None) as set_cache,
        patch("routers.search.json.dump", return_value=None),
    ):
        resp = await client.post(
            "/api/search",
            json={
                "query": "transformer",
                "sources": ["arxiv"],
                "fast_mode": True,
                "save_papers": False,
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cache_hit"] is False
    assert body["quality_mode"] == "fast"
    assert body["source_timings"] == {"arxiv": 0.012}
    assert body["source_timeouts"] == {"arxiv": False}
    assert body["stage_modes"]["source_modes"] == {"arxiv": "searched"}
    assert body["metadata"]["source_timings"] == {"arxiv": 0.012}
    assert body["metadata"]["source_timeouts"] == {"arxiv": False}
    assert body["stage_modes"]["academic_guard_passed"] is True
    assert set_cache.call_args.kwargs["academic_guard_passed"] is True


def _runtime_policy_text() -> str:
    from pathlib import Path

    return Path("docs/skillopt_search/baseline_skill.md").read_text(encoding="utf-8")


def test_search_cache_key_separates_skillopt_policy_namespace():
    """Full search-result cache keys must differ for baseline vs SkillOpt policy hash."""
    from routers import search as rs

    base_filters = {
        "sort_by": "relevance",
        "year_start": None,
        "year_end": None,
        "author": None,
        "category": None,
        "fast_mode": False,
    }
    baseline_key = rs._compute_cache_key(
        "graph rag", ["arxiv"], {**base_filters, "skillopt_policy": "baseline"}
    )
    policy_key = rs._compute_cache_key(
        "graph rag", ["arxiv"], {**base_filters, "skillopt_policy": "sha256:" + "a" * 64}
    )

    assert baseline_key != policy_key


def test_skillopt_result_cache_namespace_uses_validated_hash(monkeypatch, tmp_path):
    """Router-level cache namespace is the validated policy hash only on explicit opt-in."""
    import hashlib
    from routers import search as rs
    from app.QueryAgent.skillopt_policy import (
        SKILLOPT_POLICY_ENABLED_ENV,
        SKILLOPT_POLICY_HASH_ENV,
        SKILLOPT_POLICY_PATH_ENV,
    )

    content = _runtime_policy_text()
    path = tmp_path / "policy.md"
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    monkeypatch.setenv(SKILLOPT_POLICY_ENABLED_ENV, "true")
    monkeypatch.setenv(SKILLOPT_POLICY_PATH_ENV, str(path))
    monkeypatch.setenv(SKILLOPT_POLICY_HASH_ENV, f"sha256:{digest}")

    assert rs._skillopt_result_cache_namespace(apply_skillopt_policy=True) == f"sha256:{digest}"
    assert rs._skillopt_result_cache_namespace(apply_skillopt_policy=False) == "baseline"


def test_invalid_skillopt_result_cache_namespace_fails_closed(monkeypatch, tmp_path, caplog):
    """Invalid runtime policy config must use the baseline cache namespace, not a stale candidate key."""
    import logging
    from routers import search as rs
    from app.QueryAgent.skillopt_policy import (
        SKILLOPT_POLICY_ENABLED_ENV,
        SKILLOPT_POLICY_HASH_ENV,
        SKILLOPT_POLICY_PATH_ENV,
    )

    content = _runtime_policy_text()
    path = tmp_path / "policy.md"
    path.write_text(content, encoding="utf-8")

    monkeypatch.setenv(SKILLOPT_POLICY_ENABLED_ENV, "true")
    monkeypatch.setenv(SKILLOPT_POLICY_PATH_ENV, str(path))
    monkeypatch.setenv(SKILLOPT_POLICY_HASH_ENV, "sha256:" + "0" * 64)

    with caplog.at_level(logging.WARNING, logger="routers.search"):
        namespace = rs._skillopt_result_cache_namespace(apply_skillopt_policy=True)

    assert namespace == "baseline"
    assert any("SkillOpt search policy excluded" in rec.message for rec in caplog.records)
