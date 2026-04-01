"""
그래프 엣지 생성 모듈
"""
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
import difflib
import logging

import numpy as np

from src.utils.logger import log_data_processing

from src.utils.paper_utils import normalize_title as _normalize_title, generate_paper_id as _generate_paper_id_util

logger = logging.getLogger(__name__)

class EdgeCreator:
    """그래프 엣지 생성 클래스"""

    def __init__(self):
        self.paper_id_map = {}  # 제목 -> node_id 매핑

    def _generate_paper_id(self, paper: Dict[str, Any]) -> str:
        """논문 고유 ID 생성 (DOI 우선, 없으면 정규화 제목)"""
        return _generate_paper_id_util(paper)

    def _find_paper_by_title(self, title: str, papers: List[Dict[str, Any]]) -> Optional[str]:
        """제목으로 논문 ID 찾기 (정규화 매칭)"""
        title_norm = _normalize_title(title)
        if not title_norm:
            return None

        # 정규화 매칭
        for paper in papers:
            if _normalize_title(paper.get('title', '')) == title_norm:
                return self._generate_paper_id(paper)

        # 유사도 기반 매칭
        best_match_id = None
        best_score = 0.0
        for paper in papers:
            paper_title = _normalize_title(paper.get('title', ''))
            if not paper_title:
                continue

            ratio = difflib.SequenceMatcher(None, title_norm, paper_title).ratio()
            if ratio >= 0.85:
                return self._generate_paper_id(paper)

            if ratio > best_score:
                best_score = ratio
                best_match_id = self._generate_paper_id(paper)

        if best_score >= 0.65:
            return best_match_id

        return None

    @log_data_processing("Citation Edge Creation")
    def create_citation_edges(self, papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Citation 엣지 생성"""
        edges = []

        for paper in papers:
            source_id = self._generate_paper_id(paper)
            references = paper.get('references', [])

            for ref in references:
                ref_title = ref.get('title', '')
                if not ref_title:
                    continue

                target_id = self._find_paper_by_title(ref_title, papers)

                if target_id:
                    # 가중치 계산
                    similarity_score = ref.get('similarity_score', 0.0)
                    weight = 1.0 + (similarity_score * 0.5) if similarity_score else 1.0
                    weight = min(weight, 2.0)

                    edge = {
                        "edge_id": f"{source_id}->{target_id}",
                        "source": source_id,
                        "target": target_id,
                        "edge_type": "CITES",
                        "weight": weight,
                        "metadata": {
                            "reference_type": ref.get('reference_type', 'citation'),
                            "similarity_score": similarity_score,
                            "parent_paper_title": paper.get('title', '')
                        }
                    }
                    edges.append(edge)

        return edges

    @log_data_processing("Citation Edge Creation (by ID)")
    def create_citation_edges_by_id(
        self,
        paper_id: str,
        citations: List[Dict[str, Any]],
        graph,
    ) -> List[Dict[str, Any]]:
        """Semantic Scholar paper ID 기반 인용 엣지 생성.

        그래프에 이미 존재하는 노드에만 엣지를 생성한다.

        Args:
            paper_id: 인용 당하는 논문의 그래프 node_id
            citations: get_citations()에서 반환된 인용 논문 리스트
            graph: NetworkX 그래프 인스턴스

        Returns:
            생성된 엣지 리스트
        """
        edges: List[Dict[str, Any]] = []

        if paper_id not in graph:
            return edges

        for cit in citations:
            cit_title = cit.get('title', '')
            if not cit_title:
                continue

            # 인용 논문이 그래프에 있는지 제목으로 검색
            cit_node_id = None
            cit_title_norm = _normalize_title(cit_title)
            if not cit_title_norm:
                continue

            for node_id in graph.nodes():
                node_data = graph.nodes[node_id]
                node_title = node_data.get('title', '')
                if _normalize_title(node_title) == cit_title_norm:
                    cit_node_id = node_id
                    break

            if cit_node_id is None or cit_node_id == paper_id:
                continue

            # 이미 존재하는 엣지인지 확인
            if graph.has_edge(cit_node_id, paper_id):
                continue

            is_influential = cit.get('isInfluential', False)
            edge = {
                "edge_id": f"{cit_node_id}->{paper_id}",
                "source": cit_node_id,
                "target": paper_id,
                "edge_type": "CITES",
                "weight": 1.0,
                "metadata": {
                    "reference_type": "citation",
                    "is_influential": is_influential,
                    "source_api": "semantic_scholar",
                }
            }
            edges.append(edge)

        return edges

    @log_data_processing("Similarity Edge Creation")
    def create_similarity_edges(
        self,
        papers: List[Dict[str, Any]],
        similarity_threshold: float = 0.7,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Similarity 엣지 생성 (FAISS-backed with numpy fallback).

        Uses FAISS index for efficient neighbour search when available.
        Falls back to vectorized numpy brute-force when FAISS is unavailable
        or when GRAPH_FORCE_BRUTEFORCE=1 is set.
        """
        # Collect valid papers with embeddings
        valid_papers: List[Dict[str, Any]] = []
        valid_ids: List[str] = []
        valid_vectors: List[np.ndarray] = []

        for paper in papers:
            paper_id = paper.get('node_id') or self._generate_paper_id(paper)
            embedding = paper.get('embedding')
            if embedding is None:
                continue
            vec = np.array(embedding, dtype=np.float32)
            if vec.size == 0:
                continue
            valid_papers.append(paper)
            valid_ids.append(paper_id)
            valid_vectors.append(vec)

        if len(valid_vectors) < 2:
            return []

        matrix = np.vstack(valid_vectors).astype(np.float32)

        force_bruteforce = os.environ.get("GRAPH_FORCE_BRUTEFORCE", "0") == "1"

        if force_bruteforce:
            logger.info(
                "[EdgeCreator] GRAPH_FORCE_BRUTEFORCE=1, using numpy brute-force for %d papers",
                len(valid_ids),
            )
            return self._create_similarity_edges_bruteforce(
                matrix, valid_ids, similarity_threshold, top_k
            )

        try:
            from src.graph.faiss_index_manager import (
                build_similarity_index,
                search_neighbors,
            )
            import faiss

            # L2-normalise for cosine similarity via inner product
            faiss.normalize_L2(matrix)

            index = build_similarity_index(matrix)
            scores, indices = search_neighbors(
                index, matrix, top_k=top_k, min_similarity=similarity_threshold
            )

            edges: List[Dict[str, Any]] = []
            seen_pairs: set = set()

            for i in range(len(valid_ids)):
                src_id = valid_ids[i]
                for j_pos in range(scores.shape[1]):
                    nbr_idx = int(indices[i][j_pos])
                    sim = float(scores[i][j_pos])
                    if nbr_idx < 0 or sim <= 0.0:
                        continue
                    dst_id = valid_ids[nbr_idx]
                    pair_key = tuple(sorted((src_id, dst_id)))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    edges.append({
                        "edge_id": f"{src_id}<->{dst_id}",
                        "source": src_id,
                        "target": dst_id,
                        "edge_type": "SIMILAR_TO",
                        "weight": round(sim, 4),
                        "metadata": {
                            "similarity_type": "semantic",
                            "computed_at": str(datetime.now()),
                        },
                    })

            logger.info(
                "[EdgeCreator] FAISS: %d papers, %d edges created", len(valid_ids), len(edges)
            )
            return edges

        except (ImportError, RuntimeError) as exc:
            logger.warning(
                "[EdgeCreator] FAISS unavailable (%s), falling back to numpy brute-force", exc
            )
            return self._create_similarity_edges_bruteforce(
                matrix, valid_ids, similarity_threshold, top_k
            )

    def _create_similarity_edges_bruteforce(
        self,
        matrix: np.ndarray,
        valid_ids: List[str],
        similarity_threshold: float,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Vectorized numpy brute-force cosine similarity fallback.

        Computes full similarity matrix via matrix multiplication on
        L2-normalised vectors, then extracts top-k per row.
        """
        # L2-normalise rows
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normed = matrix / norms

        # Full cosine similarity matrix
        sim_matrix = normed @ normed.T

        edges: List[Dict[str, Any]] = []
        seen_pairs: set = set()
        n = len(valid_ids)

        for i in range(n):
            row = sim_matrix[i].copy()
            row[i] = -1.0  # exclude self
            # Get top-k indices
            if top_k < n - 1:
                top_indices = np.argpartition(row, -top_k)[-top_k:]
            else:
                top_indices = np.arange(n)
                top_indices = top_indices[top_indices != i]

            for j in top_indices:
                if j == i:
                    continue
                sim = float(row[j])
                if sim < similarity_threshold:
                    continue
                src_id = valid_ids[i]
                dst_id = valid_ids[j]
                pair_key = tuple(sorted((src_id, dst_id)))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                edges.append({
                    "edge_id": f"{src_id}<->{dst_id}",
                    "source": src_id,
                    "target": dst_id,
                    "edge_type": "SIMILAR_TO",
                    "weight": round(sim, 4),
                    "metadata": {
                        "similarity_type": "semantic",
                        "computed_at": str(datetime.now()),
                    },
                })

        logger.info(
            "[EdgeCreator] Brute-force: %d papers, %d edges created", n, len(edges)
        )
        return edges

