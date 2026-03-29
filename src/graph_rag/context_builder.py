"""
컨텍스트 생성 모듈
"""
import os
import sys
from typing import Dict, List


class ContextBuilder:
    """컨텍스트 생성 클래스"""

    def __init__(self, graph):
        self.graph = graph

    def create_context(self, selected_papers: List[Dict], query: str) -> str:
        """컨텍스트 생성"""
        context_parts = [f"User Query: {query}\n"]

        for i, paper_info in enumerate(selected_papers, 1):
            paper = paper_info['paper']
            score = paper_info['score']

            paper_context = f"""
Paper {i} (Relevance Score: {score:.3f}):
Title: {paper.get('title', 'N/A')}
Authors: {', '.join(paper.get('authors', []))}
Published: {paper.get('published_date', 'Unknown')}
Source: {paper.get('source', 'Unknown')}
Abstract: {paper.get('abstract', 'N/A')[:500]}...
"""
            context_parts.append(paper_context)

        return "\n".join(context_parts)

    def create_structured_context(self, selected_papers: List[Dict], query: str) -> Dict:
        """구조화된 컨텍스트 생성"""
        return {
            "query": query,
            "papers": [
                {
                    "title": p['paper'].get('title', ''),
                    "authors": p['paper'].get('authors', []),
                    "abstract": p['paper'].get('abstract', ''),
                    "relevance_score": p['score'],
                    "url": p['paper'].get('url', ''),
                    "relationships": self._get_paper_relationships(p['paper_id'], selected_papers)
                }
                for p in selected_papers
            ],
            "graph_statistics": {
                "total_papers": len(selected_papers),
                "avg_similarity": self._calculate_avg_similarity(selected_papers)
            }
        }

    def _get_paper_relationships(self, paper_id: str, selected_papers: List[Dict]) -> List[str]:
        """논문 간 관계 정보"""
        relationships = []
        selected_ids = {p['paper_id'] for p in selected_papers}

        # Citation 관계
        for neighbor in self.graph.neighbors(paper_id):
            if neighbor in selected_ids:
                edge_data = self.graph.get_edge_data(paper_id, neighbor)
                if edge_data:
                    for data in edge_data.values():
                        if data.get('edge_type') == 'CITES':
                            relationships.append(f"Cites: {neighbor}")

        return relationships[:5]  # 최대 5개

    def _calculate_avg_similarity(self, selected_papers: List[Dict]) -> float:
        """평균 유사도 계산"""
        if len(selected_papers) < 2:
            return 0.0

        similarities = []
        for i, p1 in enumerate(selected_papers):
            for p2 in selected_papers[i+1:]:
                edge_data = self.graph.get_edge_data(p1['paper_id'], p2['paper_id'])
                if edge_data:
                    for data in edge_data.values():
                        if data.get('edge_type') == 'SIMILAR_TO':
                            similarities.append(data.get('weight', 0.0))

        return sum(similarities) / len(similarities) if similarities else 0.0

