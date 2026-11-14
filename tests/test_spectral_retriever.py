"""Behavioral contracts for the bounded SpectRAG metadata adaptation."""

import copy
import threading
import time

import numpy as np
import pytest

from src.graph_rag.spectral_retriever import (
    MAX_CANDIDATES, _proximity, configured_mode, expand_graph_candidates, retrieve, select_context,
)


def papers():
    return [
        {"title": f"그래프 신경망 추천 방법 {i}", "abstract": "그래프 추천 데이터 학습",
         "doi": f"10.1234/{i}", "_kci_match_tier": 0 if i < 3 else 1}
        for i in range(12)
    ]


@pytest.mark.parametrize("mode", ["baseline", "spectral", "ppr"])
def test_retrieval_preserves_identity_core_input_and_size(mode):
    source = papers()
    before = copy.deepcopy(source)
    result = retrieve("그래프 추천", source, 5, mode=mode)
    assert source == before
    assert len(result.papers) == 5
    assert len({p["doi"] for p in result.papers}) == 5
    assert [p["doi"] for p in result.papers[:2]] == [p["doi"] for p in source[:2]]
    assert [p["_kci_match_tier"] for p in result.papers] == [0, 0, 0, 1, 1]
    assert all(np.isfinite(p.get("_retrieval_score", 0)) for p in result.papers)


def test_deadline_and_stop_return_baseline_without_graph_work(monkeypatch):
    from src.graph_rag import spectral_retriever as module
    monkeypatch.setattr(module, "_similarities", lambda *args: pytest.fail("work admitted after cutoff"))
    stop = threading.Event()
    stop.set()
    for kwargs in ({"deadline": time.monotonic() - 1}, {"stop_event": stop}):
        result = retrieve("그래프", papers(), 4, **kwargs)
        assert result.papers == papers()[:4]
        assert result.metadata["status"] == "deadline_fallback"


def test_large_input_is_capped_before_similarity_allocation():
    result = retrieve("그래프", papers() * 1000, 10)
    assert result.metadata["candidate_count"] == MAX_CANDIDATES
    assert result.metadata["input_truncated"] is True


@pytest.mark.parametrize("mode", ["spectral", "ppr"])
def test_diffusion_does_not_leak_to_disconnected_component(mode):
    adjacency = np.zeros((7, 7))
    for a, b in [(0, 1), (1, 2), (3, 4), (4, 5)]:
        adjacency[a, b] = adjacency[b, a] = 1
    score = _proximity(adjacency, [0], mode, None, None)
    assert score[1] > 0
    assert np.all(score[3:] == 0)
    assert np.all(np.isfinite(score))


def test_repeated_spectrum_and_repeated_queries_are_deterministic():
    adjacency = np.ones((12, 12)) - np.eye(12)
    first = _proximity(adjacency, [0], "spectral", None, None)
    assert np.allclose(first, _proximity(adjacency, [0], "spectral", None, None))
    assert np.allclose(first[1:], first[1])
    assert retrieve("그래프", papers(), 6) == retrieve("그래프", papers(), 6)


def test_missing_signal_and_invalid_edges_do_not_invent_relevance():
    source = [{"title": "apple", "id": "a"}, {"title": "banana", "id": "b"}, {"title": "carrot", "id": "c"}]
    result = retrieve("그래프", source, 3, edges=[("missing", "absent", float("nan"))])
    assert result.papers == source
    assert result.metadata["status"] == "no_signal_fallback"


def test_solver_failure_returns_unchanged_baseline(monkeypatch):
    def fail(*args):
        raise np.linalg.LinAlgError("controlled convergence failure")
    monkeypatch.setattr(np.linalg, "eigh", fail)
    result = retrieve("그래프", papers(), 4)
    assert result.papers == papers()[:4]
    assert result.metadata["status"] == "compute_fallback"


def test_context_budget_counts_serialization_and_skips_oversize_head():
    source = [{"text": "oversized " * 30}, {"text": "small one"}, {"text": "small two"}]
    render = lambda items: "HEADER " + " ; ".join(p["text"] for p in items)
    count = lambda text: len(text.split())  # deterministic test tokenizer, not an LLM token claim
    selected, used = select_context(source, 6, count, render=render)
    assert selected == source[1:]
    assert used == count(render(selected)) == 6


@pytest.mark.parametrize("top_k", [0, -1, 101])
def test_invalid_size_fails_explicitly(top_k):
    with pytest.raises(ValueError):
        retrieve("x", papers(), top_k)


def test_mode_is_opt_in_and_invalid_configuration_falls_back(monkeypatch):
    monkeypatch.delenv("KCI_RETRIEVAL_MODE", raising=False)
    assert configured_mode() == "baseline"
    monkeypatch.setenv("KCI_RETRIEVAL_MODE", "spectral")
    assert configured_mode() == "spectral"
    monkeypatch.setenv("KCI_RETRIEVAL_MODE", "typo")
    assert configured_mode() == "baseline"


def test_graph_expansion_recovers_two_hop_bridge_and_incoming_citation():
    import networkx as nx

    graph = nx.MultiDiGraph()
    graph.add_edge("seed", "bridge", edge_type="CITES")
    graph.add_edge("evidence", "bridge", edge_type="CITES")
    graph.add_edge("seed", "weak", weight=0.01)
    graph.add_node("unrelated")
    expanded = expand_graph_candidates(graph, ["seed"], max_candidates=4)
    assert expanded == ["seed", "bridge", "weak", "evidence"]
    assert "unrelated" not in expanded
    assert expand_graph_candidates(graph, ["seed"], max_candidates=2) == ["seed", "bridge"]
    assert expand_graph_candidates(graph, ["seed"], deadline=time.monotonic() - 1) == ["seed"]


def test_empty_context_wrapper_cannot_exceed_budget():
    with pytest.raises(ValueError):
        select_context([], 0, len, render=lambda records: "header")


def test_router_spectral_expansion_returns_real_graph_evidence(monkeypatch):
    import networkx as nx
    from routers import search as router

    seed = {"title": "그래프 신경망 원리", "doi": "10.1234/seed", "abstract": "그래프 신경망 추천"}
    graph = nx.MultiDiGraph()
    graph.add_node("doi:10.1234/seed", **seed)
    graph.add_node("doi:10.1234/bridge", title="추천 방법", doi="10.1234/bridge", abstract="그래프 신경망 원리 추천")
    graph.add_node("doi:10.1234/evidence", title="추적 결과", doi="10.1234/evidence", abstract="추천 방법 결과")
    graph.add_node("irrelevant", title="다른 분야")
    graph.add_edge("doi:10.1234/seed", "doi:10.1234/bridge", edge_type="CITES", weight=1)
    graph.add_edge("doi:10.1234/bridge", "doi:10.1234/evidence", edge_type="CITES", weight=1)
    monkeypatch.setenv("KCI_RETRIEVAL_MODE", "spectral")
    monkeypatch.setattr(router, "_load_graph_cached", lambda: graph)
    result = router._graphrag_expand("그래프 추천 결과", [seed], max_expand=3)
    assert {paper["doi"] for paper in result} == {"10.1234/bridge", "10.1234/evidence"}
    assert all(paper["source"] == "graphrag" for paper in result)


def test_mode_switch_changes_cache_even_without_kci_source(monkeypatch):
    from routers.search import _compute_cache_key

    monkeypatch.setenv("KCI_RETRIEVAL_MODE", "baseline")
    before = _compute_cache_key("graph retrieval", ["arxiv"], {})
    monkeypatch.setenv("KCI_RETRIEVAL_MODE", "spectral")
    assert _compute_cache_key("graph retrieval", ["arxiv"], {}) != before
