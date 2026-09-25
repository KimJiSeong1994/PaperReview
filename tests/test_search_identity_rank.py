"""Adversarial identity and ranking contract (no external model calls)."""

import copy
import itertools
import math
import unicodedata
from unittest.mock import Mock

import pytest

from src.collector.paper.deduplicator import PaperDeduplicator
from src.graph_rag.hybrid_ranker import HybridRanker, RRF_K, SOURCE_BOOST
from src.utils.paper_utils import generate_doc_id, generate_result_key, normalize_title


def test_unicode_titles_and_empty_records():
    dedup = PaperDeduplicator()
    title = "한국어 신경망"
    rows = [{"title": title}, {"title": unicodedata.normalize("NFD", title)},
            {"title": "한국어 강화학습"}, {"title": "中文学习"},
            {"title": ""}, {"title": "!!!"}]
    assert len(dedup.deduplicate(rows)) == 5
    assert normalize_title("ＡI—한국어") == "ai 한국어"
    assert normalize_title("café") != normalize_title("cafe")
    assert normalize_title("graph-based") == "graph based"


def test_doi_conflict_bridge_and_provenance_are_permutation_safe():
    rows = [{"title": "identical paper", "doi": "https://doi.org/10.1/A", "source": "a"},
            {"title": "identical paper", "doi": "doi:10.1/a", "source": "b", "_found_in_sources": ["old"]},
            {"title": "identical paper", "doi": "10.1/b", "source": "c"},
            {"title": "identical paper", "source": "bridge"}]
    original = copy.deepcopy(rows)
    calculator = Mock()
    calculator.calculate_similarity.return_value = 1.0
    dedup = PaperDeduplicator()
    expected = dedup.deduplicate(rows, True, calculator)
    for permutation in itertools.permutations(rows):
        assert dedup.deduplicate(list(permutation), True, calculator) == expected
    assert len(expected) == 2
    assert {generate_result_key(p) for p in expected} == {"doi:10.1/a", "doi:10.1/b"}
    assert {s for p in expected for s in p["_found_in_sources"]} == {"a", "b", "c", "old", "bridge"}
    assert rows == original
    calculator.calculate_similarity.assert_not_called()


def test_fuzzy_and_embedding_cannot_merge_conflicting_dois():
    rows = [{"title": "one two three four five six seven eight nine ten", "doi": "10.1/a"},
            {"title": "one two three four five six seven eight nine ten eleven", "doi": "10.1/b"}]
    calculator = Mock()
    calculator.calculate_similarity.return_value = 1.0
    assert len(PaperDeduplicator().deduplicate(rows, True, calculator)) == 2
    calculator.calculate_similarity.assert_not_called()


def test_result_identity_priority_and_legacy_id():
    first = {"title": "same", "doi": "DOI: https://dx.doi.org/10.1/A", "arxiv_id": "2501.12345v2"}
    second = dict(first, doi="10.1/b")
    assert generate_doc_id(first["title"]) == generate_doc_id(second["title"])
    assert generate_result_key(first) == "doi:10.1/a"
    assert generate_result_key(first) != generate_result_key(second)
    assert generate_result_key({"url": "https://arxiv.org/pdf/2501.12345v2.pdf"}) == "arxiv:2501.12345"
    assert generate_result_key({"source": "a", "id": "1"}) != generate_result_key({"source": "b", "id": "1"})
    assert generate_result_key({"title": "한국", "authors": ["B", "A"]}) == generate_result_key({"authors": ["A", "B"], "title": "한국"})
    assert generate_result_key({}) == generate_result_key({"title": ""})


def controlled_ranker(monkeypatch):
    ranker = HybridRanker()
    for signal in ("bm25", "semantic", "citation", "recency"):
        def values(*args, _signal=signal, **kwargs):
            papers = args[1] if _signal in ("bm25", "semantic") else args[0]
            return [p.get(_signal, 0.0) for p in papers]
        monkeypatch.setattr(ranker, f"_compute_{signal}_scores", values)
    return ranker


def test_rrf_competition_ties_constant_and_permutation(monkeypatch):
    ranker = controlled_ranker(monkeypatch)
    rows = [{"doi": "10/a", "bm25": 2.0, "citation": 4.0},
            {"doi": "10/b", "bm25": 2.0, "citation": 4.0},
            {"doi": "10/c", "bm25": 1.0, "citation": 4.0}]
    expected = ranker.rank_papers("query", rows)
    for permutation in itertools.permutations(rows):
        assert ranker.rank_papers("query", list(permutation)) == expected
    assert [p["_hybrid_score"] for p in expected] == [1 / (RRF_K + 1), 1 / (RRF_K + 1), 1 / (RRF_K + 3)]
    assert expected[0]["_score_breakdown"]["excluded_signals"]["citations"] == "constant"
    assert "_hybrid_score" not in rows[0]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_signal_is_excluded_visibly(monkeypatch, invalid):
    ranker = controlled_ranker(monkeypatch)
    ranked = ranker.rank_papers("q", [{"doi": "10/a", "semantic": invalid}, {"doi": "10/b", "semantic": 1.0}])
    assert all(math.isfinite(p["_hybrid_score"]) for p in ranked)
    assert ranked[0]["_score_breakdown"]["excluded_signals"]["semantic"] == "nonfinite"
    assert ranked[0]["_score_breakdown"]["semantic"] is None


@pytest.mark.parametrize("use_rrf", [True, False])
def test_fast_mode_forbids_every_expensive_path(monkeypatch, use_rrf):
    ranker = HybridRanker(similarity_calculator=Mock())
    for method in ("_compute_semantic_scores", "_compute_cross_encoder_scores", "_generate_hyde_embedding", "_generate_hyde_unified"):
        monkeypatch.setattr(ranker, method, Mock(side_effect=AssertionError("expensive call")))
    rows = [{"title": "relevant query", "doi": "10/a", "source": "arxiv", "citations": 3},
            {"title": "other", "doi": "10/b", "citations": 0}]
    ranked = ranker.rank_papers("relevant query", rows, fast_mode=True, use_rrf=use_rrf,
                               cross_encoder_weight=2.0, openai_client=Mock())
    assert ranked[0]["doi"] == "10/a"
    assert ranked[0]["_score_breakdown"]["source_boost"] == SOURCE_BOOST["arxiv"]
    assert "_hybrid_score" not in rows[0]


def test_sort_uses_full_precision(monkeypatch):
    ranker = controlled_ranker(monkeypatch)
    rows = [{"doi": "10/a", "bm25": 0.5}, {"doi": "10/z", "bm25": 0.50000001}]
    ranked = ranker.rank_papers("q", rows, use_rrf=False,
                               weights={"bm25": 1, "semantic": 0, "citations": 0, "recency": 0})
    assert ranked[0]["doi"] == "10/z"
    assert ranked[0]["_hybrid_score"] > ranked[1]["_hybrid_score"]


def test_rrf_full_precision_and_unavailable_signal(monkeypatch):
    ranker = controlled_ranker(monkeypatch)
    monkeypatch.setattr(ranker, "_compute_semantic_scores", lambda *args, **kwargs: [])
    monkeypatch.setattr(ranker, "_compute_cross_encoder_scores",
                        lambda query, papers, **kwargs: [p["ce"] for p in papers])
    ranked = ranker.rank_papers("q", [{"doi": "10/a", "ce": 0.1}, {"doi": "10/z", "ce": 0.2}],
                               cross_encoder_weight=0.00001)
    assert ranked[0]["doi"] == "10/z"
    assert round(ranked[0]["_hybrid_score"], 6) == round(ranked[1]["_hybrid_score"], 6)
    assert ranked[0]["_hybrid_score"] > ranked[1]["_hybrid_score"]
    assert ranked[0]["_score_breakdown"]["excluded_signals"]["semantic"] == "unavailable"


def test_distinct_arxiv_records_survive_title_and_embedding_dedup():
    calculator = Mock()
    calculator.calculate_similarity.return_value = 1.0
    rows = [{"title": "same title", "arxiv_id": "2501.12345"},
            {"title": "same title", "arxiv_id": "2501.12346"}]
    assert len(PaperDeduplicator().deduplicate(rows, True, calculator)) == 2
    calculator.calculate_similarity.assert_not_called()


@pytest.mark.parametrize("cutoff", ["deadline", "stopped"])
@pytest.mark.parametrize("stage", ["hyde", "hyde_fallback", "embedding", "ce"])
def test_inflight_cutoff_prevents_later_expensive_calls(monkeypatch, cutoff, stage):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from types import SimpleNamespace
    import src.graph_rag.hybrid_ranker as module

    entered, release, stop = Event(), Event(), Event()
    clock = [10.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "_hyde_cache_get", lambda query: None)
    module._ce_cache_clear()
    calls = []

    def blocked(name, result):
        calls.append(name)
        entered.set()
        assert release.wait(5), "test failed to release first expensive operation"
        return result

    calculator = Mock()
    calculator.get_embeddings_batch.side_effect = lambda texts: blocked(
        "embedding", [None] * len(texts))
    ranker = HybridRanker(calculator if stage != "ce" else None)
    invalid_response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content="invalid JSON"))])

    def model_call(*args, **kwargs):
        if stage == "hyde_fallback" and kwargs.get("response_format"):
            return invalid_response
        return blocked(stage, invalid_response)

    model = Mock(side_effect=model_call)
    monkeypatch.setattr(module, "create_chat_completion", model)
    scorer = Mock(side_effect=lambda query, papers: blocked("ce", [0.5] * len(papers)))
    monkeypatch.setattr("app.QueryAgent.relevance_filter.LocalRelevanceScorer.score_papers", scorer)
    rows = [{"doi": f"10/cutoff-{i}", "title": f"paper {i}", "citations": i} for i in range(40)]
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            ranker.rank_papers, "cutoff query", rows,
            openai_client=object() if stage.startswith("hyde") else None,
            cross_encoder_weight=1.0, deadline=20.0, stop_event=stop,
        )
        try:
            assert entered.wait(5), "first expensive operation never started"
            if cutoff == "deadline":
                clock[0] = 21.0
            else:
                stop.set()
        finally:
            release.set()
        ranked = future.result(timeout=5)
    assert calls == [stage]
    assert len(ranked) == len(rows)
    assert ranked[0]["doi"] == "10/cutoff-39"
    assert ranked[0]["_score_breakdown"]["excluded_signals"]["cross_encoder"] == cutoff
    assert ranked[0]["_score_breakdown"]["rrf_citations"] > 0
    if stage != "ce":
        assert ranked[0]["_score_breakdown"]["excluded_signals"]["semantic"] == cutoff
        scorer.assert_not_called()
    if stage.startswith("hyde"):
        calculator.get_embeddings_batch.assert_not_called()
        assert model.call_count == (2 if stage == "hyde_fallback" else 1)
