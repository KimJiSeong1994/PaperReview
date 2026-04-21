"""US-013: SOURCE_BOOST scale calibration for RRF ranking.

Pre-US-013 SOURCE_BOOST["arxiv"] = 0.15 overwhelmed RRF fusion scores
(typical range 0.01-0.08 for 5 signals), causing arXiv papers to always
dominate top-K regardless of actual signal quality.

These tests assert the new calibrated values stay within RRF scale.
"""
from __future__ import annotations


def test_source_boost_does_not_dominate_rrf() -> None:
    """arxiv boost should adjust ranks by ~3-5 positions, not overwhelm.

    RRF signal contribution at rank 10: 1/(60+10) ≈ 0.0143.
    Boost must stay below 0.01 (< 1 full signal at rank 10).
    """
    from src.graph_rag.hybrid_ranker import SOURCE_BOOST

    arxiv_boost = SOURCE_BOOST.get("arxiv", 0)
    assert arxiv_boost > 0, "arxiv should still receive a small positive boost"
    assert arxiv_boost < 0.01, (
        f"arxiv boost {arxiv_boost} is too large for RRF score range ~0.01-0.08; "
        "it would dominate fusion scores and ignore signal quality"
    )


def test_source_boost_within_rrf_scale() -> None:
    """All source boosts must be within RRF signal magnitude at rank 10.

    One RRF signal at rank 10: 1/(60+10) ≈ 0.0143.
    MAX_BOOST = 0.01 keeps any single source boost below that threshold.
    """
    from src.graph_rag.hybrid_ranker import SOURCE_BOOST

    MAX_BOOST = 0.01
    for source, boost in SOURCE_BOOST.items():
        assert abs(boost) <= MAX_BOOST, (
            f"source '{source}' boost {boost} exceeds RRF scale limit {MAX_BOOST}; "
            "calibrate to be proportional to one signal contribution"
        )


def test_non_arxiv_paper_can_outrank_arxiv_with_better_signal() -> None:
    """A non-arXiv paper with significantly better RRF signal should beat arXiv.

    Simulates two papers: non-arxiv ranked #1 across all signals vs arXiv ranked #5.
    With old boost (0.15) arXiv always won; with new boost (0.003) signal wins.
    """
    from src.graph_rag.hybrid_ranker import SOURCE_BOOST, RRF_K

    # Non-arXiv paper: ranked 1st in all signals → maximum RRF score
    # 5 signals × 1/(60+1) ≈ 0.082
    signals = 5
    non_arxiv_rrf = signals * (1.0 / (RRF_K + 1))
    non_arxiv_final = non_arxiv_rrf  # no source boost

    # arXiv paper: ranked 5th across all signals + source boost
    # 5 signals × 1/(60+5) ≈ 0.077
    arxiv_rrf = signals * (1.0 / (RRF_K + 5))
    arxiv_final = arxiv_rrf + SOURCE_BOOST.get("arxiv", 0.0)

    assert non_arxiv_final > arxiv_final, (
        f"Non-arXiv (rank 1, score {non_arxiv_final:.6f}) should beat "
        f"arXiv (rank 5, score {arxiv_final:.6f}) when signal quality is clearly better. "
        f"arxiv boost={SOURCE_BOOST.get('arxiv')} may still be too large."
    )
