"""
네트워크 토폴로지 분석 단위 테스트

Phase 3: 그래프 확장성 개선
"""
import pytest
import networkx as nx

from src.graph.topology_analyzer import compute_centrality, detect_communities, detect_hubs
from src.graph.temporal_tracker import build_temporal_snapshots, detect_lifecycle_events


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def bridge_graph() -> nx.Graph:
    """두 클리크(5노드)를 하나의 브릿지 노드로 연결한 그래프.

    Clique A: a0-a4 (완전 연결)
    Clique B: b0-b4 (완전 연결)
    Bridge: a0 -- bridge -- b0
    """
    g = nx.Graph()

    # Clique A
    clique_a = [f"a{i}" for i in range(5)]
    for i, u in enumerate(clique_a):
        g.add_node(u, year=2020)
        for v in clique_a[i + 1:]:
            g.add_edge(u, v, weight=1.0)

    # Clique B
    clique_b = [f"b{i}" for i in range(5)]
    for i, u in enumerate(clique_b):
        g.add_node(u, year=2022)
        for v in clique_b[i + 1:]:
            g.add_edge(u, v, weight=1.0)

    # Bridge node
    g.add_node("bridge", year=2021)
    g.add_edge("a0", "bridge", weight=1.0)
    g.add_edge("bridge", "b0", weight=1.0)

    return g


@pytest.fixture
def temporal_graph() -> nx.Graph:
    """시간적 추적 테스트용 그래프.

    Year 2020: 클리크 A (a0-a2) 형성
    Year 2021: 클리크 A 성장 (a3-a5 추가), 클리크 B (b0-b2) 생성
    Year 2022: 클리크 B 소멸 (클리크 A만 유지)
    """
    g = nx.Graph()

    # Clique A base (2020)
    for i in range(3):
        g.add_node(f"a{i}", year=2020)
    for i in range(3):
        for j in range(i + 1, 3):
            g.add_edge(f"a{i}", f"a{j}", weight=1.0)

    # Clique A growth (2021)
    for i in range(3, 6):
        g.add_node(f"a{i}", year=2021)
    for i in range(6):
        for j in range(i + 1, 6):
            if not g.has_edge(f"a{i}", f"a{j}"):
                g.add_edge(f"a{i}", f"a{j}", weight=1.0)

    # Clique B (2021)
    for i in range(3):
        g.add_node(f"b{i}", year=2021)
    for i in range(3):
        for j in range(i + 1, 3):
            g.add_edge(f"b{i}", f"b{j}", weight=1.0)

    return g


# ── Centrality tests ─────────────────────────────────────────────────

class TestComputeCentrality:
    def test_bridge_has_highest_betweenness(self, bridge_graph: nx.Graph):
        centrality = compute_centrality(bridge_graph)
        bridge_bc = centrality["bridge"]["betweenness"]
        for node_id, scores in centrality.items():
            if node_id != "bridge":
                assert bridge_bc >= scores["betweenness"], (
                    f"Bridge betweenness ({bridge_bc}) should be >= "
                    f"{node_id} betweenness ({scores['betweenness']})"
                )

    def test_all_nodes_have_pagerank(self, bridge_graph: nx.Graph):
        centrality = compute_centrality(bridge_graph)
        assert len(centrality) == bridge_graph.number_of_nodes()
        for scores in centrality.values():
            assert "pagerank" in scores
            assert scores["pagerank"] > 0

    def test_empty_graph(self):
        g = nx.Graph()
        centrality = compute_centrality(g)
        assert centrality == {}

    def test_multidigraph_converted(self):
        """MultiDiGraph가 자동 변환되어 올바른 결과를 반환하는지 확인."""
        mdg = nx.MultiDiGraph()
        mdg.add_edge("a", "b", weight=0.5)
        mdg.add_edge("a", "b", weight=0.9)  # 병렬 엣지
        mdg.add_edge("b", "c", weight=0.7)
        centrality = compute_centrality(mdg)
        assert len(centrality) == 3
        # b는 중간 노드이므로 betweenness > 0
        assert centrality["b"]["betweenness"] > 0


# ── Hub detection tests ──────────────────────────────────────────────

class TestDetectHubs:
    def test_bridge_detected_as_hub(self, bridge_graph: nx.Graph):
        centrality = compute_centrality(bridge_graph)
        hubs = detect_hubs(centrality, percentile=90)
        hub_ids = {h["node_id"] for h in hubs}
        assert "bridge" in hub_ids, "Bridge node should be detected as a hub"

    def test_hubs_sorted_by_betweenness(self, bridge_graph: nx.Graph):
        centrality = compute_centrality(bridge_graph)
        hubs = detect_hubs(centrality, percentile=50)
        for i in range(len(hubs) - 1):
            assert hubs[i]["betweenness"] >= hubs[i + 1]["betweenness"]

    def test_empty_centrality(self):
        hubs = detect_hubs({})
        assert hubs == []


# ── Community detection tests ────────────────────────────────────────

class TestDetectCommunities:
    def test_two_communities_detected(self, bridge_graph: nx.Graph):
        communities = detect_communities(bridge_graph)
        # 브릿지로 연결된 두 클리크 -> 최소 2개 커뮤니티
        assert len(communities) >= 2, (
            f"Expected at least 2 communities, got {len(communities)}"
        )

    def test_community_min_size(self, bridge_graph: nx.Graph):
        communities = detect_communities(bridge_graph, min_size=4)
        for comm in communities:
            assert comm["size"] >= 4

    def test_community_structure(self, bridge_graph: nx.Graph):
        communities = detect_communities(bridge_graph)
        for comm in communities:
            assert "community_id" in comm
            assert "nodes" in comm
            assert "size" in comm
            assert comm["size"] == len(comm["nodes"])

    def test_empty_graph(self):
        g = nx.Graph()
        communities = detect_communities(g)
        assert communities == []


# ── Temporal tracker tests ───────────────────────────────────────────

class TestBuildTemporalSnapshots:
    def test_snapshots_sorted_by_year(self, temporal_graph: nx.Graph):
        communities = detect_communities(temporal_graph)
        snapshots = build_temporal_snapshots(temporal_graph, communities)
        years = [s["year"] for s in snapshots]
        assert years == sorted(years)

    def test_creation_events_detected(self, temporal_graph: nx.Graph):
        communities = detect_communities(temporal_graph)
        snapshots = build_temporal_snapshots(temporal_graph, communities)
        events = detect_lifecycle_events(snapshots)

        creation_events = [e for e in events if e["event"] == "creation"]
        assert len(creation_events) > 0, "At least one creation event expected"

    def test_missing_year_skipped(self):
        """year 속성 없는 노드는 스냅샷에서 제외."""
        g = nx.Graph()
        g.add_node("a", year=2020)
        g.add_node("b", year=2020)
        g.add_node("c", year=2020)
        g.add_node("d")  # year 없음
        g.add_edge("a", "b", weight=1.0)
        g.add_edge("b", "c", weight=1.0)
        g.add_edge("a", "c", weight=1.0)
        g.add_edge("c", "d", weight=1.0)

        communities = detect_communities(g, min_size=1)
        snapshots = build_temporal_snapshots(g, communities)

        # d는 year가 없으므로 어떤 스냅샷의 노드에도 포함되지 않아야 함
        for snap in snapshots:
            for comm in snap["communities"]:
                assert "d" not in comm["nodes"]


class TestDetectLifecycleEvents:
    def test_growth_event(self):
        """크기가 1.5배 이상 증가하면 growth 이벤트 발생."""
        snapshots = [
            {"year": 2020, "communities": [{"community_id": 0, "nodes": ["a", "b", "c"], "size": 3}]},
            {"year": 2021, "communities": [{"community_id": 0, "nodes": ["a", "b", "c", "d", "e"], "size": 5}]},
        ]
        events = detect_lifecycle_events(snapshots)
        growth = [e for e in events if e["event"] == "growth"]
        assert len(growth) == 1
        assert growth[0]["community_id"] == 0
        assert growth[0]["details"]["ratio"] >= 1.5

    def test_shrink_event(self):
        """크기가 0.5배 이하로 감소하면 shrink 이벤트 발생."""
        snapshots = [
            {"year": 2020, "communities": [{"community_id": 0, "nodes": ["a", "b", "c", "d"], "size": 4}]},
            {"year": 2021, "communities": [{"community_id": 0, "nodes": ["a", "b"], "size": 2}]},
        ]
        events = detect_lifecycle_events(snapshots)
        shrink = [e for e in events if e["event"] == "shrink"]
        assert len(shrink) == 1
        assert shrink[0]["details"]["ratio"] <= 0.5

    def test_dissolution_event(self):
        """커뮤니티가 사라지면 dissolution 이벤트 발생."""
        snapshots = [
            {"year": 2020, "communities": [
                {"community_id": 0, "nodes": ["a", "b", "c"], "size": 3},
                {"community_id": 1, "nodes": ["d", "e", "f"], "size": 3},
            ]},
            {"year": 2021, "communities": [
                {"community_id": 0, "nodes": ["a", "b", "c"], "size": 3},
            ]},
        ]
        events = detect_lifecycle_events(snapshots)
        dissolution = [e for e in events if e["event"] == "dissolution"]
        assert len(dissolution) == 1
        assert dissolution[0]["community_id"] == 1

    def test_single_snapshot_no_events(self):
        """스냅샷이 1개이면 이벤트 없음."""
        snapshots = [
            {"year": 2020, "communities": [{"community_id": 0, "nodes": ["a", "b", "c"], "size": 3}]},
        ]
        events = detect_lifecycle_events(snapshots)
        assert events == []


# ── API schema test ──────────────────────────────────────────────────

class TestTopologyEndpointSchema:
    def test_topology_response_schema(self, bridge_graph: nx.Graph):
        """analyze 엔드포인트 응답 스키마 검증 (로직 레벨)."""
        centrality = compute_centrality(bridge_graph)
        hubs = detect_hubs(centrality)
        communities = detect_communities(bridge_graph)

        # 스키마 검증
        for node_id, scores in centrality.items():
            assert isinstance(node_id, str)
            assert isinstance(scores["betweenness"], float)
            assert isinstance(scores["pagerank"], float)

        for hub in hubs:
            assert "node_id" in hub
            assert "betweenness" in hub
            assert "pagerank" in hub

        for comm in communities:
            assert "community_id" in comm
            assert "nodes" in comm
            assert "size" in comm
            assert isinstance(comm["nodes"], list)
            assert isinstance(comm["size"], int)

    def test_temporal_response_schema(self, bridge_graph: nx.Graph):
        """temporal 엔드포인트 응답 스키마 검증 (로직 레벨)."""
        communities = detect_communities(bridge_graph)
        snapshots = build_temporal_snapshots(bridge_graph, communities)
        events = detect_lifecycle_events(snapshots)

        for snap in snapshots:
            assert "year" in snap
            assert "communities" in snap
            assert isinstance(snap["year"], int)

        for event in events:
            assert "year" in event
            assert "event" in event
            assert event["event"] in ("creation", "growth", "shrink", "dissolution")
            assert "community_id" in event
            assert "details" in event
