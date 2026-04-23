"""
Topology analysis endpoints:
  POST /api/topology/analyze   — centrality, hubs, communities
  POST /api/topology/temporal  — temporal snapshots, lifecycle events
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import networkx as nx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.requests import Request

from src.graph.topology_analyzer import compute_centrality, detect_communities, detect_hubs
from src.graph.temporal_tracker import build_temporal_snapshots, detect_lifecycle_events

from .deps import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/topology", tags=["topology"])


# ── Request / Response models ────────────────────────────────────────

class GraphNodeInput(BaseModel):
    id: str
    year: Optional[int] = None


class GraphEdgeInput(BaseModel):
    source: str
    target: str
    weight: Optional[float] = 1.0


class GraphDataInput(BaseModel):
    nodes: List[GraphNodeInput]
    edges: List[GraphEdgeInput]


class TopologyRequest(BaseModel):
    graph_data: GraphDataInput


class CentralityScore(BaseModel):
    betweenness: float
    pagerank: float


class HubInfo(BaseModel):
    node_id: str
    betweenness: float
    pagerank: float


class CommunityInfo(BaseModel):
    community_id: int
    nodes: List[str]
    size: int


class TopologyResponse(BaseModel):
    centrality: Dict[str, CentralityScore]
    hubs: List[HubInfo]
    communities: List[CommunityInfo]


class TemporalSnapshotInfo(BaseModel):
    year: int
    communities: List[CommunityInfo]


class LifecycleEventInfo(BaseModel):
    year: int
    event: str
    community_id: int
    details: Dict[str, Any]


class TemporalResponse(BaseModel):
    snapshots: List[TemporalSnapshotInfo]
    events: List[LifecycleEventInfo]


# ── Helpers ──────────────────────────────────────────────────────────

def _reconstruct_graph(data: GraphDataInput) -> nx.Graph:
    """요청 데이터에서 nx.Graph 재구성."""
    graph = nx.Graph()
    for node in data.nodes:
        attrs: Dict[str, Any] = {}
        if node.year is not None:
            attrs["year"] = node.year
        graph.add_node(node.id, **attrs)
    for edge in data.edges:
        graph.add_edge(edge.source, edge.target, weight=edge.weight or 1.0)
    return graph


def _compute_topology(graph: nx.Graph) -> Dict[str, Any]:
    """CPU-bound 토폴로지 분석 (to_thread 용)."""
    centrality = compute_centrality(graph)
    hubs = detect_hubs(centrality)
    communities = detect_communities(graph)
    return {
        "centrality": centrality,
        "hubs": hubs,
        "communities": communities,
    }


def _compute_temporal(graph: nx.Graph) -> Dict[str, Any]:
    """CPU-bound 시간적 분석 (to_thread 용)."""
    communities = detect_communities(graph)
    snapshots = build_temporal_snapshots(graph, communities)
    events = detect_lifecycle_events(snapshots)
    return {
        "snapshots": snapshots,
        "events": events,
    }


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/analyze", response_model=TopologyResponse)
@limiter.limit("5/minute")
async def analyze_topology(request: Request, payload: TopologyRequest):
    """네트워크 토폴로지 분석 — centrality, hubs, communities 반환.

    F-34: CPU-heavy graph analysis → IP rate-limited to 5/min so the
    thread-pool cannot be starved by a burst of large-graph requests.
    """
    graph = _reconstruct_graph(payload.graph_data)

    if graph.number_of_nodes() == 0:
        raise HTTPException(status_code=400, detail="Graph has no nodes")

    result = await asyncio.to_thread(_compute_topology, graph)
    return result


@router.post("/temporal", response_model=TemporalResponse)
@limiter.limit("5/minute")
async def analyze_temporal(request: Request, payload: TopologyRequest):
    """시간적 커뮤니티 추적 — snapshots, lifecycle events 반환.

    F-34: CPU-heavy analysis → IP rate-limited to 5/min.
    """
    graph = _reconstruct_graph(payload.graph_data)

    if graph.number_of_nodes() == 0:
        raise HTTPException(status_code=400, detail="Graph has no nodes")

    result = await asyncio.to_thread(_compute_temporal, graph)
    return result
