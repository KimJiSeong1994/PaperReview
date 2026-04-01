"""
네트워크 토폴로지 분석 모듈 — 허브 탐지, 커뮤니티 탐지

Phase 3: 그래프 확장성 개선
"""
import logging
from typing import Any, Dict, List

import networkx as nx
import numpy as np

from .constants import (
    TOPOLOGY_COMMUNITY_MIN_SIZE,
    TOPOLOGY_HUB_PERCENTILE,
    TOPOLOGY_PAGERANK_ALPHA,
    TOPOLOGY_USE_IGRAPH_THRESHOLD,
)

logger = logging.getLogger(__name__)


def _to_simple_graph(graph: nx.Graph) -> nx.Graph:
    """MultiDiGraph -> Graph 변환. 병렬 엣지는 max(weight)로 병합."""
    if isinstance(graph, nx.Graph) and not isinstance(graph, (nx.DiGraph, nx.MultiGraph, nx.MultiDiGraph)):
        return graph

    simple = nx.Graph()
    simple.add_nodes_from(graph.nodes(data=True))
    for u, v, data in graph.edges(data=True):
        w = data.get("weight", 1.0)
        if simple.has_edge(u, v):
            simple[u][v]["weight"] = max(simple[u][v]["weight"], w)
        else:
            simple.add_edge(u, v, weight=w)
    return simple


def _try_igraph_centrality(graph: nx.Graph) -> Dict[str, Dict[str, float]] | None:
    """igraph C 백엔드로 centrality 계산 시도. 미설치 시 None 반환."""
    try:
        import igraph as ig
    except ImportError:
        return None

    node_list = list(graph.nodes())
    node_idx = {n: i for i, n in enumerate(node_list)}

    ig_graph = ig.Graph(
        n=len(node_list),
        edges=[(node_idx[u], node_idx[v]) for u, v in graph.edges()],
        directed=False,
    )
    weights = [graph[u][v].get("weight", 1.0) for u, v in graph.edges()]
    ig_graph.es["weight"] = weights

    betweenness_raw = ig_graph.betweenness(weights="weight")
    pagerank_raw = ig_graph.pagerank(weights="weight", damping=TOPOLOGY_PAGERANK_ALPHA)

    # 정규화 (NetworkX betweenness 스케일과 일치시키기)
    n = len(node_list)
    norm = 1.0 / ((n - 1) * (n - 2)) if n > 2 else 1.0

    result: Dict[str, Dict[str, float]] = {}
    for i, node in enumerate(node_list):
        result[node] = {
            "betweenness": betweenness_raw[i] * norm,
            "pagerank": pagerank_raw[i],
        }
    return result


def compute_centrality(graph: nx.Graph) -> Dict[str, Dict[str, float]]:
    """Betweenness + PageRank centrality 계산.

    - >=5000 노드: igraph 사용 (설치 시), 미설치 시 NetworkX 폴백
    - <5000 노드: NetworkX 직접 사용
    - MultiDiGraph는 무방향 단순 그래프로 변환 후 계산

    PageRank 패턴은 ``src/graph_rag/ranker.py`` 의 ``PaperRanker`` 참조.
    """
    simple = _to_simple_graph(graph)
    n_nodes = simple.number_of_nodes()

    if n_nodes == 0:
        return {}

    # igraph 경로 (대규모)
    if n_nodes >= TOPOLOGY_USE_IGRAPH_THRESHOLD:
        logger.info("노드 %d개 — igraph 가속 시도", n_nodes)
        ig_result = _try_igraph_centrality(simple)
        if ig_result is not None:
            logger.info("igraph centrality 계산 완료")
            return ig_result
        logger.warning("igraph 미설치 — NetworkX 폴백 사용")

    # NetworkX 경로
    betweenness = nx.betweenness_centrality(simple, weight="weight")
    # PaperRanker와 동일한 nx.pagerank 호출 패턴 재사용
    pagerank = nx.pagerank(simple, alpha=TOPOLOGY_PAGERANK_ALPHA, weight="weight")

    result: Dict[str, Dict[str, float]] = {}
    for node in simple.nodes():
        result[node] = {
            "betweenness": betweenness.get(node, 0.0),
            "pagerank": pagerank.get(node, 0.0),
        }
    return result


def detect_hubs(
    centrality: Dict[str, Dict[str, float]],
    percentile: int = TOPOLOGY_HUB_PERCENTILE,
) -> List[Dict[str, Any]]:
    """Betweenness centrality 상위 N% 노드를 허브로 탐지."""
    if not centrality:
        return []

    betweenness_values = [v["betweenness"] for v in centrality.values()]
    threshold = float(np.percentile(betweenness_values, percentile))

    hubs: List[Dict[str, Any]] = []
    for node_id, scores in centrality.items():
        if scores["betweenness"] >= threshold:
            hubs.append({
                "node_id": node_id,
                "betweenness": scores["betweenness"],
                "pagerank": scores["pagerank"],
            })

    hubs.sort(key=lambda x: x["betweenness"], reverse=True)
    return hubs


def detect_communities(
    graph: nx.Graph,
    min_size: int = TOPOLOGY_COMMUNITY_MIN_SIZE,
) -> List[Dict[str, Any]]:
    """Louvain method 기반 커뮤니티 탐지.

    무방향 그래프 필요 — MultiDiGraph는 자동 변환.
    """
    simple = _to_simple_graph(graph)

    if simple.number_of_nodes() == 0:
        return []

    # networkx >= 3.x 내장 Louvain
    partition = nx.community.louvain_communities(simple, weight="weight", seed=42)

    communities: List[Dict[str, Any]] = []
    for idx, node_set in enumerate(partition):
        if len(node_set) >= min_size:
            communities.append({
                "community_id": idx,
                "nodes": sorted(node_set),
                "size": len(node_set),
            })

    communities.sort(key=lambda c: c["size"], reverse=True)
    return communities
