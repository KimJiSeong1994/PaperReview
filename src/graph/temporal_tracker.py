"""
시간적 커뮤니티 추적 모듈 — 연도별 스냅샷 및 라이프사이클 이벤트

Phase 3: 그래프 확장성 개선
"""
import logging
from typing import Any, Dict, List

import networkx as nx

from .constants import TOPOLOGY_COMMUNITY_MIN_SIZE

logger = logging.getLogger(__name__)


def _extract_year(node_data: Dict[str, Any], year_field: str = "year") -> int | None:
    """노드 데이터에서 연도 추출. 누락/파싱 실패 시 None 반환."""
    raw = node_data.get(year_field)
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def build_temporal_snapshots(
    graph: nx.Graph,
    communities: List[Dict[str, Any]],
    year_field: str = "year",
) -> List[Dict[str, Any]]:
    """연도별 커뮤니티 스냅샷 생성.

    각 연도마다 해당 연도까지의 노드로 서브그래프를 만들고,
    커뮤니티 멤버 중 해당 연도 이하 논문만 포함한 스냅샷을 반환한다.

    Args:
        graph: 논문 그래프 (노드에 year 속성 필요)
        communities: ``detect_communities`` 결과
        year_field: 연도를 담은 노드 속성 키

    Returns:
        연도순 정렬된 스냅샷 리스트
    """
    # 전체 노드의 연도 매핑
    node_years: Dict[str, int] = {}
    for node, data in graph.nodes(data=True):
        year = _extract_year(data, year_field)
        if year is not None:
            node_years[node] = year

    if not node_years:
        return []

    all_years = sorted(set(node_years.values()))

    snapshots: List[Dict[str, Any]] = []
    for year in all_years:
        # 해당 연도까지의 노드 집합
        nodes_up_to_year = {n for n, y in node_years.items() if y <= year}

        year_communities: List[Dict[str, Any]] = []
        for comm in communities:
            active_nodes = sorted(set(comm["nodes"]) & nodes_up_to_year)
            if len(active_nodes) >= TOPOLOGY_COMMUNITY_MIN_SIZE:
                year_communities.append({
                    "community_id": comm["community_id"],
                    "nodes": active_nodes,
                    "size": len(active_nodes),
                })

        snapshots.append({
            "year": year,
            "communities": year_communities,
        })

    return snapshots


def detect_lifecycle_events(
    snapshots: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """스냅샷 간 커뮤니티 라이프사이클 이벤트 탐지.

    이벤트 유형:
    - creation: 이전 스냅샷에 없던 커뮤니티가 등장
    - growth: 크기가 1.5배 이상 증가
    - shrink: 크기가 0.5배 이하로 감소
    - dissolution: 이전 스냅샷에 있던 커뮤니티가 사라짐
    """
    if len(snapshots) < 2:
        return []

    events: List[Dict[str, Any]] = []

    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        curr = snapshots[i]
        year = curr["year"]

        prev_map: Dict[int, int] = {
            c["community_id"]: c["size"] for c in prev["communities"]
        }
        curr_map: Dict[int, int] = {
            c["community_id"]: c["size"] for c in curr["communities"]
        }

        prev_ids = set(prev_map.keys())
        curr_ids = set(curr_map.keys())

        # creation — 새로 등장
        for cid in curr_ids - prev_ids:
            events.append({
                "year": year,
                "event": "creation",
                "community_id": cid,
                "details": {"size": curr_map[cid]},
            })

        # dissolution — 사라짐
        for cid in prev_ids - curr_ids:
            events.append({
                "year": year,
                "event": "dissolution",
                "community_id": cid,
                "details": {"previous_size": prev_map[cid]},
            })

        # growth / shrink — 크기 변화
        for cid in prev_ids & curr_ids:
            prev_size = prev_map[cid]
            curr_size = curr_map[cid]
            if prev_size == 0:
                continue
            ratio = curr_size / prev_size
            if ratio >= 1.5:
                events.append({
                    "year": year,
                    "event": "growth",
                    "community_id": cid,
                    "details": {
                        "previous_size": prev_size,
                        "current_size": curr_size,
                        "ratio": round(ratio, 2),
                    },
                })
            elif ratio <= 0.5:
                events.append({
                    "year": year,
                    "event": "shrink",
                    "community_id": cid,
                    "details": {
                        "previous_size": prev_size,
                        "current_size": curr_size,
                        "ratio": round(ratio, 2),
                    },
                })

    events.sort(key=lambda e: e["year"])
    return events
