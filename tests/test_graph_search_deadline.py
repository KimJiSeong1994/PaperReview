"""Cooperative cancellation contracts for optional GraphRAG enrichment."""

import threading

import networkx as nx

from routers import search as search_router
from src.graph_rag import search_engine as search_engine_module
from src.graph_rag.search_engine import SearchEngine


def _graph_with_seed_and_neighbor():
    graph = nx.MultiDiGraph()
    graph.add_node("seed", title="Seed")
    graph.add_node("neighbor", title="Neighbor", abstract="related")
    graph.add_edge("seed", "neighbor", edge_type="CITES")
    return graph


def test_expired_graphrag_budget_skips_graph_load(monkeypatch):
    stop = threading.Event()
    stop.set()
    load = lambda: (_ for _ in ()).throw(AssertionError("load after cancellation"))
    monkeypatch.setattr(search_router, "_load_graph_cached", load)

    assert (
        search_router._graphrag_expand(
            "query",
            [{"title": "Seed"}],
            deadline=1.0,
            stop_event=stop,
        )
        == []
    )


def test_graphrag_budget_checked_after_graph_load(monkeypatch):
    stop = threading.Event()
    graph = _graph_with_seed_and_neighbor()

    def load():
        stop.set()
        return graph

    monkeypatch.setattr(search_router, "_load_graph_cached", load)

    assert (
        search_router._graphrag_expand(
            "query",
            [{"title": "Seed"}],
            stop_event=stop,
        )
        == []
    )


def test_keyword_fallback_returns_no_partial_results_when_cancelled():
    stop = threading.Event()
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(
        [
            ("first", {"title": "graph retrieval"}),
            ("second", {"title": "graph retrieval"}),
            ("third", {"title": "graph retrieval"}),
        ]
    )

    class CancelOnFirstRead(dict):
        def __getitem__(self, key):
            value = super().__getitem__(key)
            if key == "first":
                stop.set()
            return value

    graph._node = CancelOnFirstRead(graph._node)
    engine = SearchEngine(graph)

    assert engine._keyword_fallback("graph retrieval", stop_event=stop) == []


def test_seeded_nested_edge_scan_returns_no_partial_expansion():
    stop = threading.Event()

    class CancelingEdge(dict):
        def get(self, key, default=None):
            value = super().get(key, default)
            if key == "edge_type":
                stop.set()
            return value

    graph = nx.MultiDiGraph()
    graph.add_node("seed", title="Seed")
    graph.add_node("first", title="First")
    graph.add_node("second", title="Second")
    graph.add_edge("seed", "first", edge_type="CITES")
    graph.add_edge("first", "second", edge_type="CITES")
    graph._adj["first"]["second"][0] = CancelingEdge(
        graph._adj["first"]["second"][0]
    )

    engine = SearchEngine(graph)
    assert (
        engine.expand_graph(
            ["seed"],
            expansion_strategy="hybrid_deep",
            deadline=None,
            stop_event=stop,
        )
        == []
    )


def test_live_seeded_expansion_preserves_graph_results():
    engine = SearchEngine(_graph_with_seed_and_neighbor())

    assert set(engine.expand_graph(["seed"], expansion_strategy="citation")) == {
        "seed",
        "neighbor",
    }


def test_fake_clock_expiry_stops_keyword_scan(monkeypatch):
    clock = [0.0]
    calls = [0]

    def monotonic():
        calls[0] += 1
        if calls[0] >= 4:
            clock[0] = 1.0
        return clock[0]

    monkeypatch.setattr(search_engine_module.time, "monotonic", monotonic)
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(
        [(f"node-{index}", {"title": "graph retrieval"}) for index in range(20)]
    )
    engine = SearchEngine(graph)

    assert engine._keyword_fallback("graph retrieval", deadline=1.0) == []
