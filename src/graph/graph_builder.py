"""
그래프 구축 모듈
"""
import os
import json
import sys
import networkx as nx
from typing import Dict, List, Any
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from .node_creator import NodeCreator
from .edge_creator import EdgeCreator
from utils.logger import log_data_processing

class GraphBuilder:
    """그래프 구축 클래스"""

    def __init__(self):
        self.node_creator = NodeCreator()
        self.edge_creator = EdgeCreator()
        self.graph = nx.MultiDiGraph()

    @log_data_processing("Graph Building")
    def build_graph(
        self,
        papers: List[Dict[str, Any]],
        embeddings: Dict[str, Any] = None,
        create_citation_edges: bool = True,
        create_similarity_edges: bool = True,
        similarity_threshold: float = 0.7,
        similarity_top_k: int = 10
    ) -> nx.MultiDiGraph:
        """전체 그래프 구축"""
        print(f"\n📊 그래프 구축 시작 (논문 수: {len(papers)})")

        # 1. 노드 생성
        print("\n[1/3] 노드 생성 중...")
        nodes = self.node_creator.create_nodes_batch(papers, embeddings)
        for node in nodes:
            self.graph.add_node(node['node_id'], **node)
        print(f"  ✓ {len(nodes)}개 노드 생성 완료")

        # 2. Citation 엣지 생성
        if create_citation_edges:
            print("\n[2/3] Citation 엣지 생성 중...")
            citation_edges = self.edge_creator.create_citation_edges(papers)
            for edge in citation_edges:
                self.graph.add_edge(
                    edge['source'],
                    edge['target'],
                    edge_type=edge['edge_type'],
                    weight=edge['weight'],
                    **edge.get('metadata', {})
                )
            print(f"  ✓ {len(citation_edges)}개 Citation 엣지 생성 완료")

        # 3. Similarity 엣지 생성
        if create_similarity_edges:
            print("\n[3/3] Similarity 엣지 생성 중...")
            similarity_edges = self.edge_creator.create_similarity_edges(
                nodes,
                similarity_threshold=similarity_threshold,
                top_k=similarity_top_k
            )
            for edge in similarity_edges:
                self.graph.add_edge(
                    edge['source'],
                    edge['target'],
                    edge_type=edge['edge_type'],
                    weight=edge['weight'],
                    **edge.get('metadata', {})
                )
            print(f"  ✓ {len(similarity_edges)}개 Similarity 엣지 생성 완료")

        # 그래프 통계
        self._print_graph_statistics()

        return self.graph

    def _print_graph_statistics(self):
        """그래프 통계 출력"""
        print("\n📈 그래프 통계:")
        print(f"  • 노드 수: {self.graph.number_of_nodes()}")
        print(f"  • 엣지 수: {self.graph.number_of_edges()}")

        # Citation 엣지 수
        citation_edges = sum(1 for _, _, data in self.graph.edges(data=True) if data.get('edge_type') == 'CITES')
        similarity_edges = sum(1 for _, _, data in self.graph.edges(data=True) if data.get('edge_type') == 'SIMILAR_TO')

        print(f"  • Citation 엣지: {citation_edges}개")
        print(f"  • Similarity 엣지: {similarity_edges}개")

        # 평균 degree
        if self.graph.number_of_nodes() > 0:
            avg_degree = sum(dict(self.graph.degree()).values()) / self.graph.number_of_nodes()
            print(f"  • 평균 degree: {avg_degree:.2f}")

    def save_graph(self, output_path: str = "data/graph/paper_graph.pkl"):
        """그래프를 파일로 저장"""
        import pickle

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, 'wb') as f:
            pickle.dump(self.graph, f)

        print(f"\n✓ 그래프 저장 완료: {output_path}")

        # 메타데이터 저장
        metadata = {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "created_at": datetime.now().isoformat()
        }

        metadata_path = output_path.replace('.pkl', '_metadata.json')
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    def load_graph(self, input_path: str = "data/graph/paper_graph.pkl") -> nx.MultiDiGraph:
        """저장된 그래프 로드"""
        import pickle

        with open(input_path, 'rb') as f:
            self.graph = pickle.load(f)

        print(f"✓ 그래프 로드 완료: {input_path}")
        self._print_graph_statistics()

        return self.graph

    def get_graph(self) -> nx.MultiDiGraph:
        """현재 그래프 반환"""
        return self.graph

