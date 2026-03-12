import hashlib
import logging
import os
import sqlite3
import struct
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import sys
from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))
from utils.logger import log_data_processing

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "OpenAI package not installed. Please install with: pip install openai"
    )

logger = logging.getLogger(__name__)

# ── SQLite 캐시 경로 ──────────────────────────────────────────────
_DEFAULT_CACHE_DB = Path("data/cache/embeddings.db")
_L1_CACHE_MAX_SIZE = 512  # 인메모리 LRU 최대 항목 수


def _encode_embedding(arr: np.ndarray) -> bytes:
    """numpy float32 배열을 bytes로 직렬화 (BLOB 저장용)."""
    return struct.pack(f"{len(arr)}f", *arr.astype(np.float32).tolist())


def _decode_embedding(blob: bytes) -> np.ndarray:
    """bytes BLOB을 numpy float64 배열로 역직렬화."""
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float64)


class SimilarityCalculator:
    """LLM 기반 논문 유사도 계산 클래스

    캐시 구조:
    - L1: 인메모리 LRU dict (최대 _L1_CACHE_MAX_SIZE 항목)
    - L2: SQLite 영속 캐시 (data/cache/embeddings.db)
    - 해시: hashlib.sha256 (결정론적, 프로세스 재시작 무관)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
        cache_db_path: Optional[Path] = None,
    ):
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "OpenAI package is required. Install with: pip install openai"
            )

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key is required. "
                "Set OPENAI_API_KEY environment variable or pass api_key parameter."
            )

        self.client = OpenAI(api_key=self.api_key)
        self.model = model

        # L1 캐시: OrderedDict 기반 LRU (key: sha256 hex string)
        self._l1_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._cache_lock = threading.Lock()

        # L2 캐시: SQLite
        self._cache_db_path = Path(cache_db_path or _DEFAULT_CACHE_DB)
        self._db_lock = threading.Lock()
        self._init_sqlite_cache()

        # 하위 호환: 기존 코드가 .embedding_cache에 직접 접근하는 경우를 위한 프록시
        # (실제 데이터는 _l1_cache에 보관)
        self.embedding_cache = self._l1_cache

    # ── SQLite 초기화 ────────────────────────────────────────────────

    def _init_sqlite_cache(self) -> None:
        """SQLite DB 파일 및 테이블 초기화."""
        try:
            self._cache_db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._db_lock:
                conn = sqlite3.connect(str(self._cache_db_path), check_same_thread=False)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS embeddings (
                        text_hash TEXT PRIMARY KEY,
                        model     TEXT NOT NULL,
                        embedding BLOB NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.commit()
                conn.close()
            logger.info(
                "[SimilarityCalculator] SQLite embedding cache initialised: %s",
                self._cache_db_path,
            )
        except Exception as e:
            logger.warning(
                "[SimilarityCalculator] SQLite cache init failed (will use L1 only): %s", e
            )

    # ── 캐시 유틸 ────────────────────────────────────────────────────

    @staticmethod
    def _hash_text(text: str) -> str:
        """결정론적 sha256 해시 반환 (hex string)."""
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

    def _l1_get(self, text_hash: str) -> Optional[np.ndarray]:
        """L1(인메모리 LRU) 캐시에서 조회."""
        with self._cache_lock:
            if text_hash in self._l1_cache:
                # LRU: 최근 접근을 끝으로 이동
                self._l1_cache.move_to_end(text_hash)
                return self._l1_cache[text_hash]
        return None

    def _l1_set(self, text_hash: str, embedding: np.ndarray) -> None:
        """L1(인메모리 LRU) 캐시에 저장. 크기 초과 시 가장 오래된 항목 제거."""
        with self._cache_lock:
            if text_hash in self._l1_cache:
                self._l1_cache.move_to_end(text_hash)
            else:
                if len(self._l1_cache) >= _L1_CACHE_MAX_SIZE:
                    self._l1_cache.popitem(last=False)  # 가장 오래된 항목 제거
                self._l1_cache[text_hash] = embedding

    def _l2_get(self, text_hash: str) -> Optional[np.ndarray]:
        """L2(SQLite) 캐시에서 조회."""
        try:
            with self._db_lock:
                conn = sqlite3.connect(str(self._cache_db_path), check_same_thread=False)
                row = conn.execute(
                    "SELECT embedding FROM embeddings WHERE text_hash = ? AND model = ?",
                    (text_hash, self.model),
                ).fetchone()
                conn.close()
            if row:
                return _decode_embedding(row[0])
        except Exception as e:
            logger.debug("[SimilarityCalculator] L2 cache read error: %s", e)
        return None

    def _l2_set_batch(self, items: List[tuple]) -> None:
        """L2(SQLite) 캐시에 배치 저장.

        Args:
            items: [(text_hash, embedding), ...] 리스트
        """
        if not items:
            return
        try:
            now = time.time()
            rows = [
                (text_hash, self.model, _encode_embedding(emb), now)
                for text_hash, emb in items
            ]
            with self._db_lock:
                conn = sqlite3.connect(str(self._cache_db_path), check_same_thread=False)
                conn.executemany(
                    "INSERT OR REPLACE INTO embeddings (text_hash, model, embedding, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )
                conn.commit()
                conn.close()
        except Exception as e:
            logger.warning("[SimilarityCalculator] L2 batch write error: %s", e)

    def _get_from_cache(self, text_hash: str) -> Optional[np.ndarray]:
        """L1 → L2 순서로 캐시 조회. L2 히트 시 L1에 올림."""
        emb = self._l1_get(text_hash)
        if emb is not None:
            return emb
        emb = self._l2_get(text_hash)
        if emb is not None:
            self._l1_set(text_hash, emb)
        return emb

    # ── 논문 텍스트 추출 ─────────────────────────────────────────────

    def _get_paper_text(self, paper: Dict[str, Any]) -> str:
        """논문에서 유사도 계산에 사용할 텍스트 추출"""
        parts = [
            f"Title: {paper['title']}" if paper.get("title") else None,
            f"Abstract: {paper['abstract']}" if paper.get("abstract") else None,
            (
                f"Content: {(paper['full_text'][:2000] + '...' if len(paper.get('full_text', '')) > 2000 else paper.get('full_text', ''))}"
                if paper.get("full_text")
                else None
            ),
        ]
        return "\n\n".join([p for p in parts if p]) if any(parts) else ""

    # ── 단일 임베딩 ──────────────────────────────────────────────────

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """텍스트를 embedding으로 변환 (L1 → L2 캐시, 스레드 안전)."""
        if not text or not text.strip():
            return None

        text_hash = self._hash_text(text)

        cached = self._get_from_cache(text_hash)
        if cached is not None:
            return cached

        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text[:8000],
            )
            embedding = np.array(response.data[0].embedding)

            self._l1_set(text_hash, embedding)
            self._l2_set_batch([(text_hash, embedding)])
            return embedding

        except Exception as e:
            logger.warning("[SimilarityCalculator] Error generating embedding: %s", e)
            return None

    # ── 코사인 유사도 ────────────────────────────────────────────────

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Cosine similarity 계산"""
        if vec1 is None or vec2 is None:
            return 0.0
        norm1, norm2 = np.linalg.norm(vec1), np.linalg.norm(vec2)
        return (
            float(np.dot(vec1, vec2) / (norm1 * norm2))
            if norm1 > 0 and norm2 > 0
            else 0.0
        )

    # ── 유사도 계산 공개 API ──────────────────────────────────────────

    @log_data_processing("Similarity Calculation")
    def calculate_similarity(
        self, paper1: Dict[str, Any], paper2: Dict[str, Any]
    ) -> float:
        """두 논문 간의 유사도 계산"""
        text1, text2 = self._get_paper_text(paper1), self._get_paper_text(paper2)
        if not text1 or not text2:
            return 0.0
        embedding1, embedding2 = self._get_embedding(text1), self._get_embedding(text2)
        return (
            max(0.0, min(1.0, self._cosine_similarity(embedding1, embedding2)))
            if embedding1 is not None and embedding2 is not None
            else 0.0
        )

    def calculate_batch_similarities(
        self,
        main_paper: Dict[str, Any],
        reference_papers: List[Dict[str, Any]],
    ) -> List[float]:
        """메인 논문과 여러 참고문헌 논문 간의 유사도 일괄 계산"""
        main_embedding = self._get_embedding(self._get_paper_text(main_paper))
        if main_embedding is None:
            return [0.0] * len(reference_papers)

        similarities = []
        for ref in reference_papers:
            ref_embedding = self._get_embedding(self._get_paper_text(ref))
            if ref_embedding is not None:
                sim = self._cosine_similarity(main_embedding, ref_embedding)
                similarities.append(max(0.0, min(1.0, sim)))
            else:
                similarities.append(0.0)
        return similarities

    def add_similarity_scores(
        self,
        main_paper: Dict[str, Any],
        references: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """참고문헌에 유사도 점수 추가"""
        if not references:
            return references

        similarities = self.calculate_batch_similarities(main_paper, references)
        list(
            map(
                lambda x: x[1].update(
                    {
                        "similarity_score": round(x[0], 4),
                        "similarity_percentage": round(x[0] * 100, 2),
                    }
                ),
                zip(similarities, references),
            )
        )
        return references

    def get_embeddings_batch(
        self,
        texts: List[str],
        batch_size: int = 100,
    ) -> List[Optional[np.ndarray]]:
        """
        텍스트 리스트를 배치로 임베딩 변환 (L1 → L2 캐시 활용).

        미캐시 텍스트를 최대 batch_size=100씩 묶어 단일 API 호출.
        오류 발생 시 해당 배치는 None으로 채워 부분 결과 반환.

        Args:
            texts: 임베딩할 텍스트 리스트
            batch_size: API 호출당 최대 텍스트 수 (기본 100)

        Returns:
            임베딩 배열 리스트 (캐시 미스 + API 오류 시 해당 위치 None)
        """
        results: List[Optional[np.ndarray]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []
        uncached_hashes: List[str] = []

        # L1 → L2 캐시 확인
        for i, text in enumerate(texts):
            if not text or not text.strip():
                continue
            text_hash = self._hash_text(text)
            cached = self._get_from_cache(text_hash)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)
                uncached_texts.append(text[:8000])
                uncached_hashes.append(text_hash)

        if not uncached_texts:
            logger.debug(
                "[SimilarityCalculator] Batch: all %d texts served from cache", len(texts)
            )
            return results

        logger.debug(
            "[SimilarityCalculator] Batch: %d cache hits, %d API calls needed (batch_size=%d)",
            len(texts) - len(uncached_texts),
            len(uncached_texts),
            batch_size,
        )

        # 배치 API 호출: uncached_texts를 batch_size 단위로 나눠 처리
        for start in range(0, len(uncached_texts), batch_size):
            batch_texts = uncached_texts[start : start + batch_size]
            batch_indices = uncached_indices[start : start + batch_size]
            batch_hashes = uncached_hashes[start : start + batch_size]

            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch_texts,
                )
                new_cache_items: List[tuple] = []
                for j, emb_data in enumerate(response.data):
                    idx = batch_indices[j]
                    text_hash = batch_hashes[j]
                    embedding = np.array(emb_data.embedding)

                    results[idx] = embedding
                    self._l1_set(text_hash, embedding)
                    new_cache_items.append((text_hash, embedding))

                # L2 SQLite에 배치 저장
                self._l2_set_batch(new_cache_items)

                logger.debug(
                    "[SimilarityCalculator] Batch chunk [%d:%d] embedded and cached",
                    start,
                    start + len(batch_texts),
                )

            except Exception as e:
                logger.warning(
                    "[SimilarityCalculator] Batch embedding error for chunk [%d:%d]: %s",
                    start,
                    start + len(batch_texts),
                    e,
                )
                # 오류 발생 시 해당 배치는 None 유지 (부분 결과 반환)

        return results
