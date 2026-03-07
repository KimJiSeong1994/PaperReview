"""
Graph RAG 응답 생성 모듈
"""
import os
import sys
from typing import Dict, Any

sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from .search_engine import SearchEngine
from .ranker import PaperRanker
from .context_builder import ContextBuilder
from .llm_client import LLMClient
from utils.logger import log_data_processing

class ResponseGenerator:
    """Graph RAG 응답 생성 클래스"""

    def __init__(self, graph, embeddings_index_path: str = None, id_mapping_path: str = None, llm_model: str = "gpt-4"):
        self.search_engine = SearchEngine(graph, embeddings_index_path, id_mapping_path)
        self.ranker = PaperRanker(graph)
        self.context_builder = ContextBuilder(graph)
        self.llm_client = LLMClient(model=llm_model)
        self.graph = graph

    @log_data_processing("Graph RAG Response Generation")
    def generate_response(
        self,
        query: str,
        top_k: int = 10,
        max_papers: int = 10,
        expansion_strategy: str = "hybrid",
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """전체 Graph RAG 파이프라인 실행"""
        # 1. 쿼리 임베딩 생성
        query_embedding = self.search_engine.generate_query_embedding(query, self.llm_client.client)
        if query_embedding is None:
            return {"error": "Failed to generate query embedding"}

        # 2. 초기 논문 검색
        initial_results = self.search_engine.vector_search(query_embedding, top_k=top_k)
        initial_papers = [r['paper_id'] for r in initial_results]

        # 3. 그래프 확장
        expanded_papers = self.search_engine.expand_graph(
            initial_papers,
            expansion_strategy=expansion_strategy
        )

        # 4. 랭킹 및 필터링
        ranked_papers = self.ranker.rank_papers(expanded_papers, query_embedding)
        selected_papers = ranked_papers[:max_papers]

        # 5. 컨텍스트 생성
        context = self.context_builder.create_context(selected_papers, query)

        # 6. LLM 응답 생성
        answer = self.llm_client.generate_response(context, query, temperature=temperature)

        # 7. 결과 반환
        return {
            "answer": answer,
            "source_papers": [
                {
                    "title": p['paper'].get('title', ''),
                    "relevance_score": p['score'],
                    "url": p['paper'].get('url', ''),
                    "authors": p['paper'].get('authors', [])
                }
                for p in selected_papers
            ],
            "graph_statistics": {
                "initial_papers": len(initial_papers),
                "expanded_papers": len(expanded_papers),
                "final_papers": len(selected_papers)
            },
            "query": query
        }

