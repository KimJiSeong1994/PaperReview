from routers.papers import _build_graph_sync
from copy import deepcopy


def test_small_graph_exposes_human_readable_relationship_metadata():
    graph = _build_graph_sync([
        {
            "doc_id": "paper-1",
            "title": "Continual Knowledge Graph Learning",
            "keywords": ["continual learning", "knowledge graph"],
            "year": 2024,
            "citations": 12,
        },
        {
            "doc_id": "paper-2",
            "title": "Knowledge Graph Learning for Continual Systems",
            "keywords": ["continual learning", "knowledge graph"],
            "year": 2025,
            "citations": 4,
        },
    ])

    assert graph["meta"]["edge_method"] == "title_keyword_jaccard"
    assert graph["meta"]["edge_label"] == "제목·키워드 유사도"
    assert graph["meta"]["edge_threshold"] == 0.12
    assert graph["meta"]["directed"] is False
    assert graph["meta"]["communities"] == [{
        "community_id": 0,
        "label": "continual learning · knowledge graph",
        "nodes": ["paper-1", "paper-2"],
        "size": 2,
    }]
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["shared_terms"] == [
        "continual learning",
        "knowledge graph",
        "continual",
        "graph",
    ]
    assert {node["community_id"] for node in graph["nodes"]} == {0}


def test_graph_result_keys_preserve_same_title_different_doi_and_input_records():
    papers = [
        {
            "doc_id": "legacy-collision",
            "result_key": f"doi:10.1000/{suffix}",
            "doi": f"10.1000/{suffix}",
            "title": "Knowledge Graph Learning",
            "keywords": ["knowledge graph"],
        }
        for suffix in ("one", "two")
    ]
    original = deepcopy(papers)
    graph = _build_graph_sync(papers)
    identities = {"doi:10.1000/one", "doi:10.1000/two"}
    assert papers == original
    assert {node["id"] for node in graph["nodes"]} == identities
    assert all(node["doc_id"] == node["id"] for node in graph["nodes"])
    assert len(graph["edges"]) == 1
    assert {graph["edges"][0]["source"], graph["edges"][0]["target"]} == identities
    assert set(graph["meta"]["communities"][0]["nodes"]) == identities
