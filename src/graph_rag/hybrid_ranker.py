"""
하이브리드 랭커: BM25 + Semantic + Citations + Recency
QueryAnalyzer의 intent에 따라 가중치를 자동 조절한다.
"""

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False

# ── Intent별 가중치 프리셋 ─────────────────────────────────────────

INTENT_WEIGHT_PRESETS: Dict[str, Dict[str, float]] = {
    "paper_search":      {"bm25": 0.35, "semantic": 0.35, "citations": 0.15, "recency": 0.15},
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


class HybridRanker:
    """BM25 + Dense + Citations + Recency 하이브리드 랭커"""

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
    ) -> List[Dict[str, Any]]:
        """
        논문 리스트를 하이브리드 점수로 랭킹.

        Args:
            query: 사용자 검색 쿼리
            papers: 랭킹할 논문 리스트
            intent: QueryAnalyzer가 판별한 검색 의도
            weights: 커스텀 가중치 (None이면 intent 프리셋 사용)
            top_k: 상위 K개만 반환 (None이면 전부)

        Returns:
            랭킹된 논문 리스트 (_hybrid_score, _score_breakdown 포함)
        """
        if not papers:
            return []

        w = dict(weights or INTENT_WEIGHT_PRESETS.get(intent, DEFAULT_WEIGHTS))

        # 개별 시그널 계산
        bm25_scores = self._compute_bm25_scores(query, papers)
        semantic_scores = self._compute_semantic_scores(query, papers)
        citation_scores = self._compute_citation_scores(papers)
        recency_scores = self._compute_recency_scores(papers)

        # Semantic fallback: 모든 semantic 점수가 0이면 가중치 재분배
        # BM25에 과도하게 집중하지 않도록 균등 분배
        if all(s == 0.0 for s in semantic_scores) and w.get("semantic", 0) > 0:
            semantic_weight = w["semantic"]
            w["bm25"] = w.get("bm25", 0) + semantic_weight * 0.5
            w["citations"] = w.get("citations", 0) + semantic_weight * 0.3
            w["recency"] = w.get("recency", 0) + semantic_weight * 0.2
            w["semantic"] = 0.0
            print("[HybridRanker] Semantic unavailable, redistributing weight: "
                  f"bm25={w['bm25']:.2f}, citations={w['citations']:.2f}, recency={w['recency']:.2f}")

        # 가중 합산 + 소스 부스트
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
            # 소스 부스트 적용 (arXiv 우선)
            source = paper.get("_source_tag") or paper.get("source", "")
            boost = SOURCE_BOOST.get(source, 0.0)
            if boost:
                hybrid += boost
                breakdown["source_boost"] = boost

            paper["_hybrid_score"] = round(hybrid, 4)
            paper["_score_breakdown"] = breakdown

        # 내림차순 정렬
        papers.sort(key=lambda p: p.get("_hybrid_score", 0), reverse=True)

        if top_k is not None:
            papers = papers[:top_k]

        return papers

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
            print(f"[HybridRanker] BM25 error, falling back to keyword: {e}")
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

    def _compute_semantic_scores(self, query: str, papers: List[Dict[str, Any]]) -> List[float]:
        """OpenAI embedding 코사인 유사도 (배치 API). calculator 없으면 0."""
        if not self.similarity_calculator:
            return [0.0] * len(papers)

        try:
            # 텍스트 준비: [query, paper1_text, paper2_text, ...]
            texts = [query]
            for p in papers:
                title = p.get("title", "")
                abstract = p.get("abstract", "")
                texts.append(f"{title}. {abstract}" if abstract else title)

            # 배치 임베딩 (get_embeddings_batch가 있으면 사용, 없으면 fallback)
            if hasattr(self.similarity_calculator, 'get_embeddings_batch'):
                embeddings = self.similarity_calculator.get_embeddings_batch(texts)
            else:
                # fallback: 순차 호출
                embeddings = [self.similarity_calculator._get_embedding(t[:8000]) for t in texts]

            query_emb = embeddings[0]
            if query_emb is None:
                return [0.0] * len(papers)

            scores = []
            for i in range(len(papers)):
                paper_emb = embeddings[i + 1]
                if paper_emb is not None:
                    sim = self.similarity_calculator._cosine_similarity(query_emb, paper_emb)
                    scores.append(max(0.0, sim))
                else:
                    scores.append(0.0)
            return scores
        except Exception as e:
            print(f"[HybridRanker] Semantic scoring error: {e}")
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
