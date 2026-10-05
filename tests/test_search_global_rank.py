"""Guards for the ranking order actually reaching the client.

The API returns papers grouped by source (``Dict[source, papers]``). A client
that iterates those buckets sees every arXiv hit, then every Scholar hit, and
never the cross-source ranking — which is how the whole ranking stack (RRF,
HyDE, cross-encoder) stayed invisible on screen. ``_rank`` is the field that
carries the fused order across the bucketing and the result cache, so these
tests pin it, the cache-key fields that were letting one request's answer serve
another, and the cross-encoder weight that replaced the second reranking pass.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import routers.search as rs
from src.graph_rag.hybrid_ranker import (
    CROSS_ENCODER_RRF_WEIGHT,
    RRF_K,
    HybridRanker,
    _ce_cache_clear,
)


@pytest.fixture(autouse=True)
def _isolate_cross_encoder_cache():
    """Drop the process-global cross-encoder cache around every test.

    ``_CE_CACHE`` is keyed by (query_hash, paper_id) with a 1h TTL and lives at
    module scope — intended in production, but it means one test's scores are
    served to the next test that reuses a query or paper id, silently masking
    whatever that test meant to assert.
    """
    _ce_cache_clear()
    yield
    _ce_cache_clear()


# ── _stamp_global_rank ────────────────────────────────────────────────


def test_stamp_global_rank_numbers_the_fused_order():
    """Ranked papers get 0..n-1 in fused order regardless of their bucket."""
    a, b, c = {"title": "a"}, {"title": "b"}, {"title": "c"}
    # Ranker put b first even though it lives in the second bucket.
    ranked = [b, a, c]
    results = {"arxiv": [a, c], "openalex": [b]}

    rs._stamp_global_rank(ranked, results)

    assert [p["_rank"] for p in ranked] == [0, 1, 2]
    assert b["_rank"] < a["_rank"] < c["_rank"]


def test_stamp_global_rank_puts_unranked_papers_last():
    """Papers the ranker never saw stay in the response but sort after it.

    Ranking is capped at ``_MAX_RANKING_CANDIDATES``, and degraded paths skip
    it entirely. Those papers must not silently jump the queue by having no
    rank at all.
    """
    ranked_one = {"title": "ranked"}
    tail_one, tail_two = {"title": "tail1"}, {"title": "tail2"}
    results = {"arxiv": [ranked_one, tail_one], "dblp": [tail_two]}

    rs._stamp_global_rank([ranked_one], results)

    assert ranked_one["_rank"] == 0
    assert {tail_one["_rank"], tail_two["_rank"]} == {1, 2}


def test_stamp_global_rank_is_a_total_order():
    """Every paper in the response gets exactly one distinct rank."""
    papers = [{"title": f"p{i}"} for i in range(6)]
    results = {"arxiv": papers[:2], "openalex": papers[2:4], "dblp": papers[4:]}

    rs._stamp_global_rank(papers[3:] + papers[:1], results)

    ranks = sorted(p["_rank"] for p in papers)
    assert ranks == list(range(6))


# ── cache key ─────────────────────────────────────────────────────────


def _key(**overrides):
    filters = {
        "sort_by": "relevance",
        "year_start": None,
        "year_end": None,
        "author": None,
        "category": None,
        "fast_mode": False,
        "max_results": 20,
        "use_llm_search": False,
        "skillopt_policy": "baseline",
    }
    filters.update(overrides)
    return rs._compute_cache_key("graph neural network", ["arxiv"], filters)


def test_cache_key_separates_max_results():
    """A body cached for 10 results is a truncated answer for 50."""
    assert _key(max_results=10) != _key(max_results=50)


def test_cache_key_separates_llm_search_pipeline():
    """use_llm_search selects a different pipeline; both map to the
    'baseline' SkillOpt namespace while the policy is off, so the key itself
    has to distinguish them."""
    assert (
        rs._skillopt_result_cache_namespace(apply_skillopt_policy=False)[0]
        == (rs._skillopt_result_cache_namespace(apply_skillopt_policy=True)[0])
    ), "precondition: both pipelines share the SkillOpt namespace when policy is off"
    assert _key(use_llm_search=True) != _key(use_llm_search=False)


def test_cache_key_still_separates_existing_dimensions():
    """The added fields must not have clobbered what already worked."""
    assert _key(fast_mode=True) != _key(fast_mode=False)
    assert _key(year_start=2020) != _key(year_start=None)
    assert _key() == _key(), "key must be deterministic"


def _mock_api_search(monkeypatch, papers):
    analyzer = MagicMock()
    analyzer.analyze_and_prepare.return_value = {
        "intent": "paper_search",
        "confidence": 0.5,
        "is_academic": True,
    }
    agent = MagicMock()
    agent.deduplicator.deduplicate.side_effect = lambda values: values

    async def search(_query, _filters):
        return {"arxiv": list(papers)}

    agent.async_search_with_filters.side_effect = search
    ranker = MagicMock()
    ranker.rank_papers.side_effect = lambda **kwargs: list(kwargs["papers"])
    jev = AsyncMock(
        return_value=(
            list(papers),
            {
                "mode": "disabled_no_api_key",
                "model": None,
                "scored_count": 0,
            },
        )
    )
    monkeypatch.setattr(rs, "query_analyzer", analyzer)
    monkeypatch.setattr(rs, "search_agent", agent)
    monkeypatch.setattr(rs, "_hybrid_ranker", ranker)
    monkeypatch.setattr(rs, "_graphrag_expand", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(rs, "get_openai_client", lambda: None)
    monkeypatch.setattr(rs, "rerank_papers", jev)
    monkeypatch.setattr(rs, "_get_cached_result", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rs, "_set_cache", MagicMock())
    monkeypatch.setattr(rs, "_persist_last_search", MagicMock())
    return ranker, jev


@pytest.mark.asyncio
async def test_search_api_jev_order_is_stamped_and_restored_from_warm_cache(
    monkeypatch, tmp_path
):
    get_cached_result = rs._get_cached_result
    set_cache = rs._set_cache
    papers = [
        {"title": "a", "abstract": "abstract a", "doi": "10.1234/a"},
        {"title": "b", "abstract": "abstract b", "doi": "10.1234/b"},
        {"title": "c", "abstract": "abstract c", "doi": "10.1234/c"},
    ]
    ranker, jev = _mock_api_search(monkeypatch, papers)
    monkeypatch.setattr(rs, "_search_cache", {})
    monkeypatch.setattr(rs, "SEARCH_CACHE_DIR", tmp_path)
    monkeypatch.setattr(rs, "_get_cached_result", get_cached_result)
    monkeypatch.setattr(rs, "_set_cache", set_cache)
    monkeypatch.setattr(rs, "ranking_cache_variant", lambda: "jev-key-present-v1")

    def hybrid_rank(**kwargs):
        by_title = {paper["title"]: paper for paper in kwargs["papers"]}
        return [by_title[title] for title in ("c", "a", "b")]

    ranker.rank_papers.side_effect = hybrid_rank

    async def jev_rerank(query, values, *, deadline, stop_event):
        assert query == "topic warm cache"
        assert deadline is not None
        assert isinstance(stop_event, threading.Event)
        by_title = {paper["title"]: paper for paper in values}
        return [by_title[title] for title in ("a", "c", "b")], {
            "mode": "completed",
            "model": "mock-jev",
            "scored_count": 3,
        }

    jev.side_effect = jev_rerank
    emitted = []
    monkeypatch.setattr(rs, "emit_or_warn", emitted.append)
    principal = SimpleNamespace(username="reader", account_incarnation="inc-1")
    http_request = SimpleNamespace(
        state=SimpleNamespace(authenticated_principal=principal),
        is_disconnected=AsyncMock(return_value=False),
    )
    request = rs.SearchRequest(
        query="topic warm cache",
        sources=["arxiv"],
        save_papers=False,
    )

    first = await rs.search_papers(request, "reader", http_request)
    first_by_rank = sorted(first.results["arxiv"], key=lambda paper: paper["_rank"])
    assert [paper["title"] for paper in first_by_rank] == ["a", "c", "b"]
    assert [paper["_rank"] for paper in first_by_rank] == [0, 1, 2]
    assert first.stage_modes["ranking_mode"] == "hybrid_rrf_jev"
    assert first.stage_modes["jev_mode"] == "completed"
    assert first.stage_modes["scored_count"] == 3
    assert first.stage_modes["ranking_variant"] == ("ce_w=0.0;jev=jev-key-present-v1")
    assert emitted[0].payload["ranking_applied"] is True
    assert emitted[0].payload["ranking_variant"] == first.stage_modes["ranking_variant"]
    assert emitted[0].payload["jev_mode"] == "completed"
    assert emitted[0].payload["scored_count"] == 3

    warm = await rs.search_papers(request, None)
    warm_by_rank = sorted(warm.results["arxiv"], key=lambda paper: paper["_rank"])
    assert warm.cache_hit is True
    assert [paper["title"] for paper in warm_by_rank] == ["a", "c", "b"]
    assert warm.stage_modes["ranking_mode"] == "hybrid_rrf_jev"
    assert warm.stage_modes["jev_mode"] == "completed"
    assert warm.stage_modes["scored_count"] == 3
    assert warm.stage_modes["ranking_variant"] == first.stage_modes["ranking_variant"]
    ranker.rank_papers.assert_called_once()
    jev.assert_awaited_once()


@pytest.mark.asyncio
async def test_jev_timeout_keeps_hybrid_order_and_is_not_cached(monkeypatch, tmp_path):
    papers = [
        {"title": title, "abstract": f"abstract {title}", "doi": f"10.1234/{title}"}
        for title in ("a", "b", "c")
    ]
    ranker, jev = _mock_api_search(monkeypatch, papers)
    monkeypatch.setattr(rs, "_search_cache", {})
    monkeypatch.setattr(rs, "SEARCH_CACHE_DIR", tmp_path)

    def hybrid_rank(**kwargs):
        by_title = {paper["title"]: paper for paper in kwargs["papers"]}
        return [by_title[title] for title in ("c", "a", "b")]

    ranker.rank_papers.side_effect = hybrid_rank

    async def failed_jev(_query, values, **_kwargs):
        return list(reversed(values)), {
            "mode": "fallback_timeout",
            "model": "mock-jev",
            "scored_count": 0,
        }

    jev.side_effect = failed_jev
    response = await rs.search_papers(
        rs.SearchRequest(
            query="topic timeout",
            sources=["arxiv"],
            save_papers=False,
        ),
        None,
    )
    by_rank = sorted(response.results["arxiv"], key=lambda paper: paper["_rank"])
    assert [paper["title"] for paper in by_rank] == ["c", "a", "b"]
    assert response.stage_modes["jev_mode"] == "fallback_timeout"
    assert response.stage_modes["ranking_mode"] == "hybrid_rrf"
    assert response.stage_modes["ranking_variant"] == "ce_w=0.0"
    rs._set_cache.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,fast_mode,sort_by,expected_mode,ranker_runs",
    [
        ("10.1234/exact", False, "relevance", "skipped_identity_route", True),
        ("topic search", True, "relevance", "skipped_fast_mode", True),
        (
            "topic search",
            False,
            "submittedDate",
            "skipped_non_relevance_sort",
            False,
        ),
    ],
)
async def test_search_skips_jev_for_exact_fast_and_date_sort(
    monkeypatch,
    query,
    fast_mode,
    sort_by,
    expected_mode,
    ranker_runs,
):
    papers = [
        {
            "title": "Older",
            "abstract": "abstract",
            "doi": "10.1234/older",
            "published_date": "2020-01-01",
        },
        {
            "title": "Newer",
            "abstract": "abstract",
            "doi": "10.1234/newer",
            "published_date": "2025-01-01",
        },
    ]
    ranker, jev = _mock_api_search(monkeypatch, papers)
    response = await rs.search_papers(
        rs.SearchRequest(
            query=query,
            sources=["arxiv"],
            fast_mode=fast_mode,
            sort_by=sort_by,
            save_papers=False,
        ),
        None,
    )
    assert response.stage_modes["jev_mode"] == expected_mode
    jev.assert_not_awaited()
    assert ranker.rank_papers.call_count == int(ranker_runs)
    if sort_by == "submittedDate":
        assert [paper["title"] for paper in response.results["arxiv"]] == [
            "Newer",
            "Older",
        ]


@pytest.mark.asyncio
async def test_deep_search_jev_reorders_before_global_rank(monkeypatch):
    papers = [
        {"title": "first", "abstract": "abstract first", "doi": "10.1234/1"},
        {"title": "second", "abstract": "abstract second", "doi": "10.1234/2"},
    ]
    agent = MagicMock()
    agent.deduplicator.deduplicate.side_effect = lambda values: values
    monkeypatch.setattr(rs, "search_agent", agent)
    ranker = MagicMock()
    ranker.rank_papers.side_effect = lambda **kwargs: list(kwargs["papers"])
    monkeypatch.setattr(rs, "_hybrid_ranker", ranker)
    monkeypatch.setattr(rs, "ranking_cache_variant", lambda: "jev-key-present-v1")

    async def jev_rerank(query, values, *, deadline, stop_event):
        assert query == "topic deep search"
        assert deadline == requested_deadline
        assert stop_event is stop
        return list(reversed(values)), {
            "mode": "completed",
            "model": "mock-jev",
            "scored_count": 2,
        }

    monkeypatch.setattr(rs, "rerank_papers", jev_rerank)
    requested_deadline = asyncio.get_running_loop().time() + 10
    # The router's absolute deadline uses time.monotonic(), which shares the
    # event loop's monotonic clock on supported asyncio implementations.
    stop = threading.Event()
    metadata = {}
    ranked = await rs._dedup_and_rank_deep_search(
        "topic deep search",
        papers,
        "paper_search",
        deadline=requested_deadline,
        stop_event=stop,
        metadata=metadata,
    )
    assert [paper["title"] for paper in ranked] == ["second", "first"]
    assert [paper["_rank"] for paper in ranked] == [0, 1]
    assert [paper["result_key"] for paper in ranked] == [
        "doi:10.1234/2",
        "doi:10.1234/1",
    ]
    assert metadata["jev_mode"] == "completed"
    assert metadata["ranking_mode"] == "hybrid_rrf_jev"
    assert metadata["scored_count"] == 2


# ── weighted RRF ──────────────────────────────────────────────────────


def _rankable(n: int):
    return [
        {
            "title": f"paper {i}",
            "abstract": "attention transformers",
            "paper_id": f"p{i}",
            "year": 2024,
            "citations": i,
        }
        for i in range(n)
    ]


def test_cross_encoder_does_not_dominate_the_fusion():
    """No signal may outvote the rest — the old second stage effectively did.

    The removed RelevanceFilter sorted the head of every result list by the
    cross-encoder alone. Measured against the labelled benchmark, with the
    dense signal both on and off, that costs nDCG@10 and Recall: ms-marco-MiniLM
    ranks by query-phrase restatement rather than by which paper is canonical.
    """
    assert CROSS_ENCODER_RRF_WEIGHT <= 1.0, (
        "a cross-encoder weight above parity regressed the benchmark sweep; "
        "raise it only with a measurement that says otherwise"
    )

    papers = _rankable(4)
    for i, paper in enumerate(papers):
        paper["year"] = datetime.now().year - (12, 7, 4, 0)[i]
    # Cross-encoder ranks the papers in exactly reverse order of the
    # citation/recency heuristics, so a dominant weight is unmistakable.
    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=lambda q, ps: [0.4 - 0.1 * int(p["paper_id"][1:]) for p in ps],
    ):
        ranked = HybridRanker().rank_papers(
            query="attention parity",
            papers=list(papers),
            use_rrf=True,
            cross_encoder_weight=1.0,
        )

    assert ranked[0]["title"] == "paper 3"
    for paper in ranked:
        i = int(paper["paper_id"][1:])
        assert paper["_hybrid_score"] == pytest.approx(
            2 / (RRF_K + 4 - i) + 1 / (RRF_K + i + 1)
        )


def test_zero_weight_skips_cross_encoder_inference():
    """A signal weighted 0 must not cost a model pass on every search.

    The benchmark put the weight at 0, so the scoring call is pure latency:
    tens of candidates through a transformer whose output is then multiplied
    by zero.
    """
    calls: list[int] = []

    def _counting(query, ps):
        calls.append(len(ps))
        return [0.5] * len(ps)

    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=_counting,
    ):
        ranked = HybridRanker().rank_papers(
            query="zero weight probe",
            papers=_rankable(5),
            use_rrf=True,
            cross_encoder_weight=0.0,
        )

    assert calls == [], "cross-encoder ran despite contributing nothing"
    breakdown = ranked[0]["_score_breakdown"]
    assert breakdown["rrf_cross_encoder"] == 0.0
    assert breakdown["cross_encoder_weight"] == 0.0
    assert breakdown["excluded_signals"]["bm25"] == "constant"
    assert breakdown["rrf_bm25"] == 0.0
    assert ranked[0]["title"] == "paper 4"
    for rank, paper in enumerate(ranked, 1):
        assert paper["_hybrid_score"] == pytest.approx(1 / (RRF_K + rank))


def test_cross_encoder_weight_can_be_overridden_per_call():
    """The offline sweep varies the weight without mutating the global constant.

    Sweeping by monkeypatching the module constant would race any concurrent
    search, so the ranker takes the weight as an argument.
    """

    def _ranked_titles(weight):
        with patch(
            "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
            side_effect=lambda q, ps: [0.4 - 0.1 * int(p["paper_id"][1:]) for p in ps],
        ):
            _ce_cache_clear()
            ranked = HybridRanker().rank_papers(
                query="override probe",
                papers=_rankable(4),
                use_rrf=True,
                cross_encoder_weight=weight,
            )
        for paper in ranked:
            i = int(paper["paper_id"][1:])
            assert paper["_hybrid_score"] == pytest.approx(
                1 / (RRF_K + 4 - i) + weight / (RRF_K + i + 1)
            )
        return [p["title"] for p in ranked]

    assert _ranked_titles(0.0) == ["paper 3", "paper 2", "paper 1", "paper 0"]
    assert _ranked_titles(50.0) == ["paper 0", "paper 1", "paper 2", "paper 3"]
    assert CROSS_ENCODER_RRF_WEIGHT == 0.0, "override must not change the default"


def test_cross_encoder_weight_matches_the_rrf_contribution():
    """The weight is applied to the RRF term, not to the raw score."""
    papers = _rankable(3)
    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=lambda q, ps: [0.9, 0.5, 0.1],
    ):
        ranked = HybridRanker().rank_papers(
            query="attention",
            papers=list(papers),
            use_rrf=True,
            cross_encoder_weight=0.5,
        )

    top = next(p for p in ranked if p["title"] == "paper 0")
    # The breakdown is rounded to 6 decimals, so compare with that absolute
    # tolerance rather than a relative one.
    assert top["_score_breakdown"]["rrf_cross_encoder"] == pytest.approx(
        0.5 / (RRF_K + 1), abs=1e-6
    )


def test_unavailable_cross_encoder_leaves_the_other_signals_alone():
    """No model → the signal drops out entirely, it does not score zero-weighted."""
    papers = _rankable(3)
    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=lambda q, ps: [],
    ) as scorer:
        ranked = HybridRanker().rank_papers(
            query="attention",
            papers=list(papers),
            use_rrf=True,
            cross_encoder_weight=1.0,
        )

    scorer.assert_called_once()
    breakdown = ranked[0]["_score_breakdown"]
    assert breakdown["rrf_cross_encoder"] == 0.0
    assert breakdown["cross_encoder_weight"] == 0.0
    assert breakdown["excluded_signals"]["cross_encoder"] == "unavailable"
    assert breakdown["excluded_signals"]["bm25"] == "constant"
    assert ranked[0]["title"] == "paper 2"
    for rank, paper in enumerate(ranked, 1):
        assert paper["_hybrid_score"] == pytest.approx(1 / (RRF_K + rank))


def test_cross_encoder_scored_once_per_ranking_pass():
    """Regression guard for the duplicate inference the second stage caused.

    The removed RelevanceFilter stage re-ran the same model over papers that
    already carried ``_cross_encoder_score`` from ranking. Two things pin that
    it cannot come back: the ranker itself scores once, and the search module
    no longer holds a relevance filter to call.

    Runs at an explicit non-zero weight — the shipped default is 0.0, where the
    correct number of passes is none (see the zero-weight test above).
    """
    calls: list[int] = []

    def _counting(query, ps):
        calls.append(len(ps))
        return [0.5] * len(ps)

    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=_counting,
    ):
        HybridRanker().rank_papers(
            query="attention",
            papers=_rankable(5),
            use_rrf=True,
            cross_encoder_weight=1.0,
        )

    assert calls == [5]
    assert not hasattr(rs, "relevance_filter"), (
        "routers.search regained a relevance filter — the second reranking "
        "pass (and its duplicate cross-encoder inference) is back"
    )
