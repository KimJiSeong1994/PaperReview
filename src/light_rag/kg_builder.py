"""
Knowledge Graph Builder - 지식 그래프 구축 및 관리

논문에서 추출한 엔티티/관계를 NetworkX 그래프로 구축하고,
중복 제거, 임베딩 생성, 증분 업데이트를 처리한다.
"""
import os
import json
import pickle
import asyncio
import numpy as np
import networkx as nx
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

load_dotenv()

from .entity_extractor import EntityExtractor
from .kg_storage import KGStorage

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class KnowledgeGraphBuilder:
    """LightRAG 지식 그래프 구축 및 관리"""

    def __init__(
        self,
        storage: Optional[KGStorage] = None,
        storage_dir: str = "data/light_rag",
        embedding_model: str = "text-embedding-3-small",
    ):
        self.storage = storage or KGStorage(storage_dir)
        self.storage_dir = storage_dir
        self.kg = nx.Graph()
        self.embedding_model = embedding_model

        api_key = os.getenv("OPENAI_API_KEY")
        if OPENAI_AVAILABLE and api_key:
            import ssl
            try:
                ssl._create_default_https_context = ssl._create_unverified_context
            except AttributeError:
                pass
            self._openai_client = OpenAI(api_key=api_key)
        else:
            self._openai_client = None

    def build_from_papers(
        self,
        papers: List[Dict[str, Any]],
        extractor: Optional[EntityExtractor] = None,
        max_concurrent: int = 4,
    ) -> nx.Graph:
        """전체 논문 세트에서 지식 그래프 구축"""
        print("=" * 60)
        print("LightRAG Knowledge Graph Build")
        print("=" * 60)

        extractor = extractor or EntityExtractor()

        # 1. 엔티티/관계 추출
        print(f"\n[1/4] Extracting entities from {len(papers)} papers...")
        extraction_results = extractor.extract_batch_sync(papers, max_concurrent)

        total_entities = sum(len(r["entities"]) for r in extraction_results)
        total_relations = sum(len(r["relationships"]) for r in extraction_results)
        print(f"  Extracted: {total_entities} entities, {total_relations} relationships")

        # 2. 지식 그래프 구축
        print("\n[2/4] Building knowledge graph...")
        self._populate_graph(extraction_results)
        print(f"  Graph: {self.kg.number_of_nodes()} nodes, {self.kg.number_of_edges()} edges")

        # 3. 청크 생성 및 저장
        print("\n[3/4] Creating paper chunks...")
        self._create_chunks(papers)
        print(f"  Chunks: {len(self.storage.chunk_kv)}")

        # 4. 임베딩 생성 및 인덱스 구축
        print("\n[4/4] Generating embeddings and building indices...")
        self._build_embeddings()

        # 저장
        self.save()
        print(f"\nKnowledge graph build complete.")
        print(f"  Stats: {json.dumps(self.storage.get_stats(), indent=2)}")

        return self.kg

    def incremental_update(
        self,
        new_papers: List[Dict[str, Any]],
        extractor: Optional[EntityExtractor] = None,
        max_concurrent: int = 4,
    ) -> nx.Graph:
        """새 논문 증분 추가 (기존 그래프 유지)"""
        print(f"\nIncremental update: {len(new_papers)} new papers")

        extractor = extractor or EntityExtractor()

        # 기존 데이터 로드
        self.load()

        # 새 논문에서 추출
        extraction_results = extractor.extract_batch_sync(new_papers, max_concurrent)

        # 그래프에 추가 (중복은 자동 병합)
        self._populate_graph(extraction_results)

        # 새 청크 추가
        self._create_chunks(new_papers)

        # 임베딩 전체 재구축 (증분 FAISS는 복잡하므로 전체 재구축)
        self._build_embeddings()

        self.save()
        return self.kg

    def _populate_graph(self, extraction_results: List[Dict[str, Any]]):
        """추출 결과로 그래프 채우기"""
        for result in extraction_results:
            paper_id = result["paper_id"]

            # 엔티티 추가
            for entity in result.get("entities", []):
                name = entity.get("name", "").strip().lower()
                if not name:
                    continue

                entity_type = entity.get("type", "Concept")
                if entity_type not in EntityExtractor.ENTITY_TYPES:
                    entity_type = "Concept"

                # 그래프 노드 추가/업데이트
                if self.kg.has_node(name):
                    node = self.kg.nodes[name]
                    papers = set(node.get("source_papers", []))
                    papers.add(paper_id)
                    node["source_papers"] = list(papers)
                    # 설명 병합
                    existing_desc = node.get("description", "")
                    new_desc = entity.get("description", "")
                    if new_desc and new_desc not in existing_desc:
                        node["description"] = f"{existing_desc} {new_desc}".strip()
                else:
                    self.kg.add_node(
                        name,
                        type=entity_type,
                        description=entity.get("description", ""),
                        source_papers=[paper_id],
                    )

                # KV 저장소 업데이트
                self.storage.upsert_entity(name, {
                    "type": entity_type,
                    "description": entity.get("description", ""),
                    "source_papers": [paper_id],
                })

            # 관계 추가
            for rel in result.get("relationships", []):
                source = rel.get("source", "").strip().lower()
                target = rel.get("target", "").strip().lower()
                if not source or not target:
                    continue

                # 노드가 없으면 생성
                for node_name in [source, target]:
                    if not self.kg.has_node(node_name):
                        self.kg.add_node(
                            node_name,
                            type="Concept",
                            description="",
                            source_papers=[paper_id],
                        )

                # 엣지 추가/업데이트
                description = rel.get("relationship", "")
                keywords = rel.get("keywords", [])

                if self.kg.has_edge(source, target):
                    edge = self.kg.edges[source, target]
                    edge["weight"] = edge.get("weight", 1) + 1
                    existing_desc = edge.get("description", "")
                    if description and description not in existing_desc:
                        edge["description"] = f"{existing_desc} {description}".strip()
                    existing_kw = set(edge.get("keywords", []))
                    existing_kw.update(keywords)
                    edge["keywords"] = list(existing_kw)
                    papers = set(edge.get("source_papers", []))
                    papers.add(paper_id)
                    edge["source_papers"] = list(papers)
                else:
                    self.kg.add_edge(
                        source,
                        target,
                        description=description,
                        keywords=keywords,
                        source_papers=[paper_id],
                        weight=1,
                    )

                # KV 저장소 업데이트
                self.storage.upsert_relation(source, target, {
                    "description": description,
                    "keywords": keywords,
                    "source_papers": [paper_id],
                })

    def _create_chunks(self, papers: List[Dict[str, Any]]):
        """논문 텍스트를 청크로 분할하여 저장"""
        for paper in papers:
            paper_id = paper.get("title", "unknown")[:100].lower().strip().replace(" ", "_")
            text = self._get_paper_text(paper)
            chunks = EntityExtractor.chunk_text(text, chunk_size=1200, overlap=100)

            for i, chunk in enumerate(chunks):
                chunk_id = f"{paper_id}__chunk_{i}"
                self.storage.upsert_chunk(chunk_id, {
                    "text": chunk,
                    "paper_id": paper_id,
                    "chunk_index": i,
                })

    def _build_embeddings(self):
        """엔티티, 관계, 청크 임베딩 생성 및 인덱스 구축"""
        if not self._openai_client:
            print("  Warning: OpenAI client unavailable, skipping embedding generation")
            return

        # 엔티티 임베딩
        entity_texts = {}
        for key, data in self.storage.entity_kv.items():
            text = f"{data.get('name', key)}: {data.get('description', '')}"
            entity_texts[key] = text

        if entity_texts:
            entity_embeddings = self._batch_embed(entity_texts)
            self.storage.build_entity_index(entity_embeddings)
            print(f"  Entity index: {len(entity_embeddings)} vectors")

        # 관계 임베딩
        relation_texts = {}
        for key, data in self.storage.relation_kv.items():
            text = f"{data.get('source', '')} - {data.get('target', '')}: {data.get('description', '')} [{', '.join(data.get('keywords', []))}]"
            relation_texts[key] = text

        if relation_texts:
            relation_embeddings = self._batch_embed(relation_texts)
            self.storage.build_relation_index(relation_embeddings)
            print(f"  Relation index: {len(relation_embeddings)} vectors")

        # 청크 임베딩
        chunk_texts = {}
        for key, data in self.storage.chunk_kv.items():
            chunk_texts[key] = data.get("text", "")[:8000]

        if chunk_texts:
            chunk_embeddings = self._batch_embed(chunk_texts)
            self.storage.build_chunk_index(chunk_embeddings)
            print(f"  Chunk index: {len(chunk_embeddings)} vectors")

    def _batch_embed(
        self, texts: Dict[str, str], batch_size: int = 100
    ) -> Dict[str, np.ndarray]:
        """배치 임베딩 생성"""
        keys = list(texts.keys())
        all_texts = [texts[k][:8000] for k in keys]
        embeddings = {}

        for i in range(0, len(all_texts), batch_size):
            batch_keys = keys[i : i + batch_size]
            batch_texts = all_texts[i : i + batch_size]

            try:
                response = self._openai_client.embeddings.create(
                    model=self.embedding_model,
                    input=batch_texts,
                )
                for j, emb_data in enumerate(response.data):
                    embeddings[batch_keys[j]] = np.array(emb_data.embedding, dtype="float32")
            except Exception as e:
                print(f"  Embedding batch error: {e}")
                # 실패 시 0 벡터로 대체
                for k in batch_keys:
                    embeddings[k] = np.zeros(1536, dtype="float32")

        return embeddings

    @staticmethod
    def _get_paper_text(paper: Dict[str, Any]) -> str:
        """논문에서 텍스트 추출"""
        parts = []
        if paper.get("title"):
            parts.append(paper["title"])
        if paper.get("abstract"):
            parts.append(paper["abstract"])
        if paper.get("full_text"):
            parts.append(paper["full_text"][:5000])
        return "\n\n".join(parts)

    # ─── Persistence ───

    def save(self, path: Optional[str] = None):
        """지식 그래프 + 저장소 저장"""
        kg_path = path or os.path.join(self.storage_dir, "knowledge_graph.pkl")
        os.makedirs(os.path.dirname(kg_path), exist_ok=True)

        with open(kg_path, "wb") as f:
            pickle.dump(self.kg, f)

        self.storage.save()
        print(f"  Knowledge graph saved: {self.kg.number_of_nodes()} nodes, {self.kg.number_of_edges()} edges")

    def load(self, path: Optional[str] = None) -> nx.Graph:
        """지식 그래프 + 저장소 로드"""
        kg_path = path or os.path.join(self.storage_dir, "knowledge_graph.pkl")

        if os.path.exists(kg_path):
            with open(kg_path, "rb") as f:
                self.kg = pickle.load(f)
            print(f"  Knowledge graph loaded: {self.kg.number_of_nodes()} nodes, {self.kg.number_of_edges()} edges")
        else:
            print(f"  No existing knowledge graph found, starting fresh")
            self.kg = nx.Graph()

        self.storage.load()
        return self.kg

    def get_stats(self) -> Dict[str, Any]:
        """지식 그래프 통계"""
        stats = {
            "kg_nodes": self.kg.number_of_nodes(),
            "kg_edges": self.kg.number_of_edges(),
            "storage": self.storage.get_stats(),
        }

        # 엔티티 타입별 통계
        type_counts = {}
        for node in self.kg.nodes():
            etype = self.kg.nodes[node].get("type", "Unknown")
            type_counts[etype] = type_counts.get(etype, 0) + 1
        stats["entity_types"] = type_counts

        return stats
