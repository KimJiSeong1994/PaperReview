from routers.papers import _build_edges_jaccard, _build_graph_sync
from copy import deepcopy


def test_small_graph_exposes_human_readable_relationship_metadata():
    graph = _build_graph_sync(
        [
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
        ]
    )

    assert graph["meta"]["edge_method"] == "title_keyword_jaccard"
    assert graph["meta"]["edge_label"] == "제목·키워드 유사도"
    assert graph["meta"]["edge_threshold"] == 0.12
    assert graph["meta"]["directed"] is False
    assert graph["meta"]["communities"] == [
        {
            "community_id": 0,
            "label": "continual learning · knowledge graph",
            "nodes": ["paper-1", "paper-2"],
            "size": 2,
        }
    ]
    assert len(graph["edges"]) == 1
    # Title tokens shared by every title are query echo, not evidence.
    assert graph["edges"][0]["shared_terms"] == [
        "continual learning",
        "knowledge graph",
    ]
    assert graph["meta"]["common_terms"] == [
        "continual",
        "graph",
        "knowledge",
        "learning",
    ]
    assert graph["meta"]["edge_total"] == 1
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


def _homogeneous_papers(count: int) -> list[dict]:
    """Titles that all echo one query plus a per-paper distinctive tail."""
    tails = ["federated", "poisoning", "survey", "medical", "legal", "agent"]
    return [
        {
            "doc_id": f"p{index}",
            "title": (
                "Graph Retrieval-Augmented Generation for "
                f"{tails[index % len(tails)]} {tails[(index * 5 + 1) % len(tails)]}"
            ),
            "keywords": [tails[index % len(tails)]],
            "citations": index,
        }
        for index in range(count)
    ]


def test_query_echo_terms_are_excluded_from_evidence_and_labels():
    graph = _build_graph_sync(_homogeneous_papers(12))
    common = set(graph["meta"]["common_terms"])

    assert {
        "graph",
        "retrieval-augmented",
        "retrieval",
        "augmented",
        "generation",
    } <= common
    for edge in graph["edges"]:
        assert not common & set(edge["shared_terms"])
    for community in graph["meta"]["communities"]:
        assert not common & set(community["label"].replace(" · ", " ").split())


def test_sparsified_graph_keeps_origin_component_reachable():
    import networkx as nx

    papers = _homogeneous_papers(12)
    full = nx.Graph()
    full.add_nodes_from(paper["doc_id"] for paper in papers)
    _build_edges_jaccard(papers, full)
    assert full.number_of_edges() > 0

    graph = _build_graph_sync(papers)
    n = len(graph["nodes"])
    assert graph["meta"]["edge_total"] == full.number_of_edges()
    assert len(graph["edges"]) <= 5 * n
    assert len(graph["edges"]) <= graph["meta"]["edge_total"]

    sparse = nx.Graph()
    sparse.add_nodes_from(node["id"] for node in graph["nodes"])
    sparse.add_edges_from((edge["source"], edge["target"]) for edge in graph["edges"])

    def components(g):
        return {frozenset(c) for c in nx.connected_components(g)}

    # The spanning tree keeps every component exactly as it was.
    assert components(sparse) == components(full)


def test_community_ids_are_contiguous_and_tiny_communities_are_merged():
    graph = _build_graph_sync(_homogeneous_papers(24))
    communities = graph["meta"]["communities"]

    assert [c["community_id"] for c in communities] == list(range(len(communities)))
    labelled = {node["community_id"] for node in graph["nodes"]} - {None}
    assert labelled == set(range(len(communities)))
    assert all(c["size"] >= 3 for c in communities)
    labels = [c["label"] for c in communities]
    assert len(labels) == len(set(labels))


def test_community_count_is_capped_to_palette_size():
    graph = _build_graph_sync(_homogeneous_papers(80))
    communities = graph["meta"]["communities"]

    assert len(communities) <= 6
    assert [c["community_id"] for c in communities] == list(range(len(communities)))
    labelled = [node for node in graph["nodes"] if node["community_id"] is not None]
    assert {node["community_id"] for node in labelled} == set(range(len(communities)))
    assert sum(c["size"] for c in communities) == len(labelled)


def test_weighted_jaccard_prefers_rare_shared_tokens():
    import networkx as nx

    filler = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
    papers = [
        {"doc_id": f"f{i}", "title": f"Graph Methods {filler[i]} {filler[(i + 1) % 6]}"}
        for i in range(6)
    ] + [
        {"doc_id": "ubiq-a", "title": "Graph Methods Zulu Yankee"},
        {"doc_id": "ubiq-b", "title": "Graph Methods Whiskey Victor"},
        {"doc_id": "rare-a", "title": "Graph Methods Hyperbolic Zulu"},
        {"doc_id": "rare-b", "title": "Graph Methods Hyperbolic Victor"},
    ]
    full = nx.Graph()
    full.add_nodes_from(paper["doc_id"] for paper in papers)
    _build_edges_jaccard(papers, full)

    ubiquitous_only = full.get_edge_data("ubiq-a", "ubiq-b", {}).get("weight", 0.0)
    one_rare_token = full.get_edge_data("rare-a", "rare-b", {}).get("weight", 0.0)
    assert one_rare_token > ubiquitous_only


def test_isolated_singleton_is_unlabelled_and_ids_stay_contiguous():
    papers = _homogeneous_papers(9) + [
        {
            "doc_id": "lonely",
            "title": "Zebra Migration Patterns in Serengeti",
            "citations": 1,
        }
    ]
    graph = _build_graph_sync(papers)
    by_id = {node["id"]: node for node in graph["nodes"]}

    assert by_id["lonely"]["community_id"] is None
    assert by_id["lonely"]["community_label"] == ""
    assert not any(
        e["source"] == "lonely" or e["target"] == "lonely" for e in graph["edges"]
    )
    communities = graph["meta"]["communities"]
    assert communities, "the connected papers still form reported communities"
    assert "lonely" not in {n for c in communities for n in c["nodes"]}
    assert [c["community_id"] for c in communities] == list(range(len(communities)))


def test_isolated_singletons_do_not_collapse_real_communities_into_one():
    """Regression: 22 isolated papers once counted against the six-community cap
    and the merge loop folded five real topics into a single giant community."""
    query = "graph retrieval augmented generation"
    rare = ["zebra", "quasar", "mangrove", "glacier", "saffron"]
    papers = []
    for group, token in enumerate(rare):
        for index in range(5):
            papers.append(
                {
                    "doc_id": f"g{group}-{index}",
                    "title": f"{token} {query} study{group}{index}",
                    "year": 2024,
                }
            )
    for index in range(len(rare) - 1):
        papers.append(
            {
                "doc_id": f"bridge-{index}",
                "title": f"{rare[index]} {rare[index + 1]} {query} bridgework{index}",
                "year": 2024,
            }
        )
    for index in range(8):
        papers.append(
            {
                "doc_id": f"lonely-{index}",
                "title": f"unrelated{index} topic{index} wordplay{index}",
                "year": 2024,
            }
        )

    graph = _build_graph_sync(papers)
    communities = graph["meta"]["communities"]
    unlabelled = [node for node in graph["nodes"] if node["community_id"] is None]

    assert len(unlabelled) == 8
    assert all(node["doc_id"].startswith("lonely-") for node in unlabelled)
    assert 3 <= len(communities) <= 6
    labelled = sum(community["size"] for community in communities)
    assert max(community["size"] for community in communities) < labelled


def test_title_tokens_drop_stray_hyphens_from_evidence_and_labels():
    papers = [
        {"doc_id": "a", "title": "Leveraging (knowledge)-intensive graphs", "year": 2024},
        {"doc_id": "b", "title": "Leveraging knowledge-intensive graphs", "year": 2024},
        {"doc_id": "c", "title": "Leveraging intensive graphs today", "year": 2024},
    ]

    graph = _build_graph_sync(papers)

    mentioned = {
        term
        for edge in graph["edges"]
        for term in edge["shared_terms"]
    } | {
        term
        for community in graph["meta"]["communities"]
        for term in community["label"].split(" · ")
    }
    assert mentioned
    assert not any(term.startswith("-") or term.endswith("-") for term in mentioned)


def test_edgeless_graph_reports_no_communities():
    papers = [
        {"doc_id": f"p{index}", "title": f"alpha{index} beta{index} gamma{index}", "year": 2024}
        for index in range(20)
    ]

    graph = _build_graph_sync(papers)

    assert graph["edges"] == []
    assert graph["meta"]["communities"] == []
    assert all(node["community_id"] is None for node in graph["nodes"])
