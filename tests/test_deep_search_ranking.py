"""Deep search must rank and deduplicate like the standard search path.

Both deep-search endpoints used to return whatever order the ReAct turns
appended in, with no cross-source dedup — so the same paper found by two turns
appeared twice, and none of the ranking signals ran. The two entry points
disagreed about what "best" means while looking equally authoritative.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import routers.search as rs


def _papers():
    """Two duplicates of one paper plus two others, in a deliberately bad order."""
    return [
        {"title": "Attention Is All You Need", "abstract": "transformer", "doi": "10.1/a",
         "year": 2017, "citations": 90000, "_source": "arxiv"},
        {"title": "Some Unrelated Paper", "abstract": "unrelated topic", "doi": "10.2/b",
         "year": 2001, "citations": 1, "_source": "openalex"},
        # Same DOI as the first — a second turn found it again.
        {"title": "Attention Is All You Need", "abstract": "transformer", "doi": "10.1/a",
         "year": 2017, "citations": 90000, "_source": "openalex"},
        {"title": "Transformer Survey", "abstract": "attention survey", "doi": "10.3/c",
         "year": 2023, "citations": 50, "_source": "dblp"},
    ]


@pytest.mark.asyncio
async def test_duplicates_are_collapsed():
    ranked = await rs._dedup_and_rank_deep_search("attention", _papers(), "paper_search")

    dois = [p.get("doi") for p in ranked]
    assert len(dois) == len(set(dois)), f"duplicate papers survived: {dois}"
    assert len(ranked) == 3


@pytest.mark.asyncio
async def test_papers_carry_a_total_rank_order():
    ranked = await rs._dedup_and_rank_deep_search("attention", _papers(), "paper_search")

    ranks = [p["_rank"] for p in ranked]
    assert ranks == list(range(len(ranked))), f"_rank is not a total order: {ranks}"


@pytest.mark.asyncio
async def test_ranking_reorders_rather_than_preserving_arrival_order():
    """The whole point: the returned order must come from the signals."""
    papers = [
        {"title": "Barely related note", "abstract": "n/a", "doi": "10.9/z",
         "year": 1998, "citations": 0, "_source": "arxiv"},
        {"title": "Attention Is All You Need", "abstract": "transformer attention",
         "doi": "10.1/a", "year": 2017, "citations": 90000, "_source": "openalex"},
    ]
    ranked = await rs._dedup_and_rank_deep_search("attention transformer", papers, "paper_search")

    assert ranked[0]["doi"] == "10.1/a", (
        "the strong match did not reach the top — ranking is not running"
    )


@pytest.mark.asyncio
async def test_ranker_failure_still_returns_papers_in_a_stamped_order():
    """Deep search is slow; an unranked answer must beat no answer."""
    broken = MagicMock()
    broken.rank_papers.side_effect = RuntimeError("ranker exploded")

    with patch.object(rs, "_hybrid_ranker", broken):
        ranked = await rs._dedup_and_rank_deep_search("attention", _papers(), "paper_search")

    assert len(ranked) == 3, "papers were lost when ranking failed"
    assert [p["_rank"] for p in ranked] == [0, 1, 2]


@pytest.mark.asyncio
async def test_missing_ranker_does_not_break_the_path():
    with patch.object(rs, "_hybrid_ranker", None):
        ranked = await rs._dedup_and_rank_deep_search("attention", _papers(), "paper_search")

    assert len(ranked) == 3
    assert all("_rank" in p for p in ranked)


@pytest.mark.asyncio
async def test_empty_result_is_passed_through():
    assert await rs._dedup_and_rank_deep_search("attention", [], "paper_search") == []
