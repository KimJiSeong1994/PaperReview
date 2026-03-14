"""
그래프 노드 생성 모듈
"""
import os
import sys
from typing import Dict, List, Any

sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from utils.logger import log_data_processing

from utils.paper_utils import generate_paper_id as _generate_paper_id_util

class NodeCreator:
    """논문 노드 생성 클래스"""

    def __init__(self):
        pass

    def _generate_paper_id(self, paper: Dict[str, Any]) -> str:
        """논문 고유 ID 생성 (DOI 우선, 없으면 정규화 제목)"""
        return _generate_paper_id_util(paper)

    @log_data_processing("Node Creation")
    def create_node(self, paper: Dict[str, Any], embedding: Any = None) -> Dict[str, Any]:
        """단일 논문 노드 생성"""
        node_id = self._generate_paper_id(paper)

        node = {
            "node_id": node_id,
            "title": paper.get('title', ''),
            "authors": paper.get('authors', []),
            "abstract": paper.get('abstract', ''),
            "full_text": paper.get('full_text', ''),
            "url": paper.get('url', ''),
            "pdf_url": paper.get('pdf_url', ''),
            "source": paper.get('source', ''),
            "arxiv_id": paper.get('arxiv_id', ''),
            "doi": paper.get('doi', ''),
            "published_date": paper.get('published_date', ''),
            "categories": paper.get('categories', []),
            "citations": paper.get('citations', 0),
            "year": paper.get('year', ''),
            "collected_at": paper.get('collected_at', ''),
            "search_query": paper.get('search_query', ''),
            "embedding": embedding.tolist() if embedding is not None else None,
            "metadata": {
                "full_text_length": len(paper.get('full_text', '')),
                "has_references": bool(paper.get('references')),
                "reference_count": len(paper.get('references', []))
            }
        }

        return node

    def create_nodes_batch(self, papers: List[Dict[str, Any]], embeddings: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """여러 논문 노드 배치 생성"""
        nodes = []
        embeddings = embeddings or {}

        for paper in papers:
            paper_id = self._generate_paper_id(paper)
            embedding = embeddings.get(paper_id)
            node = self.create_node(paper, embedding)
            nodes.append(node)

        return nodes

