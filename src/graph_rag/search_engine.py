"""
Graph RAG 검색 엔진
"""
import os
import sys
import json
import numpy as np
from typing import Dict, List, Any, Optional
import importlib

faiss_spec = importlib.util.find_spec("faiss")
if faiss_spec is not None:
    faiss = importlib.import_module("faiss")
    FAISS_AVAILABLE = True
else:
    faiss = None  # type: ignore
    FAISS_AVAILABLE = False

sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from utils.logger import log_data_processing

class SearchEngine:
    """Graph RAG 검색 엔진"""
    
    def __init__(self, graph, embeddings_index_path: str = None, id_mapping_path: str = None):
        self.graph = graph
        self.index = None
        self.id_mapping = []
        
        if embeddings_index_path and id_mapping_path and FAISS_AVAILABLE:
            self.load_embeddings(embeddings_index_path, id_mapping_path)
        elif not FAISS_AVAILABLE:
            print("Warning: FAISS is not available. Vector search features are disabled.")
    
    def load_embeddings(self, index_path: str, mapping_path: str):
        """저장된 임베딩 인덱스 로드"""
        if not FAISS_AVAILABLE:
            print("FAISS is not available. Skipping embedding index load.")
            return

        try:
            self.index = faiss.read_index(index_path)
            with open(mapping_path, 'r', encoding='utf-8') as f:
                self.id_mapping = json.load(f)
            print(f"✓ 임베딩 인덱스 로드 완료: {len(self.id_mapping)}개")
        except Exception as e:
            print(f"임베딩 로드 실패: {e}")
    
    def generate_query_embedding(self, query: str, openai_client) -> Optional[np.ndarray]:
        """쿼리 임베딩 생성"""
        if not FAISS_AVAILABLE:
            # 기본 L2 정규화만 수행하여 numpy 배열 반환
            embedding = np.array(openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=query
            ).data[0].embedding).astype('float32')
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            return embedding.reshape(1, -1)

        try:
            response = openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=query
            )
            embedding = np.array(response.data[0].embedding).astype('float32')
            faiss.normalize_L2(embedding.reshape(1, -1))
            return embedding.reshape(1, -1)
        except Exception as e:
            print(f"쿼리 임베딩 생성 실패: {e}")
            return None
    
    @log_data_processing("Vector Search")
    def vector_search(self, query_embedding: np.ndarray, top_k: int = 10) -> List[Dict[str, Any]]:
        """벡터 유사도 기반 검색"""
        if not FAISS_AVAILABLE or self.index is None:
            return []
        
        distances, indices = self.index.search(query_embedding, top_k)
        
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.id_mapping):
                paper_id = self.id_mapping[idx]
                similarity = float(distances[0][i])
                results.append({
                    'paper_id': paper_id,
                    'similarity': similarity
                })
        
        return results
    
    def get_neighbors(self, paper_id: str, edge_type: str = None) -> List[str]:
        """그래프에서 인접 노드 가져오기"""
        if paper_id not in self.graph:
            return []
        
        neighbors = []
        for neighbor in self.graph.neighbors(paper_id):
            if edge_type:
                # 특정 엣지 타입만 필터링
                edge_data = self.graph.get_edge_data(paper_id, neighbor)
                if edge_data and any(data.get('edge_type') == edge_type for data in edge_data.values()):
                    neighbors.append(neighbor)
            else:
                neighbors.append(neighbor)
        
        return neighbors
    
    def get_cited_papers(self, paper_id: str) -> List[str]:
        """인용한 논문들 가져오기"""
        return self.get_neighbors(paper_id, edge_type='CITES')
    
    def get_citing_papers(self, paper_id: str) -> List[str]:
        """인용당한 논문들 가져오기"""
        if paper_id not in self.graph:
            return []
        
        citing = []
        for predecessor in self.graph.predecessors(paper_id):
            edge_data = self.graph.get_edge_data(predecessor, paper_id)
            if edge_data and any(data.get('edge_type') == 'CITES' for data in edge_data.values()):
                citing.append(predecessor)
        
        return citing
    
    def get_similar_papers(self, paper_id: str, top_k: int = 5) -> List[str]:
        """유사한 논문들 가져오기"""
        neighbors = self.get_neighbors(paper_id, edge_type='SIMILAR_TO')
        
        # 가중치로 정렬
        similar_with_weights = []
        for neighbor in neighbors:
            edge_data = self.graph.get_edge_data(paper_id, neighbor)
            if edge_data:
                max_weight = max(data.get('weight', 0.0) for data in edge_data.values())
                similar_with_weights.append((neighbor, max_weight))
        
        similar_with_weights.sort(key=lambda x: x[1], reverse=True)
        return [paper_id for paper_id, _ in similar_with_weights[:top_k]]
    
    @log_data_processing("Graph Expansion")
    def expand_graph(
        self,
        initial_papers: List[str],
        expansion_strategy: str = "hybrid",
        max_depth: int = 2
    ) -> List[str]:
        """그래프 확장"""
        expanded_papers = set(initial_papers)
        
        if expansion_strategy == "citation":
            for paper_id in initial_papers:
                expanded_papers.update(self.get_cited_papers(paper_id))
                expanded_papers.update(self.get_citing_papers(paper_id))
        
        elif expansion_strategy == "similarity":
            for paper_id in initial_papers:
                expanded_papers.update(self.get_similar_papers(paper_id, top_k=5))
        
        elif expansion_strategy == "hybrid":
            # 1-hop 확장
            for paper_id in list(initial_papers):
                expanded_papers.update(self.get_cited_papers(paper_id))
                expanded_papers.update(self.get_citing_papers(paper_id))
                expanded_papers.update(self.get_similar_papers(paper_id, top_k=5))
            
            # 2-hop 확장 (선택적)
            if max_depth >= 2:
                second_hop = set()
                for neighbor in list(expanded_papers):
                    second_hop.update(self.get_similar_papers(neighbor, top_k=3))
                expanded_papers.update(second_hop)
        
        return list(expanded_papers)
    
    def search(
        self,
        query: str,
        query_embedding: np.ndarray,
        openai_client,
        top_k: int = 10,
        expansion_strategy: str = "hybrid",
        max_expanded: int = 20
    ) -> List[str]:
        """통합 검색"""
        # 1. 벡터 검색
        initial_results = self.vector_search(query_embedding, top_k=top_k)
        initial_papers = [r['paper_id'] for r in initial_results]
        
        # 2. 그래프 확장
        expanded_papers = self.expand_graph(initial_papers, expansion_strategy=expansion_strategy)
        
        # 3. 확장된 논문 중 상위 선택
        if FAISS_AVAILABLE and self.index is not None and len(expanded_papers) > max_expanded:
            # 벡터 유사도로 재랭킹
            expanded_results = []
            for paper_id in expanded_papers:
                if paper_id in self.id_mapping:
                    idx = self.id_mapping.index(paper_id)
                    embedding = self.index.reconstruct(idx)
                    similarity = float(np.dot(query_embedding[0], embedding))
                    expanded_results.append((paper_id, similarity))
            
            expanded_results.sort(key=lambda x: x[1], reverse=True)
            expanded_papers = [pid for pid, _ in expanded_results[:max_expanded]]
        
        return expanded_papers

