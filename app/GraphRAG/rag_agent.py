import logging
logger = logging.getLogger(__name__)

"""
Graph RAG 통합 에이전트
기존 GraphRAG + LightRAG 이중 레벨 검색 통합
"""
import os
import json
import networkx as nx
from typing import Dict, List, Any

from src.graph.embedding_generator import EmbeddingGenerator
from src.graph.graph_builder import GraphBuilder
from src.graph_rag.response_generator import ResponseGenerator
from src.light_rag.kg_storage import KGStorage
from src.light_rag.kg_builder import KnowledgeGraphBuilder
from src.light_rag.entity_extractor import EntityExtractor
from src.light_rag.light_response_generator import LightResponseGenerator

class GraphRAGAgent:
    """Graph RAG 통합 에이전트 (기존 GraphRAG + LightRAG)"""

    def __init__(
        self,
        papers_json_path: str = "data/raw/papers.json",
        graph_path: str = "data/graph/paper_graph.pkl",
        embeddings_index_path: str = "data/embeddings/paper_embeddings.index",
        id_mapping_path: str = "data/embeddings/paper_id_mapping.json",
        light_rag_dir: str = "data/light_rag",
        llm_model: str = "gpt-4.1"
    ):
        self.papers_json_path = papers_json_path
        self.graph_path = graph_path
        self.embeddings_index_path = embeddings_index_path
        self.id_mapping_path = id_mapping_path
        self.light_rag_dir = light_rag_dir
        self.llm_model = llm_model

        self.graph = None
        self.response_generator = None

        # LightRAG components
        self.kg = None
        self.kg_storage = None
        self.light_response_generator = None

    def build_graph_from_papers(
        self,
        create_citation_edges: bool = True,
        create_similarity_edges: bool = True,
        similarity_threshold: float = 0.7,
        similarity_top_k: int = 10,
        batch_size: int = 100
    ) -> nx.MultiDiGraph:
        """논문 데이터로부터 그래프 구축"""
        logger.info("="*70)
        logger.info("[INFO] Graph RAG 그래프 구축 시작")
        logger.info("="*70)

        # 1. 논문 데이터 로드
        logger.info("\n[1/4] 논문 데이터 로드 중...")
        with open(self.papers_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        papers = data.get('papers', [])
        logger.info(f"  [v] {len(papers)}개 논문 로드 완료")

        # 2. 임베딩 생성
        logger.info("\n[2/4] 임베딩 생성 중...")
        embedding_generator = EmbeddingGenerator()
        embeddings = embedding_generator.generate_batch_embeddings(papers, batch_size=batch_size)
        logger.info(f"  [v] {len(embeddings)}개 임베딩 생성 완료")

        # 3. 임베딩 저장
        logger.info("\n[3/4] 임베딩 저장 중...")
        embedding_generator.save_embeddings(embeddings)

        # 4. 그래프 구축
        logger.info("\n[4/4] 그래프 구축 중...")
        graph_builder = GraphBuilder()
        graph = graph_builder.build_graph(
            papers,
            embeddings=embeddings,
            create_citation_edges=create_citation_edges,
            create_similarity_edges=create_similarity_edges,
            similarity_threshold=similarity_threshold,
            similarity_top_k=similarity_top_k
        )

        # 5. 그래프 저장
        graph_builder.save_graph(self.graph_path)

        self.graph = graph
        return graph

    def load_graph(self) -> nx.MultiDiGraph:
        """저장된 그래프 로드"""
        graph_builder = GraphBuilder()
        self.graph = graph_builder.load_graph(self.graph_path)
        return self.graph

    def initialize_response_generator(self):
        """응답 생성기 초기화"""
        if self.graph is None:
            if os.path.exists(self.graph_path):
                self.load_graph()
            else:
                raise FileNotFoundError(f"그래프 파일을 찾을 수 없습니다: {self.graph_path}")

        self.response_generator = ResponseGenerator(
            self.graph,
            self.embeddings_index_path,
            self.id_mapping_path,
            self.llm_model
        )

    def query(
        self,
        query: str,
        top_k: int = 10,
        max_papers: int = 10,
        expansion_strategy: str = "hybrid",
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """쿼리 실행"""
        if self.response_generator is None:
            self.initialize_response_generator()

        return self.response_generator.generate_response(
            query=query,
            top_k=top_k,
            max_papers=max_papers,
            expansion_strategy=expansion_strategy,
            temperature=temperature
        )

    # ─── LightRAG Methods ───

    def build_knowledge_graph(
        self,
        max_concurrent: int = 4,
        extraction_model: str = "gpt-4o-mini",
    ) -> nx.Graph:
        """LightRAG 지식 그래프 구축"""
        logger.info("=" * 70)
        logger.info("LightRAG Knowledge Graph Build")
        logger.info("=" * 70)

        # 논문 데이터 로드
        with open(self.papers_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        papers = data.get("papers", [])
        logger.info(f"Loaded {len(papers)} papers")

        # KG 구축
        storage = KGStorage(self.light_rag_dir)
        extractor = EntityExtractor(model=extraction_model)
        builder = KnowledgeGraphBuilder(storage=storage, storage_dir=self.light_rag_dir)

        self.kg = builder.build_from_papers(papers, extractor, max_concurrent)
        self.kg_storage = storage
        return self.kg

    def incremental_update_kg(
        self,
        new_papers: List[Dict[str, Any]],
        max_concurrent: int = 4,
    ) -> nx.Graph:
        """LightRAG 지식 그래프 증분 업데이트"""
        storage = KGStorage(self.light_rag_dir)
        builder = KnowledgeGraphBuilder(storage=storage, storage_dir=self.light_rag_dir)

        self.kg = builder.incremental_update(new_papers, max_concurrent=max_concurrent)
        self.kg_storage = storage
        return self.kg

    def initialize_light_response_generator(self):
        """LightRAG 응답 생성기 초기화"""
        if self.graph is None:
            if os.path.exists(self.graph_path):
                self.load_graph()

        # KG 로드
        storage = KGStorage(self.light_rag_dir)
        builder = KnowledgeGraphBuilder(storage=storage, storage_dir=self.light_rag_dir)
        self.kg = builder.load()
        self.kg_storage = storage

        self.light_response_generator = LightResponseGenerator(
            kg=self.kg,
            paper_graph=self.graph,
            storage=self.kg_storage,
            llm_model=self.llm_model,
            storage_dir=self.light_rag_dir,
        )

    def light_query(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """LightRAG 모드 쿼리"""
        if self.light_response_generator is None:
            self.initialize_light_response_generator()

        return self.light_response_generator.generate(
            query=query,
            mode=mode,
            top_k=top_k,
            temperature=temperature,
        )

    def get_kg_stats(self) -> Dict[str, Any]:
        """지식 그래프 통계 조회"""
        if self.kg is None:
            storage = KGStorage(self.light_rag_dir)
            builder = KnowledgeGraphBuilder(storage=storage, storage_dir=self.light_rag_dir)
            kg_path = os.path.join(self.light_rag_dir, "knowledge_graph.pkl")
            if os.path.exists(kg_path):
                self.kg = builder.load()
                self.kg_storage = storage
                return builder.get_stats()
            return {"error": "Knowledge graph not found. Run light-build first."}

        builder = KnowledgeGraphBuilder(storage=self.kg_storage, storage_dir=self.light_rag_dir)
        builder.kg = self.kg
        return builder.get_stats()

