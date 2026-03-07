"""
논문 랭킹 모듈
"""
import os
import sys
import numpy as np
import networkx as nx
from typing import Dict, List, Any
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))

class PaperRanker:
    """논문 랭킹 클래스"""

    def __init__(self, graph):
        self.graph = graph

    def get_pagerank(self, paper_id: str, pagerank_scores: Dict[str, float] = None) -> float:
        """PageRank 점수 가져오기"""
        if pagerank_scores is None:
            pagerank_scores = nx.pagerank(self.graph)
        return pagerank_scores.get(paper_id, 0.0)

    def normalize_citations(self, citations: int, max_citations: int = 1000) -> float:
        """인용 수 정규화"""
        return min(citations / max_citations, 1.0) if max_citations > 0 else 0.0

    def calculate_recency_score(self, published_date: str) -> float:
        """최신성 점수 계산"""
        if not published_date:
            return 0.5

        try:
            pub_year = int(published_date.split('-')[0])
            current_year = datetime.now().year
            age = current_year - pub_year

            # 최근 논문일수록 높은 점수
            if age <= 1:
                return 1.0
            elif age <= 3:
                return 0.8
            elif age <= 5:
                return 0.6
            elif age <= 10:
                return 0.4
            else:
                return 0.2
        except (ValueError, IndexError):
            return 0.5

    def rank_papers(
        self,
        paper_ids: List[str],
        query_embedding: np.ndarray,
        weights: Dict[str, float] = None
    ) -> List[Dict[str, Any]]:
        """논문 랭킹"""
        import networkx as nx

        weights = weights or {
            'query_similarity': 0.5,
            'pagerank': 0.2,
            'citations': 0.2,
            'recency': 0.1
        }

        # PageRank 계산
        pagerank_scores = nx.pagerank(self.graph)

        # 최대 인용 수 계산
        max_citations = max(
            (self.graph.nodes[node].get('citations', 0) for node in self.graph.nodes()),
            default=1000
        )

        scored_papers = []

        for paper_id in paper_ids:
            if paper_id not in self.graph:
                continue

            paper = self.graph.nodes[paper_id]
            paper_embedding = paper.get('embedding')

            # 1. 쿼리-논문 유사도
            if paper_embedding:
                query_sim = float(np.dot(query_embedding[0], np.array(paper_embedding)))
            else:
                query_sim = 0.0

            # 2. PageRank
            pagerank_score = pagerank_scores.get(paper_id, 0.0)

            # 3. 인용 수
            citations = paper.get('citations', 0)
            citation_score = self.normalize_citations(citations, max_citations)

            # 4. 최신성
            published_date = paper.get('published_date', '')
            recency_score = self.calculate_recency_score(published_date)

            # 종합 점수
            final_score = (
                weights['query_similarity'] * query_sim +
                weights['pagerank'] * pagerank_score +
                weights['citations'] * citation_score +
                weights['recency'] * recency_score
            )

            scored_papers.append({
                'paper_id': paper_id,
                'score': final_score,
                'paper': paper,
                'breakdown': {
                    'query_similarity': query_sim,
                    'pagerank': pagerank_score,
                    'citations': citation_score,
                    'recency': recency_score
                }
            })

        # 점수 순 정렬
        scored_papers.sort(key=lambda x: x['score'], reverse=True)

        return scored_papers

