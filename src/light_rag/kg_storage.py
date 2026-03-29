import logging
logger = logging.getLogger(__name__)

"""
KG Storage - 지식 그래프 KV + Vector 통합 저장소

엔티티, 관계, 청크에 대한 Key-Value 저장과
FAISS 벡터 인덱스를 통합 관리한다.
"""
import os
import json
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
import importlib

faiss_spec = importlib.util.find_spec("faiss")
if faiss_spec is not None:
    faiss = importlib.import_module("faiss")
    FAISS_AVAILABLE = True
else:
    faiss = None
    FAISS_AVAILABLE = False


class KGStorage:
    """엔티티/관계/청크의 KV + Vector 통합 저장소"""

    def __init__(self, storage_dir: str = "data/light_rag"):
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

        # KV stores
        self.entity_kv: Dict[str, Dict[str, Any]] = {}
        self.relation_kv: Dict[str, Dict[str, Any]] = {}
        self.chunk_kv: Dict[str, Dict[str, Any]] = {}

        # Vector stores (FAISS)
        self.entity_index = None
        self.entity_id_mapping: List[str] = []
        self.relation_index = None
        self.relation_id_mapping: List[str] = []
        self.chunk_index = None
        self.chunk_id_mapping: List[str] = []

        self._embedding_dim: Optional[int] = None

    # ─── KV Operations ───

    def upsert_entity(self, name: str, data: Dict[str, Any]):
        """엔티티 추가/업데이트 (동일 이름이면 설명 병합)"""
        key = self._normalize_key(name)
        if key in self.entity_kv:
            existing = self.entity_kv[key]
            # 설명 병합
            existing_desc = existing.get("description", "")
            new_desc = data.get("description", "")
            if new_desc and new_desc not in existing_desc:
                existing["description"] = f"{existing_desc} {new_desc}".strip()
            # 출처 논문 병합
            existing_papers = set(existing.get("source_papers", []))
            existing_papers.update(data.get("source_papers", []))
            existing["source_papers"] = list(existing_papers)
            # 타입 유지 (기존 우선)
            if not existing.get("type") and data.get("type"):
                existing["type"] = data["type"]
        else:
            self.entity_kv[key] = {
                "name": name,
                "type": data.get("type", "Concept"),
                "description": data.get("description", ""),
                "source_papers": list(data.get("source_papers", [])),
            }

    def upsert_relation(self, source: str, target: str, data: Dict[str, Any]):
        """관계 추가/업데이트"""
        src_key = self._normalize_key(source)
        tgt_key = self._normalize_key(target)
        rel_key = f"{src_key}||{tgt_key}"

        if rel_key in self.relation_kv:
            existing = self.relation_kv[rel_key]
            existing_desc = existing.get("description", "")
            new_desc = data.get("description", "")
            if new_desc and new_desc not in existing_desc:
                existing["description"] = f"{existing_desc} {new_desc}".strip()
            existing_keywords = set(existing.get("keywords", []))
            existing_keywords.update(data.get("keywords", []))
            existing["keywords"] = list(existing_keywords)
            existing_papers = set(existing.get("source_papers", []))
            existing_papers.update(data.get("source_papers", []))
            existing["source_papers"] = list(existing_papers)
            existing["weight"] = existing.get("weight", 0) + 1
        else:
            self.relation_kv[rel_key] = {
                "source": source,
                "target": target,
                "description": data.get("description", ""),
                "keywords": list(data.get("keywords", [])),
                "source_papers": list(data.get("source_papers", [])),
                "weight": 1,
            }

    def upsert_chunk(self, chunk_id: str, data: Dict[str, Any]):
        """청크 추가/업데이트"""
        self.chunk_kv[chunk_id] = {
            "text": data.get("text", ""),
            "paper_id": data.get("paper_id", ""),
            "chunk_index": data.get("chunk_index", 0),
        }

    def get_entity(self, name: str) -> Optional[Dict[str, Any]]:
        """엔티티 조회"""
        return self.entity_kv.get(self._normalize_key(name))

    def get_relation(self, source: str, target: str) -> Optional[Dict[str, Any]]:
        """관계 조회"""
        key = f"{self._normalize_key(source)}||{self._normalize_key(target)}"
        return self.relation_kv.get(key)

    def get_entity_relations(self, entity_name: str) -> List[Dict[str, Any]]:
        """특정 엔티티와 연결된 모든 관계 조회"""
        key = self._normalize_key(entity_name)
        results = []
        for rel_key, rel_data in self.relation_kv.items():
            src, tgt = rel_key.split("||")
            if src == key or tgt == key:
                results.append(rel_data)
        return results

    # ─── Vector Operations ───

    def build_entity_index(self, embeddings: Dict[str, np.ndarray]):
        """엔티티 FAISS 인덱스 구축"""
        if not embeddings:
            return
        self.entity_id_mapping = list(embeddings.keys())
        vectors = np.array([embeddings[k] for k in self.entity_id_mapping]).astype("float32")
        self._embedding_dim = vectors.shape[1]

        if FAISS_AVAILABLE:
            self.entity_index = faiss.IndexFlatIP(self._embedding_dim)
            faiss.normalize_L2(vectors)
            self.entity_index.add(vectors)
        else:
            self.entity_index = vectors

    def build_relation_index(self, embeddings: Dict[str, np.ndarray]):
        """관계 FAISS 인덱스 구축"""
        if not embeddings:
            return
        self.relation_id_mapping = list(embeddings.keys())
        vectors = np.array([embeddings[k] for k in self.relation_id_mapping]).astype("float32")
        dim = vectors.shape[1]

        if FAISS_AVAILABLE:
            self.relation_index = faiss.IndexFlatIP(dim)
            faiss.normalize_L2(vectors)
            self.relation_index.add(vectors)
        else:
            self.relation_index = vectors

    def build_chunk_index(self, embeddings: Dict[str, np.ndarray]):
        """청크 FAISS 인덱스 구축"""
        if not embeddings:
            return
        self.chunk_id_mapping = list(embeddings.keys())
        vectors = np.array([embeddings[k] for k in self.chunk_id_mapping]).astype("float32")
        dim = vectors.shape[1]

        if FAISS_AVAILABLE:
            self.chunk_index = faiss.IndexFlatIP(dim)
            faiss.normalize_L2(vectors)
            self.chunk_index.add(vectors)
        else:
            self.chunk_index = vectors

    def search_entities(self, query_embedding: np.ndarray, top_k: int = 10) -> List[Tuple[str, float]]:
        """엔티티 벡터 검색"""
        return self._vector_search(
            self.entity_index, self.entity_id_mapping, query_embedding, top_k
        )

    def search_relations(self, query_embedding: np.ndarray, top_k: int = 10) -> List[Tuple[str, float]]:
        """관계 벡터 검색"""
        return self._vector_search(
            self.relation_index, self.relation_id_mapping, query_embedding, top_k
        )

    def search_chunks(self, query_embedding: np.ndarray, top_k: int = 10) -> List[Tuple[str, float]]:
        """청크 벡터 검색"""
        return self._vector_search(
            self.chunk_index, self.chunk_id_mapping, query_embedding, top_k
        )

    def _vector_search(
        self, index, id_mapping: List[str], query_embedding: np.ndarray, top_k: int
    ) -> List[Tuple[str, float]]:
        """범용 벡터 검색"""
        if index is None or not id_mapping:
            return []

        query = query_embedding.astype("float32")
        if query.ndim == 1:
            query = query.reshape(1, -1)

        if FAISS_AVAILABLE and hasattr(index, "search"):
            norm = np.linalg.norm(query)
            if norm > 0:
                query = query / norm
            distances, indices = index.search(query, min(top_k, len(id_mapping)))
            results = []
            for i, idx in enumerate(indices[0]):
                if 0 <= idx < len(id_mapping):
                    results.append((id_mapping[idx], float(distances[0][i])))
            return results
        else:
            # numpy fallback
            vectors = index
            norm_q = np.linalg.norm(query)
            if norm_q > 0:
                query = query / norm_q
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            normalized = vectors / norms
            similarities = (normalized @ query.T).flatten()
            top_indices = np.argsort(similarities)[::-1][:top_k]
            return [(id_mapping[i], float(similarities[i])) for i in top_indices]

    # ─── Persistence ───

    def save(self):
        """전체 저장소 디스크 저장"""
        # KV stores
        self._save_json(self.entity_kv, "entity_kv.json")
        self._save_json(self.relation_kv, "relation_kv.json")
        self._save_json(self.chunk_kv, "chunk_kv.json")

        # Vector index mappings
        self._save_json(self.entity_id_mapping, "entity_id_mapping.json")
        self._save_json(self.relation_id_mapping, "relation_id_mapping.json")
        self._save_json(self.chunk_id_mapping, "chunk_id_mapping.json")

        # FAISS indices
        if FAISS_AVAILABLE:
            if self.entity_index is not None and hasattr(self.entity_index, "ntotal"):
                faiss.write_index(self.entity_index, os.path.join(self.storage_dir, "entity_embeddings.index"))
            if self.relation_index is not None and hasattr(self.relation_index, "ntotal"):
                faiss.write_index(self.relation_index, os.path.join(self.storage_dir, "relation_embeddings.index"))
            if self.chunk_index is not None and hasattr(self.chunk_index, "ntotal"):
                faiss.write_index(self.chunk_index, os.path.join(self.storage_dir, "chunk_embeddings.index"))
        else:
            # numpy fallback save
            if self.entity_index is not None and isinstance(self.entity_index, np.ndarray):
                np.save(os.path.join(self.storage_dir, "entity_embeddings.npy"), self.entity_index)
            if self.relation_index is not None and isinstance(self.relation_index, np.ndarray):
                np.save(os.path.join(self.storage_dir, "relation_embeddings.npy"), self.relation_index)
            if self.chunk_index is not None and isinstance(self.chunk_index, np.ndarray):
                np.save(os.path.join(self.storage_dir, "chunk_embeddings.npy"), self.chunk_index)

        logger.info(f"  KGStorage saved: {len(self.entity_kv)} entities, "
              f"{len(self.relation_kv)} relations, {len(self.chunk_kv)} chunks")

    def load(self):
        """전체 저장소 디스크 로드"""
        # KV stores
        self.entity_kv = self._load_json("entity_kv.json", {})
        self.relation_kv = self._load_json("relation_kv.json", {})
        self.chunk_kv = self._load_json("chunk_kv.json", {})

        # Vector index mappings
        self.entity_id_mapping = self._load_json("entity_id_mapping.json", [])
        self.relation_id_mapping = self._load_json("relation_id_mapping.json", [])
        self.chunk_id_mapping = self._load_json("chunk_id_mapping.json", [])

        # FAISS indices
        if FAISS_AVAILABLE:
            self.entity_index = self._load_faiss_index("entity_embeddings.index")
            self.relation_index = self._load_faiss_index("relation_embeddings.index")
            self.chunk_index = self._load_faiss_index("chunk_embeddings.index")
        else:
            self.entity_index = self._load_numpy("entity_embeddings.npy")
            self.relation_index = self._load_numpy("relation_embeddings.npy")
            self.chunk_index = self._load_numpy("chunk_embeddings.npy")

        logger.info(f"  KGStorage loaded: {len(self.entity_kv)} entities, "
              f"{len(self.relation_kv)} relations, {len(self.chunk_kv)} chunks")

    def _save_json(self, data, filename: str):
        path = os.path.join(self.storage_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_json(self, filename: str, default):
        path = os.path.join(self.storage_dir, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return default

    def _load_faiss_index(self, filename: str):
        path = os.path.join(self.storage_dir, filename)
        if os.path.exists(path):
            return faiss.read_index(path)
        return None

    def _load_numpy(self, filename: str):
        path = os.path.join(self.storage_dir, filename)
        if os.path.exists(path):
            return np.load(path)
        return None

    @staticmethod
    def _normalize_key(name: str) -> str:
        """엔티티/관계 키 정규화"""
        return name.strip().lower().replace("  ", " ")

    # ─── Stats ───

    def get_stats(self) -> Dict[str, Any]:
        """저장소 통계"""
        return {
            "entities": len(self.entity_kv),
            "relations": len(self.relation_kv),
            "chunks": len(self.chunk_kv),
            "entity_index_size": len(self.entity_id_mapping),
            "relation_index_size": len(self.relation_id_mapping),
            "chunk_index_size": len(self.chunk_id_mapping),
        }
