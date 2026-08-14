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

from unittest.mock import patch

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
    assert rs._skillopt_result_cache_namespace(apply_skillopt_policy=False)[0] == (
        rs._skillopt_result_cache_namespace(apply_skillopt_policy=True)[0]
    ), "precondition: both pipelines share the SkillOpt namespace when policy is off"
    assert _key(use_llm_search=True) != _key(use_llm_search=False)


def test_cache_key_still_separates_existing_dimensions():
    """The added fields must not have clobbered what already worked."""
    assert _key(fast_mode=True) != _key(fast_mode=False)
    assert _key(year_start=2020) != _key(year_start=None)
    assert _key() == _key(), "key must be deterministic"


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
    # Cross-encoder ranks the papers in exactly reverse order of the
    # citation/recency heuristics, so a dominant weight is unmistakable.
    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=lambda q, ps: [0.1 * (i + 1) for i in range(len(ps))],
    ):
        ranked = HybridRanker().rank_papers(
            query="attention parity", papers=list(papers), use_rrf=True
        )

    assert ranked[0]["title"] != "paper 3", (
        "the cross-encoder's pick won outright against every other signal — "
        f"it is dominating the fusion at weight {CROSS_ENCODER_RRF_WEIGHT}"
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
    assert breakdown["rrf_bm25"] > 0.0, "the remaining signals must still fuse"


def test_cross_encoder_weight_can_be_overridden_per_call():
    """The offline sweep varies the weight without mutating the global constant.

    Sweeping by monkeypatching the module constant would race any concurrent
    search, so the ranker takes the weight as an argument.
    """
    scores = [0.1 * (i + 1) for i in range(4)]

    def _ranked_titles(weight):
        with patch(
            "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
            side_effect=lambda q, ps: scores[: len(ps)],
        ):
            _ce_cache_clear()
            ranked = HybridRanker().rank_papers(
                query="override probe",
                papers=_rankable(4),
                use_rrf=True,
                cross_encoder_weight=weight,
            )
        return [p["title"] for p in ranked]

    assert _ranked_titles(0.0) != _ranked_titles(50.0), (
        "cross_encoder_weight had no effect — the sweep would compare identical rankings"
    )
    assert CROSS_ENCODER_RRF_WEIGHT == 0.0, "override must not change the default"


def test_cross_encoder_weight_matches_the_rrf_contribution():
    """The weight is applied to the RRF term, not to the raw score."""
    papers = _rankable(3)
    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=lambda q, ps: [0.9, 0.5, 0.1],
    ):
        ranked = HybridRanker().rank_papers(
            query="attention", papers=list(papers), use_rrf=True
        )

    top = next(p for p in ranked if p["title"] == "paper 0")
    # The breakdown is rounded to 6 decimals, so compare with that absolute
    # tolerance rather than a relative one.
    assert top["_score_breakdown"]["rrf_cross_encoder"] == pytest.approx(
        CROSS_ENCODER_RRF_WEIGHT / (RRF_K + 1), abs=1e-6
    )


def test_unavailable_cross_encoder_leaves_the_other_signals_alone():
    """No model → the signal drops out entirely, it does not score zero-weighted."""
    papers = _rankable(3)
    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=lambda q, ps: [],
    ):
        ranked = HybridRanker().rank_papers(
            query="attention", papers=list(papers), use_rrf=True
        )

    breakdown = ranked[0]["_score_breakdown"]
    assert breakdown["rrf_cross_encoder"] == 0.0
    assert breakdown["cross_encoder_weight"] == 0.0
    assert breakdown["rrf_bm25"] > 0.0, "other signals must still fuse"


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
            query="attention", papers=_rankable(5), use_rrf=True, cross_encoder_weight=1.0
        )

    assert calls == [5]
    assert not hasattr(rs, "relevance_filter"), (
        "routers.search regained a relevance filter — the second reranking "
        "pass (and its duplicate cross-encoder inference) is back"
    )
