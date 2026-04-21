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
import json
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


# ── Cross-encoder LRU+TTL 캐시 (TTL 1h, 최대 10k 항목) ─────────────
_CE_CACHE: Dict[Tuple[str, str], Tuple[float, float]] = {}
_CE_CACHE_LOCK = threading.Lock()
_CE_CACHE_TTL = 3600  # 1 hour
_CE_CACHE_MAX = 10_000


def _ce_query_hash(query: str) -> str:
    """쿼리 문자열을 안정적인 16자 해시로 변환."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def _ce_cache_get(query_hash: str, paper_id: str) -> Optional[float]:
    """Cross-encoder 점수 캐시 조회 (TTL 만료 시 None)."""
    key = (query_hash, paper_id)
    with _CE_CACHE_LOCK:
        entry = _CE_CACHE.get(key)
        if entry is None:
            return None
        score, ts = entry
        if time.time() - ts > _CE_CACHE_TTL:
            _CE_CACHE.pop(key, None)
            return None
        return score


def _ce_cache_set(query_hash: str, paper_id: str, score: float) -> None:
    """Cross-encoder 점수 캐시 저장. 상한 초과 시 오래된 10%를 일괄 제거."""
    key = (query_hash, paper_id)
    with _CE_CACHE_LOCK:
        if len(_CE_CACHE) >= _CE_CACHE_MAX:
            # Evict oldest 10% to amortize
            sorted_items = sorted(_CE_CACHE.items(), key=lambda kv: kv[1][1])
            evict_count = max(1, _CE_CACHE_MAX // 10)
            for k, _ in sorted_items[:evict_count]:
                _CE_CACHE.pop(k, None)
        _CE_CACHE[key] = (score, time.time())


def _ce_cache_clear() -> None:
    """테스트용: 전체 캐시 초기화."""
    with _CE_CACHE_LOCK:
        _CE_CACHE.clear()

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
# SOURCE_BOOST는 RRF 점수 범위(0.01~0.08)에 맞게 보정됨.
# 0.001 boost ≈ 최종 정렬에서 ~1 랭크 포지션 이동에 해당.
# US-013 이전 값(arxiv: 0.15)은 신호 합계를 압도해 arXiv 논문이
# 신호 품질과 무관하게 항상 top-K를 차지하는 문제를 유발했음.
SOURCE_BOOST: Dict[str, float] = {
    "arxiv": 0.003,  # was 0.15 — calibrated for RRF score range ~0.01-0.08
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
        """Cross-encoder 기반 relevance score. LocalRelevanceScorer 싱글턴 재사용.

        (query_hash, paper_id) 단위 TTL 1h LRU 캐시로 반복 호출 시 재계산을 회피.
        paper_id 부재 시 title 해시로 대체하여 캐시 키의 일관성을 확보한다.
        """
        try:
            from app.QueryAgent.relevance_filter import LocalRelevanceScorer

            # 이미 paper dict에 스코어가 있으면 재사용 (동일 호출 내 중복 방지)
            existing = [p.get("_cross_encoder_score") for p in papers]
            if all(s is not None for s in existing):
                logger.debug("[HybridRanker] Reusing existing cross-encoder scores")
                return [float(s) for s in existing]

            n = len(papers)
            if n == 0:
                return []

            # Stable query hash (16 chars) for cache key
            query_hash = _ce_query_hash(query)

            # Paper identifier fallback: paper_id → id → arxiv_id → doi → hash(title)
            def _paper_key(p: Dict[str, Any]) -> str:
                pid = (
                    p.get("paper_id")
                    or p.get("id")
                    or p.get("arxiv_id")
                    or p.get("doi")
                )
                if pid:
                    return str(pid)
                title = str(p.get("title", "") or "")
                return "t:" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]

            paper_keys = [_paper_key(p) for p in papers]

            # 1) Cache lookup
            scores: List[Optional[float]] = [None] * n
            miss_indices: List[int] = []
            for i, pk in enumerate(paper_keys):
                cached = _ce_cache_get(query_hash, pk)
                if cached is not None:
                    scores[i] = cached
                else:
                    miss_indices.append(i)

            hit_count = n - len(miss_indices)
            if hit_count:
                logger.info(
                    "[HybridRanker] Cross-encoder cache: %d/%d hits",
                    hit_count,
                    n,
                )

            # 2) Compute only misses through score_papers (batch_size=32 inside)
            if miss_indices:
                miss_papers = [papers[i] for i in miss_indices]
                fresh_scores = LocalRelevanceScorer.score_papers(query, miss_papers)
                if fresh_scores and len(fresh_scores) == len(miss_papers):
                    for local_idx, orig_idx in enumerate(miss_indices):
                        s = float(fresh_scores[local_idx])
                        scores[orig_idx] = s
                        _ce_cache_set(query_hash, paper_keys[orig_idx], s)
                else:
                    # 신규 점수 계산 실패 → 캐시 히트만으로는 부분 결과라 전체 스킵
                    logger.warning(
                        "[HybridRanker] Cross-encoder produced no scores for %d misses",
                        len(miss_indices),
                    )
                    return []

            # 3) Attach to paper dicts for downstream reuse (same call)
            final_scores: List[float] = []
            for i, s in enumerate(scores):
                if s is None:
                    return []
                papers[i]["_cross_encoder_score"] = s
                final_scores.append(s)

            return final_scores
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

    def _generate_hypothetical_abstract(
        self,
        query: str,
        openai_client,
        research_area: str = "",
    ) -> str:
        """HyDE fallback: 가상 초록만 단독 생성 (개별 LLM 호출)."""
        local_started = time.perf_counter()
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
        logger.info(
            "[HybridRanker] HyDE hypothetical abstract generated in %.2fs",
            time.perf_counter() - local_started,
        )
        return content.strip()

    def _generate_alt_queries(
        self,
        query: str,
        openai_client,
    ) -> List[str]:
        """HyDE fallback: 대안 검색 쿼리 2개만 단독 생성 (개별 LLM 호출)."""
        local_started = time.perf_counter()
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
        logger.info(
            "[HybridRanker] HyDE alternative queries generated in %.2fs",
            time.perf_counter() - local_started,
        )
        return lines[:2]  # 최대 2개

    def _generate_hyde_unified(
        self,
        query: str,
        openai_client,
        research_area: str = "",
    ) -> Tuple[str, List[str]]:
        """통합 HyDE 호출: 1회의 gpt-4o-mini JSON 응답으로 (abstract, alt_queries[2]) 획득.

        2 LLM calls → 1 LLM call 로 축소하여 HyDE 경로 지연을 절반으로 단축.
        JSON 파싱/응답 불완전 시 기존 개별 메서드로 graceful fallback.

        Args:
            query: 원본 사용자 쿼리
            openai_client: OpenAI 클라이언트
            research_area: 선택적 연구 분야 힌트

        Returns:
            (hypothetical_abstract, [alt_query_1, alt_query_2])
        """
        local_started = time.perf_counter()
        domain_spec = (
            f"specializing in {research_area} research"
            if research_area
            else "across academic research domains"
        )
        system_prompt = (
            f"You are an expert scientific paper abstract generator {domain_spec}. "
            "Given a research query, produce BOTH: "
            "(a) a hypothetical abstract (~150 words, formal academic language, "
            "covering the problem, proposed method/approach name, key technical terms, "
            "and quantitative claims), and "
            "(b) exactly 2 alternative search queries that rephrase the original from "
            "different angles. "
            "Respond with a single JSON object with keys "
            '"abstract" (string) and "alt_queries" (array of exactly 2 strings). '
            "Do not add any commentary."
        )
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Research query: {query}"},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=600,
                timeout=12.0,
            )
            content = response.choices[0].message.content or ""
            if not content.strip():
                raise ValueError("Empty HyDE unified response")

            data = json.loads(content)
            abstract = str(data.get("abstract", "") or "").strip()
            raw_alts = data.get("alt_queries") or []
            if not isinstance(raw_alts, list):
                raise ValueError("alt_queries must be a list")
            alt_queries = [str(q).strip() for q in raw_alts if str(q).strip()][:2]

            if not abstract or len(alt_queries) < 2:
                raise ValueError(
                    f"Incomplete HyDE response (abstract={bool(abstract)}, alts={len(alt_queries)})"
                )

            logger.info(
                "[HybridRanker] HyDE unified call generated abstract+%d alts in %.2fs",
                len(alt_queries),
                time.perf_counter() - local_started,
            )
            return abstract, alt_queries

        except Exception as e:
            logger.warning(
                "hyde_unified_fallback_triggered: unified HyDE call failed (%s); falling back to individual calls",
                e,
            )
            # Fallback: 기존 2회 LLM 호출 (병렬)
            try:
                abstract_future = _HYDE_EXECUTOR.submit(
                    self._generate_hypothetical_abstract,
                    query,
                    openai_client,
                    research_area,
                )
                alt_future = _HYDE_EXECUTOR.submit(
                    self._generate_alt_queries,
                    query,
                    openai_client,
                )
                fallback_abstract = abstract_future.result(timeout=15)
                fallback_alts = alt_future.result(timeout=15)
                return fallback_abstract, fallback_alts
            except Exception as inner:
                logger.warning(
                    "[HybridRanker] HyDE fallback individual calls also failed: %s",
                    inner,
                )
                return "", []

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

        started = time.perf_counter()
        try:
            # 1 & 2. 통합 HyDE 호출 (1 LLM call) — 실패 시 개별 호출로 fallback
            hypothetical_abstract, alt_queries = self._generate_hyde_unified(
                query=query,
                openai_client=openai_client,
                research_area=research_area,
            )

            # 3. 배치 임베딩: [원본 쿼리, 가상 초록] + 대안들
            texts_to_embed = [query]
            if hypothetical_abstract:
                texts_to_embed.append(hypothetical_abstract)
            texts_to_embed.extend(alt_queries)

            embed_started = time.perf_counter()
            # US-011 fix: SimilarityCalculator가 있으면 동일 파이프라인으로 임베딩
            # 생성해 논문 임베딩과 차원(dim)을 반드시 일치시킨다.
            # (과거 text-embedding-3-small 하드코딩 시 ko→large(3072)로 생성된
            #  논문 임베딩과 shape mismatch가 발생해 semantic 신호가 침묵 제외됨)
            vectors: List[np.ndarray]
            if self.similarity_calculator is not None and hasattr(
                self.similarity_calculator, "get_embeddings_batch"
            ):
                truncated = [t[:8000] for t in texts_to_embed]
                emb_batch = self.similarity_calculator.get_embeddings_batch(truncated)
                vectors = [np.asarray(v) for v in emb_batch if v is not None]
                logger.info(
                    "[HybridRanker] HyDE embedding batch created via SimilarityCalculator "
                    "in %.2fs from %d texts (%d vectors)",
                    time.perf_counter() - embed_started,
                    len(texts_to_embed),
                    len(vectors),
                )
            else:
                # Fallback: SimilarityCalculator 없으면 기존 경로 유지
                logger.warning(
                    "[HybridRanker] HyDE falling back to hardcoded text-embedding-3-small "
                    "(no SimilarityCalculator injected) — dim parity with paper embeddings NOT guaranteed"
                )
                embed_response = openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[t[:8000] for t in texts_to_embed],
                )
                logger.info(
                    "[HybridRanker] HyDE embedding batch created via openai_client "
                    "in %.2fs from %d texts (no SimilarityCalculator)",
                    time.perf_counter() - embed_started,
                    len(texts_to_embed),
                )
                vectors = [np.array(d.embedding) for d in embed_response.data]

            if not vectors:
                return None

            # Fix H-1: filter to query-dim group before stacking to avoid
            # mixed-dim crash when SimilarityCalculator dispatches different
            # models for Korean vs English texts in the same batch.
            query_dim = vectors[0].shape
            uniform = [v for v in vectors if v.shape == query_dim]
            if len(uniform) < len(vectors):
                logger.warning(
                    "[HybridRanker] HyDE batch produced mixed dims (%d texts → %d kept with query-dim %s); "
                    "likely mixed-language alts — keeping query-dim group only",
                    len(vectors),
                    len(uniform),
                    query_dim,
                )
            vectors = uniform
            if not vectors:
                logger.warning("[HybridRanker] HyDE: no vectors survived dim filter — aborting HyDE")
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
            logger.info(
                "[HybridRanker] HyDE embedding ready in %.2fs",
                time.perf_counter() - started,
            )
            # 캐시에 저장
            _hyde_cache_set(query, result)
            return result

        except Exception as e:
            logger.warning(
                "[HybridRanker] HyDE embedding failed after %.2fs, will fall back to raw query: %s",
                time.perf_counter() - started,
                e,
            )
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

            # US-011: query_emb 차원과 논문 임베딩 차원이 다르면 silent shape mismatch가
            # _cosine_similarity 내부 np.dot에서 ValueError를 일으킨다. 기존에는 이
            # ValueError가 외부 except로 흡수되어 전체 semantic 점수가 [0.0] * N으로
            # 되돌아가면서 RRF fusion에서 semantic 신호가 조용히 제외되었다.
            # → 이제는 논문 임베딩과 dim이 다를 경우 로그를 띄우고 해당 필드만 0.0으로
            #   처리해 다른 논문에는 신호가 유지되도록 한다.
            query_shape = getattr(query_emb, "shape", None)
            mismatch_logged = False

            def _safe_cosine(
                query_vec: np.ndarray,
                target_vec: Optional[np.ndarray],
            ) -> float:
                nonlocal mismatch_logged
                if target_vec is None:
                    return 0.0
                target_shape = getattr(target_vec, "shape", None)
                if query_shape is not None and target_shape != query_shape:
                    if not mismatch_logged:
                        logger.error(
                            "HyDE dim mismatch: hyde=%s paper=%s — semantic signal EXCLUDED for this query "
                            "(subsequent mismatches in same query suppressed)",
                            query_shape,
                            target_shape,
                        )
                        mismatch_logged = True
                    return 0.0
                sim = self.similarity_calculator._cosine_similarity(query_vec, target_vec)
                return max(0.0, sim)

            scores: List[float] = []
            for i in range(len(papers)):
                title_emb = embeddings[1 + i * 2]
                abstract_emb = embeddings[2 + i * 2]

                title_sim = _safe_cosine(query_emb, title_emb)
                abstract_sim = _safe_cosine(query_emb, abstract_emb)

                # Field-weighted combination
                weighted_sim = 0.6 * title_sim + 0.4 * abstract_sim
                scores.append(weighted_sim)

            return scores

        except Exception as e:
            logger.warning("[HybridRanker] Semantic scoring error: %s", e, exc_info=True)
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
