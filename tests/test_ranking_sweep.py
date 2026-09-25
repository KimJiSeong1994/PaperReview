"""Tests for the offline ranking sweep (src/search_eval/ranking_sweep.py).

The sweep is what turned CROSS_ENCODER_RRF_WEIGHT from a guess into a measured
value, so the two things that would silently invalidate it are pinned here: the
candidate pool must be verifiably unedited, and every weight must see the same
untouched candidates.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.graph_rag.hybrid_ranker import _ce_cache_clear
from src.search_eval.ranking_sweep import (
    DEFAULT_DATASET,
    POOL_VERSION,
    _pool_hash,
    capture_candidate_pool,
    load_candidate_pool,
    score_pool_at_weight,
    sweep,
)
from src.search_eval.skillopt_contract import ValidationError, load_json


@pytest.fixture(autouse=True)
def _isolate_cross_encoder_cache():
    _ce_cache_clear()
    yield
    _ce_cache_clear()


@pytest.fixture
def fake_pool(tmp_path) -> Path:
    """A pool covering the real dataset's query ids with canned candidates."""
    dataset = load_json(str(DEFAULT_DATASET))
    candidates = {}
    for query in dataset["queries"]:
        labels = query["labels"]
        target = str(labels["must_include"][0])
        candidates[str(query["query_id"])] = [
            {"title": f"Unrelated filler {i}", "abstract": "noise", "year": 2019, "citations": i}
            for i in range(3)
        ] + [{"title": target, "abstract": target, "year": 2024, "citations": 900}]

    body = {
        "version": POOL_VERSION,
        "dataset_hash": dataset["dataset_hash"],
        "per_source": 5,
        "sources": ["arxiv"],
        "candidates": candidates,
        "capture_errors": {},
    }
    body["pool_hash"] = _pool_hash(body)
    path = tmp_path / "pool.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


# ── pool integrity ────────────────────────────────────────────────────


def test_pool_loads_when_untouched(fake_pool):
    pool = load_candidate_pool(fake_pool)
    assert pool["version"] == POOL_VERSION
    assert pool["candidates"]


def test_edited_pool_is_rejected(fake_pool):
    """A hand-edited pool would silently change what the sweep measured."""
    body = json.loads(fake_pool.read_text(encoding="utf-8"))
    first = next(iter(body["candidates"]))
    body["candidates"][first].append({"title": "smuggled", "abstract": "", "citations": 0})
    fake_pool.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValidationError, match="pool hash mismatch"):
        load_candidate_pool(fake_pool)


def test_pool_version_is_enforced(fake_pool):
    body = json.loads(fake_pool.read_text(encoding="utf-8"))
    body["version"] = "search-candidate-pool-v0"
    body["pool_hash"] = _pool_hash(body)
    fake_pool.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValidationError, match="version"):
        load_candidate_pool(fake_pool)


def test_capture_preserves_same_title_distinct_paper_identities(tmp_path, monkeypatch):
    class Source:
        def search(self, _query, max_results):
            return [
                {"title": "Shared title", "doi": "10.1234/first", "authors": ["A"]},
                {"title": "Shared title", "doi": "10.1234/second", "authors": ["B"]},
            ]

    for module, name in (
        ("src.collector.paper.arxiv_searcher", "ArxivSearcher"),
        ("src.collector.paper.dblp_searcher", "DBLPSearcher"),
        ("src.collector.paper.openalex_searcher", "OpenAlexSearcher"),
    ):
        monkeypatch.setattr(f"{module}.{name}", Source)
    pool = capture_candidate_pool(out_path=tmp_path / "captured.json")
    for papers in pool["candidates"].values():
        assert {paper["doi"] for paper in papers} == {"10.1234/first", "10.1234/second"}
        assert len(papers) == 2
        assert len({paper["result_key"] for paper in papers}) == 2
        assert all(paper["authors"] for paper in papers)


# ── sweep behaviour ───────────────────────────────────────────────────


def _fake_scores(_query, papers):
    return [0.1 * (i + 1) for i in range(len(papers))]


def test_sweep_reports_one_row_per_weight(fake_pool):
    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=_fake_scores,
    ):
        rows = sweep(weights=[0.0, 1.0, 4.0], pool_path=fake_pool)

    assert [row["cross_encoder_weight"] for row in rows] == [0.0, 1.0, 4.0]
    for row in rows:
        assert 0.0 <= row["nDCG@10"] <= 1.0
        assert 0.0 <= row["Recall@10"] <= 1.0


def test_each_weight_sees_untouched_candidates(fake_pool):
    """rank_papers annotates and sorts in place, so the pool must be copied.

    Without the copy, weight N would rank papers already carrying weight N-1's
    scores and ordering, and the comparison would measure nothing.
    """
    pool = load_candidate_pool(fake_pool)
    before = json.dumps(pool["candidates"], sort_keys=True)

    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=_fake_scores,
    ):
        score_pool_at_weight(pool=pool, cross_encoder_weight=4.0)

    assert json.dumps(pool["candidates"], sort_keys=True) == before, (
        "ranking mutated the candidate pool — later weights would not start clean"
    )


def test_sweep_output_is_measured_evidence(fake_pool):
    """The record must declare measured evidence bound to the pool hash.

    Fixture-mode records cannot authorize anything downstream; a sweep over a
    real captured pool is exactly the 'measured' class the approval chain wants.
    """
    pool = load_candidate_pool(fake_pool)
    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=_fake_scores,
    ):
        record = score_pool_at_weight(pool=pool, cross_encoder_weight=1.0)

    assert record["evidence"]["mode"] == "measured"
    assert record["evidence"]["capture_hash"] == pool["pool_hash"]
    assert record["p95_latency_ms"] > 0.0
    assert record["timing_scope"] == "ranker_only"
    assert record["comparison_scope"] == "fixed_pool"
    assert record["promotion_eligible"] is False
    assert record["query_count"] == len(load_json(str(DEFAULT_DATASET))["queries"])


def test_sweep_rejects_pool_from_different_dataset(fake_pool):
    pool = load_candidate_pool(fake_pool)
    pool["dataset_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="dataset hash mismatch"):
        score_pool_at_weight(pool=pool, cross_encoder_weight=0.0)


def test_sweep_record_passes_the_repos_own_validator(fake_pool):
    """The sweep must emit records the existing contract accepts unchanged."""
    from src.search_eval.retrieval_eval import validate_retrieval_evaluation_record

    pool = load_candidate_pool(fake_pool)
    with patch(
        "app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers",
        side_effect=_fake_scores,
    ):
        record = score_pool_at_weight(pool=pool, cross_encoder_weight=1.0)

    validate_retrieval_evaluation_record(record)
