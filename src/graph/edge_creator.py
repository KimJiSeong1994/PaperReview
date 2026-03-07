"""
그래프 엣지 생성 모듈
"""
import os
import sys
from typing import Dict, List, Any, Optional
from datetime import datetime
import difflib

sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from utils.logger import log_data_processing

try:
    from collector.paper.deduplicator import PaperDeduplicator
    _normalize_title = PaperDeduplicator.normalize_title
    _normalize_doi = PaperDeduplicator.normalize_doi
except ImportError:
    def _normalize_title(t):
        return t.lower().strip() if t else ""

    def _normalize_doi(d):
        return ""

class EdgeCreator:
    """그래프 엣지 생성 클래스"""

    def __init__(self):
        self.paper_id_map = {}  # 제목 -> node_id 매핑

    def _generate_paper_id(self, paper: Dict[str, Any]) -> str:
        """논문 고유 ID 생성 (DOI 우선, 없으면 정규화 제목)"""
        doi = _normalize_doi(paper.get('doi', ''))
        if doi:
            return f"doi:{doi}"
        title = _normalize_title(paper.get('title', ''))
        return title[:100] if title else str(hash(str(paper)))

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

    @log_data_processing("Similarity Edge Creation")
    def create_similarity_edges(
        self,
        papers: List[Dict[str, Any]],
        similarity_threshold: float = 0.7,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Similarity 엣지 생성"""
        edges = []

        # 각 논문에 대해 유사도 상위 K개만 선택
        for i, paper1 in enumerate(papers):
            paper1_id = paper1.get('node_id') or self._generate_paper_id(paper1)
            embedding1 = paper1.get('embedding')
            if isinstance(embedding1, list):
                embedding1 = embedding1

            if not embedding1:
                continue

            # 다른 논문들과의 유사도 계산
            similarities = []
            for paper2 in papers:
                paper2_id = paper2.get('node_id') or self._generate_paper_id(paper2)
                if paper1_id == paper2_id:
                    continue

                embedding2 = paper2.get('embedding')
                if isinstance(embedding2, list):
                    embedding2 = embedding2

                if not embedding2:
                    continue

                # Cosine similarity 계산
                similarity = self._cosine_similarity(embedding1, embedding2)

                if similarity >= similarity_threshold:
                    similarities.append((paper2_id, similarity))

            # 상위 K개 선택
            similarities.sort(key=lambda x: x[1], reverse=True)
            top_similarities = similarities[:top_k]

            for target_id, similarity in top_similarities:
                edge = {
                    "edge_id": f"{paper1_id}<->{target_id}",
                    "source": paper1_id,
                    "target": target_id,
                    "edge_type": "SIMILAR_TO",
                    "weight": similarity,
                    "metadata": {
                        "similarity_type": "semantic",
                        "computed_at": str(datetime.now())
                    }
                }
                edges.append(edge)

        return edges

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Cosine similarity 계산"""
        import numpy as np

        v1 = np.array(vec1)
        v2 = np.array(vec2)

        dot_product = np.dot(v1, v2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

