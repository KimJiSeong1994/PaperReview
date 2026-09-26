import itertools
import math
import unittest
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

from src.recommendation_profiles import RecommendationProfile
from src.recommendation_ranker import (
    _freshness,
    minimum_score_for_mode,
    mmr_rerank,
    rank_paper_v2,
    reason_v2,
)
from src.utils.paper_utils import generate_result_key


class RecommendationRankerTests(unittest.TestCase):
    def rank(self, name, title="Graph Learning", score=None):
        item = rank_paper_v2(
            {"doi": f"10.1234/{name}", "title": title, "year": 2026},
            RecommendationProfile(),
            current_year=2026,
        )
        return (
            item
            if score is None
            else replace(item, score=score * 5, raw_score=score, normalized_score=score)
        )

    def test_private_terms_never_in_reason_or_matched_terms(self):
        profile = RecommendationProfile(
            positive_terms=Counter({"private_marker": 30}),
            query_terms=Counter({"private_marker": 4}),
        )
        item = rank_paper_v2(
            {"title": "private_marker", "doi": "10.1234/a"}, profile, current_year=2026
        )
        self.assertGreater(item.score_breakdown["interest_match"], 0)
        self.assertEqual(item.matched_terms, [])
        for fallback in (False, True):
            self.assertNotIn(
                "private_marker", reason_v2(item, fallback_recent=fallback)
            )
        self.assertNotIn("논문 품질 신호", item.reason_factors)

    def test_nonbibliographic_fields_do_not_influence_score(self):
        profile = RecommendationProfile(positive_terms=Counter({"private_marker": 50}))
        paper = {"title": "Graph learning", "year": 2020}
        baseline = rank_paper_v2(paper, profile, current_year=2026)
        poisoned = rank_paper_v2(
            {
                **paper,
                "search_query": "private_marker",
                "related_query": "private_marker",
                "notes": "private_marker",
                "related_review_score": 5,
            },
            profile,
            current_year=2026,
        )
        self.assertEqual(baseline.score, poisoned.score)
        self.assertEqual(baseline.score_breakdown, poisoned.score_breakdown)

    def test_finite_scores_and_publication_dates(self):
        for bad in (float("nan"), float("inf"), float("-inf"), "NaN", "invalid", None):
            item = rank_paper_v2(
                {"title": "Graph", "citation_count": bad, "year": bad},
                RecommendationProfile(positive_terms=Counter({"graph": float("inf")})),
                current_year=2026,
            )
            self.assertTrue(
                all(
                    math.isfinite(value)
                    for value in (
                        item.score,
                        item.raw_score,
                        item.normalized_score,
                        *item.score_breakdown.values(),
                    )
                )
            )
        self.assertEqual(
            _freshness({"published_date": "2027-01-01"}, current_year=2026), 0
        )
        self.assertEqual(
            _freshness(
                {"published_date": "2026-12-01"},
                current_year=2026,
                now=datetime(2026, 9, 25, tzinfo=timezone.utc),
            ),
            0,
        )
        self.assertEqual(
            _freshness({"year": 2000, "updated_date": "2026-01-01"}, current_year=2026),
            0,
        )
        self.assertEqual(
            _freshness(
                {"updated_date": "2026-01-01", "collected_at": "2026-01-01"},
                current_year=2026,
            ),
            0.15,
        )
        self.assertEqual(
            _freshness({"published_date": "2026-99-99"}, current_year=2026), 0.15
        )

    def test_id_only_negative_and_positive(self):
        paper = {"doi": "https://doi.org/10.1234/A", "title": "Graph learning"}
        key = generate_result_key(paper)
        neutral = rank_paper_v2(paper, RecommendationProfile(), current_year=2026)
        positive = rank_paper_v2(
            paper, RecommendationProfile(positive_paper_ids={key}), current_year=2026
        )
        negative = rank_paper_v2(
            paper, RecommendationProfile(negative_paper_ids={key}), current_year=2026
        )
        self.assertGreater(positive.raw_score, neutral.raw_score)
        self.assertLess(negative.raw_score, neutral.raw_score)

    def test_canonical_ties_permutations_and_mmr_order_not_score_order(self):
        tied = [self.rank(name, score=0.9) for name in ("c", "a", "b")]
        expected = ["doi:10.1234/a", "doi:10.1234/b", "doi:10.1234/c"]
        for permutation in itertools.permutations(tied):
            self.assertEqual(
                [
                    generate_result_key(item.paper)
                    for item in mmr_rerank(list(permutation), limit=3)
                ],
                expected,
            )
        a = self.rank("a", "Graph Neural Learning", 0.95)
        b = self.rank("b", "Graph Neural Learning", 0.94)
        c = self.rank("c", "Ocean Climate Forecast", 0.85)
        selected = mmr_rerank([b, c, a], limit=3)
        self.assertEqual(
            [item.paper["doi"] for item in selected],
            [a.paper["doi"], c.paper["doi"], b.paper["doi"]],
        )
        self.assertLess(selected[1].score, selected[2].score)

    def test_shortlist_floor_no_fill_and_cached_features(self):
        high = self.rank("high", score=0.9)
        low = self.rank("low", score=0.1)
        self.assertEqual(len(mmr_rerank([low, high], limit=12)), 1)
        self.assertEqual(mmr_rerank([high], limit=-1), [])
        invalid = replace(high, normalized_score=float("nan"))
        self.assertEqual(mmr_rerank([invalid], limit=1), [])
        many = [self.rank(str(number), score=0.9) for number in range(205)]
        with patch(
            "src.recommendation_ranker._paper_terms",
            side_effect=AssertionError("cached features required"),
        ):
            self.assertEqual(len(mmr_rerank(many, limit=250)), 200)
        self.assertEqual(len(mmr_rerank([high, high], limit=2)), 1)

    def test_thresholds_are_mode_specific(self):
        self.assertEqual(minimum_score_for_mode("v1", v1_min_score=12), 12)
        self.assertEqual(minimum_score_for_mode("v2", v1_min_score=12), 0)
        self.assertEqual(
            minimum_score_for_mode("v2", v1_min_score=12, v2_min_score=1.2), 1.2
        )
        with self.assertRaises(ValueError):
            minimum_score_for_mode("v2", v1_min_score=12, v2_min_score=float("nan"))


if __name__ == "__main__":
    unittest.main()
