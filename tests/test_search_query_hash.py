"""query_hash must reach the client on every /api/search response path.

A click can only be joined to its search if the browser was given the hash.
The endpoint returns from several branches (cache fast path, non-academic
guard, cached-after-guard, normal, partial-on-timeout); a branch that omits
the field silently drops every click made from those results.
"""
from unittest.mock import MagicMock, patch

import pytest

from routers.search import _query_hash


def test_query_hash_is_stable_and_short():
    assert _query_hash("graph neural networks") == _query_hash("graph neural networks")
    assert _query_hash("a") != _query_hash("b")
    assert len(_query_hash("x")) == 12


@pytest.mark.asyncio
async def test_cache_fast_path_returns_query_hash(client):
    from routers import search as rs

    cached = {"arxiv": [{"title": "Cached", "authors": [], "abstract": "", "source": "arxiv"}]}
    with (
        patch.object(rs, "_get_cached_result", return_value=cached),
        patch.object(rs, "_set_cache", return_value=None),
    ):
        resp = await client.post(
            "/api/search",
            json={"query": "machine learning", "fast_mode": True, "save_papers": False},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["query_hash"] == _query_hash("machine learning")


@pytest.mark.asyncio
async def test_non_academic_guard_returns_query_hash(client):
    """The guard short-circuits early; it must still identify the search."""
    from routers import search as rs

    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {
        "is_academic": False,
        "original_query": "weather today",
    }
    with (
        patch.object(rs, "query_analyzer", analyzer),
        patch.object(rs, "_get_cached_result", return_value=None),
        patch.object(rs, "_set_cache", return_value=None),
    ):
        resp = await client.post(
            "/api/search",
            json={"query": "weather today", "fast_mode": True, "save_papers": False},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["query_hash"] == _query_hash("weather today")


def test_every_search_response_constructor_sets_query_hash():
    """Guard against a new return branch forgetting the field."""
    import ast
    import inspect
    import textwrap

    from routers import search as rs

    tree = ast.parse(textwrap.dedent(inspect.getsource(rs.search_papers)))
    constructors = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "SearchResponse"
    ]
    assert constructors, "no SearchResponse(...) found — update this test"
    missing = [node for node in constructors if not any(keyword.arg == "query_hash" for keyword in node.keywords)]
    assert not missing, f"{len(missing)} SearchResponse branch(es) omit query_hash"
