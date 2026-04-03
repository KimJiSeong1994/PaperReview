"""
하이브리드 랭커: BM25 + Semantic + Citations + Recency
QueryAnalyzer의 intent에 따라 가중치를 자동 조절한다.

개선 사항:
- HyDE (Hypothetical Document Embedding) + Multi-Query 지원
- RRF (Reciprocal Rank Fusion) 지원
- Field-Weighted Semantic Scoring (title 0.6 + abstract 0.4)
- 기존 weighted-sum 방식은 fallback으로 유지
"""

import atexit
import hashlib
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False

logger = logging.getLogger(__name__)

# ── 모듈 레벨 HyDE 전용 ThreadPoolExecutor (재사용) ────────────────
_HYDE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hyde")
atexit.register(_HYDE_EXECUTOR.shutdown, wait=False)

# ── HyDE 임베딩 캐시 (TTL 24h, 최대 256 항목) ─────────────────────
_HYDE_CACHE: Dict[str, Tuple[np.ndarray, float]] = {}
_HYDE_CACHE_LOCK = threading.Lock()
_HYDE_CACHE_TTL = 86400  # 24 hours
_HYDE_CACHE_MAX = 256


def _hyde_cache_get(query: str) -> Optional[np.ndarray]:
    """TTL 기반 HyDE 임베딩 캐시 조회."""
    key = hashlib.sha256(query.encode("utf-8")).hexdigest()
    with _HYDE_CACHE_LOCK:
        entry = _HYDE_CACHE.get(key)
        if entry and (time.time() - entry[1]) < _HYDE_CACHE_TTL:
            return entry[0]
        if entry:
            del _HYDE_CACHE[key]
    return None


def _hyde_cache_set(query: str, embedding: np.ndarray) -> None:
    """HyDE 임베딩을 캐시에 저장. 최대 크기 초과 시 가장 오래된 항목 제거."""
    key = hashlib.sha256(query.encode("utf-8")).hexdigest()
    with _HYDE_CACHE_LOCK:
        if len(_HYDE_CACHE) >= _HYDE_CACHE_MAX:
            oldest_key = min(_HYDE_CACHE, key=lambda k: _HYDE_CACHE[k][1])
            del _HYDE_CACHE[oldest_key]
        _HYDE_CACHE[key] = (embedding, time.time())

# ── Intent별 가중치 프리셋 ─────────────────────────────────────────

INTENT_WEIGHT_PRESETS: Dict[str, Dict[str, float]] = {
    "paper_search":      {"bm25": 0.35, "semantic": 0.25, "citations": 0.25, "recency": 0.15},
    "latest_research":   {"bm25": 0.20, "semantic": 0.20, "citations": 0.10, "recency": 0.50},
    "survey":            {"bm25": 0.15, "semantic": 0.15, "citations": 0.40, "recency": 0.30},
    "method_search":     {"bm25": 0.30, "semantic": 0.50, "citations": 0.10, "recency": 0.10},
    "author_search":     {"bm25": 0.20, "semantic": 0.20, "citations": 0.30, "recency": 0.30},
    "topic_exploration": {"bm25": 0.25, "semantic": 0.30, "citations": 0.25, "recency": 0.20},
    "comparison":        {"bm25": 0.30, "semantic": 0.40, "citations": 0.20, "recency": 0.10},
    "problem_solving":   {"bm25": 0.25, "semantic": 0.35, "citations": 0.15, "recency": 0.25},
}

DEFAULT_WEIGHTS = INTENT_WEIGHT_PRESETS["paper_search"]

# ── 소스별 부스트 (arXiv 우선) ──────────────────────────────────────
SOURCE_BOOST: Dict[str, float] = {
    "arxiv": 0.15,
}

# ── RRF 상수 ──────────────────────────────────────────────────────
RRF_K = 60


class HybridRanker:
    """BM25 + Dense + Citations + Recency 하이브리드 랭커

    지원 모드:
    - use_rrf=True (기본): RRF (Reciprocal Rank Fusion) 점수로 최종 정렬
    - use_rrf=False (fallback): 기존 weighted-sum 방식
    - openai_client 제공 시: HyDE + Multi-Query로 semantic 품질 향상
    """

    def __init__(self, similarity_calculator=None):
        """
        Args:
            similarity_calculator: SimilarityCalculator 인스턴스 (semantic 점수용, 선택)
        """
        self.similarity_calculator = similarity_calculator

    # ── public API ────────────────────────────────────────────────────

    def rank_papers(
        self,
        query: str,
        papers: List[Dict[str, Any]],
        intent: str = "paper_search",
        weights: Optional[Dict[str, float]] = None,
        top_k: Optional[int] = None,
        openai_client=None,
        use_rrf: bool = True,
        research_area: str = "",
    ) -> List[Dict[str, Any]]:
        """
        논문 리스트를 하이브리드 점수로 랭킹.

        Args:
            query: 사용자 검색 쿼리
            papers: 랭킹할 논문 리스트
            intent: QueryAnalyzer가 판별한 검색 의도
            weights: 커스텀 가중치 (None이면 intent 프리셋 사용, use_rrf=False일 때만 의미 있음)
            top_k: 상위 K개만 반환 (None이면 전부)
            openai_client: OpenAI 클라이언트 (HyDE 활성화용, 선택)
            use_rrf: True면 RRF 방식, False면 weighted-sum 방식 (기존 동작)

        Returns:
            랭킹된 논문 리스트 (_hybrid_score, _score_breakdown 포함)
        """
        if not papers:
            return []

        if use_rrf:
            return self.rank_papers_rrf(
                query=query,
                papers=papers,
                intent=intent,
                top_k=top_k,
                openai_client=openai_client,
                research_area=research_area,
            )

        # ── Weighted-sum fallback (기존 동작 유지) ──────────────────
        w = dict(weights or INTENT_WEIGHT_PRESETS.get(intent, DEFAULT_WEIGHTS))

        bm25_scores = self._compute_bm25_scores(query, papers)
        semantic_scores = self._compute_semantic_scores(query, papers, openai_client=openai_client, research_area=research_area)
        citation_scores = self._compute_citation_scores(papers)
        recency_scores = self._compute_recency_scores(papers)

        # Semantic fallback: 모든 semantic 점수가 0이면 가중치 재분배
        if all(s == 0.0 for s in semantic_scores) and w.get("semantic", 0) > 0:
            semantic_weight = w["semantic"]
            w["bm25"] = w.get("bm25", 0) + semantic_weight * 0.5
            w["citations"] = w.get("citations", 0) + semantic_weight * 0.3
            w["recency"] = w.get("recency", 0) + semantic_weight * 0.2
            w["semantic"] = 0.0
            logger.info(
                "[HybridRanker] Semantic unavailable, redistributing weight: "
                "bm25=%.2f, citations=%.2f, recency=%.2f",
                w["bm25"], w["citations"], w["recency"],
            )

        for i, paper in enumerate(papers):
            breakdown = {
                "bm25": round(bm25_scores[i], 4),
                "semantic": round(semantic_scores[i], 4),
                "citations": round(citation_scores[i], 4),
                "recency": round(recency_scores[i], 4),
            }
            hybrid = (
                w["bm25"] * bm25_scores[i]
                + w["semantic"] * semantic_scores[i]
                + w["citations"] * citation_scores[i]
                + w["recency"] * recency_scores[i]
            )
            source = paper.get("_source_tag") or paper.get("source", "")
            boost = SOURCE_BOOST.get(source, 0.0)
            if boost:
                hybrid += boost
                breakdown["source_boost"] = boost

            paper["_hybrid_score"] = round(hybrid, 4)
            paper["_score_breakdown"] = breakdown

        papers.sort(key=lambda p: p.get("_hybrid_score", 0), reverse=True)

        if top_k is not None:
            papers = papers[:top_k]

        return papers

    def rank_papers_rrf(
        self,
        query: str,
        papers: List[Dict[str, Any]],
        intent: str = "paper_search",
        top_k: Optional[int] = None,
        openai_client=None,
        research_area: str = "",
    ) -> List[Dict[str, Any]]:
        """
        RRF (Reciprocal Rank Fusion) 방식으로 논문 랭킹.

        각 신호(BM25, Semantic, Citations, Recency)로 독립 정렬 후
        RRF 공식 score(d) = Σ 1/(k + rank_i(d)) 로 통합.
        마지막에 SOURCE_BOOST를 가산.

        Args:
            query: 사용자 검색 쿼리
            papers: 랭킹할 논문 리스트
            intent: QueryAnalyzer가 판별한 검색 의도 (현재 미사용, 향후 확장)
            top_k: 상위 K개만 반환 (None이면 전부)
            openai_client: OpenAI 클라이언트 (HyDE 활성화용, 선택)

        Returns:
            RRF 점수 기준으로 정렬된 논문 리스트 (_hybrid_score, _score_breakdown 포함)
        """
        if not papers:
            return []

        n = len(papers)

        bm25_scores = self._compute_bm25_scores(query, papers)
        semantic_scores = self._compute_semantic_scores(query, papers, openai_client=openai_client, research_area=research_area)
        citation_scores = self._compute_citation_scores(papers)
        recency_scores = self._compute_recency_scores(papers)

        # 각 신호별로 내림차순 순위 계산 (rank: 1-based)
        def _ranks_from_scores(scores: List[float]) -> List[int]:
            """점수 리스트를 받아 각 원소의 1-based 순위 반환 (높을수록 rank=1)."""
            indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            ranks = [0] * n
            for rank, (idx, _) in enumerate(indexed, start=1):
                ranks[idx] = rank
            return ranks

        bm25_ranks = _ranks_from_scores(bm25_scores)
        semantic_ranks = _ranks_from_scores(semantic_scores)
        citation_ranks = _ranks_from_scores(citation_scores)
        recency_ranks = _ranks_from_scores(recency_scores)

        # Cross-encoder (5번째 신호) — 미설치 시 빈 리스트 → RRF에서 제외
        cross_encoder_scores = self._compute_cross_encoder_scores(query, papers)
        cross_encoder_available = len(cross_encoder_scores) == n
        if cross_encoder_available:
            cross_encoder_ranks = _ranks_from_scores(cross_encoder_scores)
            logger.info("[HybridRanker] RRF: Cross-encoder signal active (%d papers)", n)
        else:
            cross_encoder_ranks = [0] * n
            logger.info("[HybridRanker] RRF: Cross-encoder unavailable, excluding from fusion")

        # semantic 전부 0이면 해당 신호 제외 (rank 기여 없음 처리)
        semantic_zero = all(s == 0.0 for s in semantic_scores)
        if semantic_zero:
            logger.info("[HybridRanker] RRF: Semantic unavailable, excluding from fusion")

        for i, paper in enumerate(papers):
            rrf_bm25 = 1.0 / (RRF_K + bm25_ranks[i])
            rrf_semantic = 0.0 if semantic_zero else 1.0 / (RRF_K + semantic_ranks[i])
            rrf_citations = 1.0 / (RRF_K + citation_ranks[i])
            rrf_recency = 1.0 / (RRF_K + recency_ranks[i])
            rrf_cross_encoder = (
                1.0 / (RRF_K + cross_encoder_ranks[i]) if cross_encoder_available else 0.0
            )

            rrf_score = rrf_bm25 + rrf_semantic + rrf_citations + rrf_recency + rrf_cross_encoder

            breakdown = {
                "bm25": round(bm25_scores[i], 4),
                "semantic": round(semantic_scores[i], 4),
                "citations": round(citation_scores[i], 4),
                "recency": round(recency_scores[i], 4),
                "cross_encoder": round(cross_encoder_scores[i], 4) if cross_encoder_available else 0.0,
                "rrf_bm25": round(rrf_bm25, 6),
                "rrf_semantic": round(rrf_semantic, 6),
                "rrf_citations": round(rrf_citations, 6),
                "rrf_recency": round(rrf_recency, 6),
                "rrf_cross_encoder": round(rrf_cross_encoder, 6),
                "rrf_mode": True,
            }

            # SOURCE_BOOST 적용 (arXiv 우선)
            source = paper.get("_source_tag") or paper.get("source", "")
            boost = SOURCE_BOOST.get(source, 0.0)
            if boost:
                rrf_score += boost
                breakdown["source_boost"] = boost

            paper["_hybrid_score"] = round(rrf_score, 6)
            paper["_score_breakdown"] = breakdown

        papers.sort(key=lambda p: p.get("_hybrid_score", 0), reverse=True)

        if top_k is not None:
            papers = papers[:top_k]

        return papers

    # ── Cross-encoder ──────────────────────────────────────────────

    def _compute_cross_encoder_scores(self, query: str, papers: List[Dict[str, Any]]) -> List[float]:
        """Cross-encoder 기반 relevance score. LocalRelevanceScorer 싱글턴 재사용."""
        try:
            from app.QueryAgent.relevance_filter import LocalRelevanceScorer

            # 이미 paper dict에 스코어가 있으면 재사용 (중복 호출 방지)
            existing = [p.get("_cross_encoder_score") for p in papers]
            if all(s is not None for s in existing):
                logger.debug("[HybridRanker] Reusing existing cross-encoder scores")
                return [float(s) for s in existing]

            # score_papers 클래스 메서드 사용 (모델 로딩 + sigmoid 정규화 포함)
            scores = LocalRelevanceScorer.score_papers(query, papers)
            if not scores:
                return []

            # 결과를 paper dict에 캐싱
            for i, s in enumerate(scores):
                papers[i]["_cross_encoder_score"] = s

            return scores
        except Exception as e:
            logger.warning("[HybridRanker] Cross-encoder failed: %s", e)
            return []

    # ── BM25 (sparse) ────────────────────────────────────────────────

    def _compute_bm25_scores(self, query: str, papers: List[Dict[str, Any]]) -> List[float]:
        """BM25 점수 (0~1 정규화). 제목을 2회 반복해 가중."""
        if not BM25_AVAILABLE:
            return self._keyword_fallback(query, papers)

        try:
            corpus = []
            for p in papers:
                title = p.get("title", "")
                abstract = p.get("abstract", "")
                # 제목 2회 반복 → 제목 매칭에 더 높은 가중
                doc = f"{title} {title} {abstract}".lower().split()
                corpus.append(doc)

            if not corpus:
                return [0.0] * len(papers)

            bm25 = BM25Okapi(corpus)
            query_tokens = query.lower().split()
            raw_scores = bm25.get_scores(query_tokens)

            return self._min_max_normalize(raw_scores)
        except Exception as e:
            logger.warning("[HybridRanker] BM25 error, falling back to keyword: %s", e)
            return self._keyword_fallback(query, papers)

    def _keyword_fallback(self, query: str, papers: List[Dict[str, Any]]) -> List[float]:
        """BM25 불가 시 키워드 오버랩 점수"""
        query_tokens = set(query.lower().split())
        scores = []
        for p in papers:
            title_tokens = set(p.get("title", "").lower().split())
            abstract_tokens = set(p.get("abstract", "").lower().split())
            title_overlap = len(query_tokens & title_tokens)
            abstract_overlap = len(query_tokens & abstract_tokens)
            scores.append(title_overlap * 2 + abstract_overlap)
        return self._min_max_normalize(scores)

    # ── Semantic (dense) ─────────────────────────────────────────────

    def _generate_hyde_embedding(
        self,
        query: str,
        openai_client,
        research_area: str = "",
    ) -> Optional[np.ndarray]:
        """
        HyDE (Hypothetical Document Embedding) + Multi-Query 평균 임베딩 생성.

        1. gpt-4o-mini로 가상 초록(hypothetical abstract) 생성
        2. gpt-4o-mini로 대안 검색 쿼리 2개 생성
        3. [원본 쿼리, 가상 초록, 대안1, 대안2] 배치 임베딩
        4. L2-정규화 후 평균 반환

        Args:
            query: 원본 사용자 쿼리
            openai_client: OpenAI 클라이언트

        Returns:
            L2-정규화된 평균 임베딩 벡터, 실패 시 None
        """
        # 캐시 조회
        cached = _hyde_cache_get(query)
        if cached is not None:
            logger.debug("[HybridRanker] HyDE cache hit for query: %s", query[:50])
            return cached

        try:
            # 1 & 2. 가상 초록 + 대안 쿼리 생성을 병렬 실행 (독립적인 LLM 호출)
            def _generate_hypothetical_abstract() -> str:
                domain_spec = (
                    f"specializing in {research_area} research"
                    if research_area
                    else "across academic research domains"
                )
                hyde_response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"You are an expert scientific paper abstract generator {domain_spec}. "
                                "Given a research query, write a hypothetical abstract for a paper that would be the ideal search result. "
                                "Include: (1) the problem addressed, (2) the proposed method/approach name, "
                                "(3) key technical terms and acronyms used in the field, "
                                "(4) quantitative claims (e.g., 'achieves state-of-the-art on X benchmark'). "
                                "Use formal academic language. Output only the abstract text, no title or labels."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Research query: {query}\n\n"
                                "Write a hypothetical abstract (~150 words) that a highly relevant paper would have. "
                                "Focus on technical depth and domain-specific terminology."
                            ),
                        },
                    ],
                    max_tokens=200,
                    temperature=0.1,
                )
                content = hyde_response.choices[0].message.content or ""
                return content.strip()

            def _generate_alt_queries() -> List[str]:
                alt_response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Generate 2 alternative search queries for academic paper search. "
                                "Each query should rephrase the original from a different angle. "
                                "Output exactly 2 lines, one query per line, no numbering or labels."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Original query: {query}",
                        },
                    ],
                    max_tokens=100,
                    temperature=0.3,
                )
                alt_content = alt_response.choices[0].message.content or ""
                lines = [line.strip() for line in alt_content.strip().splitlines() if line.strip()]
                return lines[:2]  # 최대 2개

            abstract_future = _HYDE_EXECUTOR.submit(_generate_hypothetical_abstract)
            alt_future = _HYDE_EXECUTOR.submit(_generate_alt_queries)

            hypothetical_abstract = abstract_future.result(timeout=15)
            alt_queries = alt_future.result(timeout=15)

            # 3. 배치 임베딩: [원본 쿼리, 가상 초록] + 대안들
            texts_to_embed = [query]
            if hypothetical_abstract:
                texts_to_embed.append(hypothetical_abstract)
            texts_to_embed.extend(alt_queries)

            embed_response = openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=[t[:8000] for t in texts_to_embed],
            )
            vectors = [np.array(d.embedding) for d in embed_response.data]

            if not vectors:
                return None

            # 4. L2-정규화 후 평균
            normalized = []
            for v in vectors:
                norm = np.linalg.norm(v)
                if norm > 1e-9:
                    normalized.append(v / norm)

            if not normalized:
                return None

            avg = np.mean(np.stack(normalized), axis=0)
            final_norm = np.linalg.norm(avg)
            result = avg / final_norm if final_norm > 1e-9 else avg

            logger.debug(
                "[HybridRanker] HyDE embedding built from %d texts (query + %d alts + abstract)",
                len(texts_to_embed),
                len(alt_queries),
            )
            # 캐시에 저장
            _hyde_cache_set(query, result)
            return result

        except Exception as e:
            logger.warning("[HybridRanker] HyDE embedding failed, will fall back to raw query: %s", e)
            return None

    def _compute_semantic_scores(
        self,
        query: str,
        papers: List[Dict[str, Any]],
        openai_client=None,
        research_area: str = "",
    ) -> List[float]:
        """
        Field-Weighted Semantic 점수 (title 0.6 + abstract 0.4 코사인 유사도).

        HyDE 활성화 시 openai_client를 이용해 더 풍부한 쿼리 임베딩을 생성.
        SimilarityCalculator가 없으면 모두 0.0 반환.

        배치 임베딩 구성:
            [query, title_0, abstract_0, title_1, abstract_1, ...]

        Args:
            query: 검색 쿼리 (또는 HyDE 임베딩 소스)
            papers: 랭킹할 논문 리스트
            openai_client: HyDE 생성용 OpenAI 클라이언트 (선택)

        Returns:
            0~1 범위 semantic 점수 리스트
        """
        if not self.similarity_calculator:
            return [0.0] * len(papers)

        try:
            # HyDE 임베딩 시도 (openai_client 있을 때)
            hyde_query_emb: Optional[np.ndarray] = None
            if openai_client is not None:
                hyde_query_emb = self._generate_hyde_embedding(query, openai_client, research_area=research_area)
                if hyde_query_emb is not None:
                    logger.info("[HybridRanker] HyDE embedding active for semantic scoring")

            # 배치 텍스트 구성: [query, title_0, abstract_0, title_1, abstract_1, ...]
            texts: List[str] = [query]
            for p in papers:
                title = p.get("title", "") or ""
                abstract = p.get("abstract", "") or ""
                texts.append(title)
                texts.append(abstract if abstract else title)

            # 배치 임베딩
            if hasattr(self.similarity_calculator, "get_embeddings_batch"):
                embeddings = self.similarity_calculator.get_embeddings_batch(texts)
            else:
                embeddings = [
                    self.similarity_calculator._get_embedding(t[:8000]) for t in texts
                ]

            # 쿼리 임베딩 결정: HyDE 우선, 없으면 raw query 임베딩
            raw_query_emb = embeddings[0]
            if hyde_query_emb is not None:
                query_emb = hyde_query_emb
            elif raw_query_emb is not None:
                query_emb = raw_query_emb
            else:
                return [0.0] * len(papers)

            scores: List[float] = []
            for i in range(len(papers)):
                title_emb = embeddings[1 + i * 2]
                abstract_emb = embeddings[2 + i * 2]

                # title 유사도
                if title_emb is not None:
                    title_sim = self.similarity_calculator._cosine_similarity(query_emb, title_emb)
                    title_sim = max(0.0, title_sim)
                else:
                    title_sim = 0.0

                # abstract 유사도
                if abstract_emb is not None:
                    abstract_sim = self.similarity_calculator._cosine_similarity(query_emb, abstract_emb)
                    abstract_sim = max(0.0, abstract_sim)
                else:
                    abstract_sim = 0.0

                # Field-weighted combination
                weighted_sim = 0.6 * title_sim + 0.4 * abstract_sim
                scores.append(weighted_sim)

            return scores

        except Exception as e:
            logger.warning("[HybridRanker] Semantic scoring error: %s", e)
            return [0.0] * len(papers)

    # ── Citations ────────────────────────────────────────────────────

    @staticmethod
    def _compute_citation_scores(papers: List[Dict[str, Any]]) -> List[float]:
        """log 정규화 인용수: log(1+c) / log(1+max_c)"""
        raw = [max(0, int(p.get("citations", 0) or 0)) for p in papers]
        max_c = max(raw) if raw else 0
        if max_c == 0:
            return [0.0] * len(papers)
        log_max = math.log(1 + max_c)
        return [math.log(1 + c) / log_max for c in raw]

    # ── Recency ──────────────────────────────────────────────────────

    @staticmethod
    def _compute_recency_scores(papers: List[Dict[str, Any]]) -> List[float]:
        """연도 기반 최신성 점수: 1년→1.0, 3년→0.7, 5년→0.5, 10년→0.3, 그 이상→0.1"""
        current_year = datetime.now().year
        scores = []
        for p in papers:
            try:
                year = int(p.get("year", 0) or 0)
            except (ValueError, TypeError):
                year = 0
            if year == 0:
                scores.append(0.3)  # 연도 불명 → 중간값
                continue
            age = current_year - year
            if age < 0:
                scores.append(0.3)  # 미래 연도 (데이터 오류) → 중간값
            elif age <= 1:
                scores.append(1.0)
            elif age <= 3:
                scores.append(0.7)
            elif age <= 5:
                scores.append(0.5)
            elif age <= 10:
                scores.append(0.3)
            else:
                scores.append(0.1)
        return scores

    # ── 유틸 ─────────────────────────────────────────────────────────

    @staticmethod
    def _min_max_normalize(scores) -> List[float]:
        """0~1 정규화"""
        arr = np.array(scores, dtype=float)
        if arr.size == 0:
            return []
        mn, mx = float(arr.min()), float(arr.max())
        if mx - mn < 1e-9:
            return [1.0] * len(scores) if mx > 0 else [0.0] * len(scores)
        return ((arr - mn) / (mx - mn)).tolist()
