import logging
logger = logging.getLogger(__name__)

"""
Light Retriever - LightRAG 이중 레벨 검색 엔진

5가지 검색 모드를 지원:
- naive: 청크 벡터 검색 (기존 RAG)
- local: Low-level 엔티티 기반 검색 (구체적, 사실적)
- global: High-level 관계 기반 검색 (주제적, 종합적)
- hybrid: local + global 결합
- mix: hybrid + naive (지식 그래프 + 벡터 통합)
"""
import os
import numpy as np
import networkx as nx
from typing import Dict, List, Any, Optional, Set
from dotenv import load_dotenv

load_dotenv()

from .kg_storage import KGStorage

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class LightRetriever:
    """LightRAG 이중 레벨 검색"""

    MODES = ["naive", "local", "global", "hybrid", "mix"]

    def __init__(
        self,
        kg: nx.Graph,
        paper_graph: Optional[nx.MultiDiGraph],
        storage: KGStorage,
        embedding_model: str = "text-embedding-3-small",
    ):
        self.kg = kg
        self.paper_graph = paper_graph
        self.storage = storage
        self.embedding_model = embedding_model

        api_key = os.getenv("OPENAI_API_KEY")
        if OPENAI_AVAILABLE and api_key:
            self._openai_client = OpenAI(api_key=api_key)
        else:
            self._openai_client = None

    def retrieve(
        self,
        query: str,
        keywords: Dict[str, List[str]],
        mode: str = "hybrid",
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """통합 검색 인터페이스"""
        if mode not in self.MODES:
            mode = "hybrid"

        if mode == "naive":
            return self._naive_search(query, top_k)
        elif mode == "local":
            return self._local_search(keywords.get("low_level", []), top_k)
        elif mode == "global":
            return self._global_search(keywords.get("high_level", []), top_k)
        elif mode == "hybrid":
            local_result = self._local_search(keywords.get("low_level", []), top_k)
            global_result = self._global_search(keywords.get("high_level", []), top_k)
            return self._merge_results(local_result, global_result)
        elif mode == "mix":
            hybrid_result = self.retrieve(query, keywords, mode="hybrid", top_k=top_k)
            naive_result = self._naive_search(query, top_k)
            return self._merge_results(hybrid_result, naive_result)

        return {"entities": [], "relationships": [], "paper_ids": [], "chunks": []}

    def _local_search(
        self, low_level_keywords: List[str], top_k: int = 10
    ) -> Dict[str, Any]:
        """Low-level 검색: 키워드 → 엔티티 → 이웃 관계 → 논문"""
        matched_entities: List[Dict[str, Any]] = []
        matched_relations: List[Dict[str, Any]] = []
        paper_ids: Set[str] = set()

        # 1. 키워드로 엔티티 벡터 검색
        entity_matches = self._search_entities_by_keywords(low_level_keywords, top_k)

        for entity_name, score in entity_matches:
            entity_data = self.storage.get_entity(entity_name)
            if not entity_data:
                continue

            matched_entities.append({
                **entity_data,
                "match_score": score,
            })

            # 출처 논문 수집
            paper_ids.update(entity_data.get("source_papers", []))

            # 2. 이 엔티티와 연결된 관계 수집
            neighbors = list(self.kg.neighbors(entity_name)) if self.kg.has_node(entity_name) else []
            for neighbor in neighbors[:5]:
                edge_data = self.kg.edges.get((entity_name, neighbor), {})
                if edge_data:
                    matched_relations.append({
                        "source": entity_name,
                        "target": neighbor,
                        "description": edge_data.get("description", ""),
                        "keywords": edge_data.get("keywords", []),
                    })
                    paper_ids.update(edge_data.get("source_papers", []))

                # 이웃 엔티티의 출처 논문도 수집
                neighbor_data = self.storage.get_entity(neighbor)
                if neighbor_data:
                    paper_ids.update(neighbor_data.get("source_papers", []))

        return {
            "entities": matched_entities[:top_k],
            "relationships": matched_relations[:top_k * 2],
            "paper_ids": list(paper_ids),
            "chunks": [],
            "mode": "local",
        }

    def _global_search(
        self, high_level_keywords: List[str], top_k: int = 10
    ) -> Dict[str, Any]:
        """High-level 검색: 키워드 → 관계 매칭 → 엔티티 그룹 → 논문"""
        matched_entities: List[Dict[str, Any]] = []
        matched_relations: List[Dict[str, Any]] = []
        paper_ids: Set[str] = set()
        seen_entities: Set[str] = set()

        # 1. 키워드로 관계 벡터 검색
        relation_matches = self._search_relations_by_keywords(high_level_keywords, top_k)

        for rel_key, score in relation_matches:
            rel_data = self.storage.relation_kv.get(rel_key)
            if not rel_data:
                continue

            matched_relations.append({
                **rel_data,
                "match_score": score,
            })

            paper_ids.update(rel_data.get("source_papers", []))

            # 2. 관계의 source/target 엔티티 수집
            source = rel_data.get("source", "")
            target = rel_data.get("target", "")

            for entity_name in [source, target]:
                normalized = KGStorage._normalize_key(entity_name)
                if normalized and normalized not in seen_entities:
                    seen_entities.add(normalized)
                    entity_data = self.storage.get_entity(entity_name)
                    if entity_data:
                        matched_entities.append(entity_data)
                        paper_ids.update(entity_data.get("source_papers", []))

        return {
            "entities": matched_entities[:top_k],
            "relationships": matched_relations[:top_k],
            "paper_ids": list(paper_ids),
            "chunks": [],
            "mode": "global",
        }

    def _naive_search(
        self, query: str, top_k: int = 10
    ) -> Dict[str, Any]:
        """Naive 검색: 청크 벡터 유사도 기반"""
        query_embedding = self._get_embedding(query)
        if query_embedding is None:
            return {"entities": [], "relationships": [], "paper_ids": [], "chunks": [], "mode": "naive"}

        chunk_matches = self.storage.search_chunks(query_embedding, top_k)

        chunks = []
        paper_ids: Set[str] = set()
        for chunk_id, score in chunk_matches:
            chunk_data = self.storage.chunk_kv.get(chunk_id)
            if chunk_data:
                chunks.append({
                    **chunk_data,
                    "chunk_id": chunk_id,
                    "match_score": score,
                })
                paper_ids.add(chunk_data.get("paper_id", ""))

        return {
            "entities": [],
            "relationships": [],
            "paper_ids": list(paper_ids),
            "chunks": chunks[:top_k],
            "mode": "naive",
        }

    def _search_entities_by_keywords(
        self, keywords: List[str], top_k: int = 10
    ) -> List[tuple]:
        """키워드로 엔티티 검색 (벡터 + 이름 매칭)"""
        results = {}

        # 1. 이름 기반 직접 매칭
        for keyword in keywords:
            normalized = KGStorage._normalize_key(keyword)
            if normalized in self.storage.entity_kv:
                results[normalized] = 1.0  # 정확 매칭은 최고 점수

            # 부분 매칭
            for entity_key in self.storage.entity_kv:
                if normalized in entity_key or entity_key in normalized:
                    if entity_key not in results:
                        results[entity_key] = 0.8

        # 2. 벡터 검색
        if keywords:
            combined_query = " ".join(keywords)
            query_embedding = self._get_embedding(combined_query)
            if query_embedding is not None:
                vector_matches = self.storage.search_entities(query_embedding, top_k * 2)
                for entity_key, score in vector_matches:
                    if entity_key not in results or score > results[entity_key]:
                        results[entity_key] = score

        # 점수순 정렬
        sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:top_k]

    def _search_relations_by_keywords(
        self, keywords: List[str], top_k: int = 10
    ) -> List[tuple]:
        """키워드로 관계 검색 (벡터 + 키워드 매칭)"""
        results = {}

        # 1. 키워드 기반 직접 매칭
        for keyword in keywords:
            normalized = keyword.strip().lower()
            for rel_key, rel_data in self.storage.relation_kv.items():
                rel_keywords = [k.lower() for k in rel_data.get("keywords", [])]
                if normalized in rel_keywords:
                    results[rel_key] = results.get(rel_key, 0) + 0.9
                # 설명에서도 매칭
                desc = rel_data.get("description", "").lower()
                if normalized in desc:
                    results[rel_key] = max(results.get(rel_key, 0), 0.7)

        # 2. 벡터 검색
        if keywords:
            combined_query = " ".join(keywords)
            query_embedding = self._get_embedding(combined_query)
            if query_embedding is not None:
                vector_matches = self.storage.search_relations(query_embedding, top_k * 2)
                for rel_key, score in vector_matches:
                    if rel_key not in results or score > results[rel_key]:
                        results[rel_key] = score

        sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:top_k]

    def _merge_results(self, *results_list) -> Dict[str, Any]:
        """여러 검색 결과 병합 및 중복 제거"""
        merged_entities = {}
        merged_relations = {}
        all_paper_ids: Set[str] = set()
        merged_chunks = {}

        for result in results_list:
            # 엔티티 병합
            for entity in result.get("entities", []):
                name = entity.get("name", "").lower()
                if name and (name not in merged_entities or
                             entity.get("match_score", 0) > merged_entities[name].get("match_score", 0)):
                    merged_entities[name] = entity

            # 관계 병합
            for rel in result.get("relationships", []):
                key = f"{rel.get('source', '')}||{rel.get('target', '')}"
                if key not in merged_relations:
                    merged_relations[key] = rel

            # 논문 ID 합산
            all_paper_ids.update(result.get("paper_ids", []))

            # 청크 병합
            for chunk in result.get("chunks", []):
                cid = chunk.get("chunk_id", "")
                if cid and cid not in merged_chunks:
                    merged_chunks[cid] = chunk

        return {
            "entities": sorted(
                merged_entities.values(),
                key=lambda x: x.get("match_score", 0),
                reverse=True,
            ),
            "relationships": list(merged_relations.values()),
            "paper_ids": list(all_paper_ids),
            "chunks": list(merged_chunks.values()),
            "mode": "merged",
        }

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """텍스트 임베딩 생성"""
        if not self._openai_client:
            return None
        try:
            response = self._openai_client.embeddings.create(
                model=self.embedding_model,
                input=text[:8000],
            )
            return np.array(response.data[0].embedding, dtype="float32")
        except Exception as e:
            logger.error(f"  Embedding error: {e}")
            return None
