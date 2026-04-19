"""
LLM 기반 검색 결과 관련성 필터 에이전트
사용자 질의와 검색된 논문의 관련성을 평가하여 필터링
"""
import os
import json
import logging
import concurrent.futures
import time
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


# 로거는 lazy import로 처리 (권한 오류 방지)
def log_data_processing(operation: str = None):
    """로거 데코레이터 (lazy import)"""
    try:
        from src.utils.logger import log_data_processing as _log_data_processing
        return _log_data_processing(operation)
    except (ImportError, OSError, PermissionError):
        # 로거 사용 불가 시 no-op 데코레이터 반환
        def noop_decorator(func):
            return func
        return noop_decorator

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None


class LocalRelevanceScorer:
    """로컬 cross-encoder 모델 기반 관련성 스코어러.

    sentence-transformers의 CrossEncoder를 사용하여
    LLM API 호출 없이 빠르게 관련성을 평가한다.
    """

    _instance = None
    _model = None

    def __init__(self) -> None:
        pass

    @classmethod
    def get_model(cls):
        """Lazy initialization of cross-encoder model (singleton)."""
        if cls._model is None:
            try:
                from sentence_transformers import CrossEncoder  # type: ignore
                cls._model = CrossEncoder(
                    "cross-encoder/ms-marco-MiniLM-L-6-v2",  # 22MB, fast
                    max_length=512,
                )
                logger.info("[LocalScorer] Cross-encoder model loaded successfully")
            except ImportError:
                logger.warning(
                    "[LocalScorer] sentence-transformers not installed, local scoring unavailable"
                )
                return None
            except Exception as e:
                logger.warning("[LocalScorer] Failed to load cross-encoder: %s", e)
                return None
        return cls._model

    @classmethod
    def is_available(cls) -> bool:
        """Check if local scoring is available."""
        try:
            from sentence_transformers import CrossEncoder  # noqa: F401  # type: ignore
            return True
        except ImportError:
            return False

    @classmethod
    def score_papers(cls, query: str, papers: List[Dict[str, Any]]) -> List[float]:
        """Score papers using local cross-encoder.

        Args:
            query: Search query
            papers: List of paper dicts with 'title' and optional 'abstract'

        Returns:
            List of relevance scores (0.0-1.0)
        """
        model = cls.get_model()
        if model is None:
            return []

        pairs = []
        for paper in papers:
            title = paper.get("title", "")
            abstract = (paper.get("abstract", "") or "")[:500]
            doc_text = f"{title}. {abstract}" if abstract else title
            pairs.append((query, doc_text))

        if not pairs:
            return []

        try:
            import numpy as np
            # batch_size=32: CPU 추론 시 기본값(1)보다 3-5배 빠름
            raw_scores = model.predict(pairs, batch_size=32, show_progress_bar=False)
            # Sigmoid normalization to 0-1 range
            scores = 1 / (1 + np.exp(-raw_scores))
            return scores.tolist()
        except Exception as e:
            logger.warning("[LocalScorer] Scoring failed: %s", e)
            return []


# Pre-load cross-encoder model at import time if env var set
if os.getenv("PRELOAD_CROSS_ENCODER", "").lower() in ("1", "true", "yes"):
    LocalRelevanceScorer.get_model()


class RelevanceFilter:
    """LLM 기반 검색 결과 관련성 필터"""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        RelevanceFilter 초기화

        Args:
            api_key: OpenAI API 키 (없으면 환경변수에서 로드)
            model: 사용할 LLM 모델 (기본값: gpt-4o-mini)
        """
        # SSL 검증은 api_server.py에서 전역으로 처리됨

        if not OPENAI_AVAILABLE:
            self.client = None
            self.api_key = None
            self.model = model
            return

        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            self.client = None
            self.model = model
            return

        self.client = OpenAI(api_key=self.api_key)
        self.model = model

    @log_data_processing("Relevance Filtering")
    def filter_papers(self, query: str, papers: List[Dict[str, Any]],
                     threshold: float = 0.6, max_papers: int = None, parallel: bool = True) -> List[Dict[str, Any]]:
        """
        검색된 논문들을 질의와의 관련성에 따라 필터링

        Args:
            query: 사용자 검색 쿼리
            papers: 검색된 논문 리스트
            threshold: 관련성 점수 임계값 (0.0 ~ 1.0)
            max_papers: 반환할 최대 논문 수
            parallel: 병렬 처리 여부 (기본 True)

        Returns:
            관련성 점수가 높은 논문 리스트 (관련성 점수 포함)
        """
        started = time.perf_counter()

        if not papers:
            return []

        # Client가 없으면 모든 논문을 그대로 반환 (필터링 없음)
        if not self.client:
            for paper in papers:
                paper['relevance_score'] = 0.8  # 기본 점수
            logger.info(
                "[RelevanceFilter] client unavailable; returning defaults for %d papers in %.2fs",
                len(papers),
                time.perf_counter() - started,
            )
            return papers[:max_papers] if max_papers else papers

        # Try local cross-encoder scoring first (fast, no API cost)
        local_scorer = LocalRelevanceScorer
        if local_scorer.is_available() and len(papers) > 0:
            try:
                local_scores = local_scorer.score_papers(query, papers)
                if local_scores and len(local_scores) == len(papers):
                    # Attach scores and filter
                    scored_papers = list(zip(papers, local_scores))
                    scored_papers.sort(key=lambda x: x[1], reverse=True)

                    # Apply threshold and limit
                    filtered = [
                        {**p, "relevance_score": round(s, 3)}
                        for p, s in scored_papers
                        if s >= threshold
                    ][:max_papers]

                    logger.info(
                        "[RelevanceFilter] Local cross-encoder: %d/%d papers passed (threshold=%.2f, took %.2fs)",
                        len(filtered), len(papers), threshold,
                        time.perf_counter() - started,
                    )
                    return filtered
            except Exception as e:
                logger.warning(
                    "[RelevanceFilter] Local scoring failed, falling back to LLM: %s", e
                )

        logger.info(f"[관련성 필터] {len(papers)}개 논문 평가 시작... (병렬: {parallel}, mode=llm_batch)")

        # 배치로 처리 (한 번에 10개씩)
        batch_size = 10
        batches = [papers[i:i+batch_size] for i in range(0, len(papers), batch_size)]

        if parallel and len(batches) > 1:
            # 병렬 처리 (배치 순서 보존)
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(batches))) as executor:
                future_to_idx = {}
                for i, batch in enumerate(batches):
                    future = executor.submit(self._evaluate_batch, query, batch)
                    future_to_idx[future] = i

                all_results = [None] * len(batches)
                for future in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    all_results[idx] = future.result()

            # 결과 병합 (순서 보장)
            filtered_papers = []
            for batch, scores in zip(batches, all_results):
                if scores is None:
                    scores = [0.0] * len(batch)
                for paper, score in zip(batch, scores):
                    if score >= threshold:
                        paper['relevance_score'] = score
                        filtered_papers.append(paper)
                        logger.info(f"  [v] [{score:.2f}] {paper.get('title', 'Untitled')[:60]}")
                    else:
                        logger.info(f"  [x] [{score:.2f}] {paper.get('title', 'Untitled')[:60]}")
        else:
            # 순차 처리
            filtered_papers = []
            for batch in batches:
                batch_results = self._evaluate_batch(query, batch)
                for paper, score in zip(batch, batch_results):
                    if score >= threshold:
                        paper['relevance_score'] = score
                        filtered_papers.append(paper)
                        logger.info(f"  [v] [{score:.2f}] {paper.get('title', 'Untitled')[:60]}")
                    else:
                        logger.info(f"  [x] [{score:.2f}] {paper.get('title', 'Untitled')[:60]}")

        # 관련성 점수 순으로 정렬
        filtered_papers.sort(key=lambda p: p['relevance_score'], reverse=True)

        # 최대 개수 제한
        if max_papers:
            filtered_papers = filtered_papers[:max_papers]

        logger.info(
            f"[관련성 필터] {len(filtered_papers)}/{len(papers)}개 논문 선택 (임계값: {threshold}, took {time.perf_counter() - started:.2f}s)"
        )
        return filtered_papers

    def _evaluate_batch(self, query: str, papers: List[Dict[str, Any]]) -> List[float]:
        """배치 논문들의 관련성 평가"""
        try:
            # 평가 프롬프트 생성
            evaluation_prompt = self._create_evaluation_prompt(query, papers)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert academic research evaluator.
Your task is to evaluate the relevance between a user's research query and academic papers.
Rate each paper's relevance on a scale of 0.0 to 1.0, where:
- 1.0 = Highly relevant, directly addresses the query
- 0.7-0.9 = Very relevant, closely related to the query
- 0.5-0.6 = Moderately relevant, somewhat related
- 0.3-0.4 = Slightly relevant, tangentially related
- 0.0-0.2 = Not relevant, unrelated to the query

Consider:
- Topic match: Does the paper discuss the same research area?
- Problem match: Does it address similar problems or challenges?
- Method match: Does it use similar methods or approaches?
- Goal match: Does it have similar research goals?"""
                    },
                    {
                        "role": "user",
                        "content": evaluation_prompt
                    }
                ],
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content or "{}"
            evaluation = json.loads(result_text)

            # 점수 추출 및 검증
            scores = evaluation.get("scores", [])
            if len(scores) != len(papers):
                logger.warning(f"[WARNING] 평가 결과 개수 불일치: {len(scores)} vs {len(papers)}")
                return [0.5] * len(papers)  # 기본값 반환

            return [float(s) for s in scores]

        except Exception as e:
            logger.error(f"[WARNING] 관련성 평가 중 오류: {e}")
            # 폴백: 간단한 키워드 매칭으로 점수 계산
            return [self._fallback_score(query, paper) for paper in papers]

    def _create_evaluation_prompt(self, query: str, papers: List[Dict[str, Any]]) -> str:
        """평가 프롬프트 생성"""
        papers_info = []
        for idx, paper in enumerate(papers):
            title = paper.get('title', 'Untitled')
            abstract = paper.get('abstract', '')[:500]  # 최대 500자

            papers_info.append(f"""Paper {idx + 1}:
Title: {title}
Abstract: {abstract if abstract else "No abstract available"}""")

        papers_text = "\n\n".join(papers_info)

        return f"""User's research query: "{query}"

Evaluate the relevance of each paper to this query.

{papers_text}

Provide your evaluation in JSON format:
{{
    "scores": [0.0 to 1.0 for paper 1, 0.0 to 1.0 for paper 2, ...],
    "reasoning": ["brief reason for paper 1", "brief reason for paper 2", ...]
}}

Return only valid JSON, no additional text."""

    def _fallback_score(self, query: str, paper: Dict[str, Any]) -> float:
        """LLM 평가 실패 시 간단한 키워드 매칭으로 점수 계산"""
        query_lower = query.lower()
        title_lower = paper.get('title', '').lower()
        abstract_lower = paper.get('abstract', '').lower()

        # 키워드 추출 (단순화)
        import re
        query_words = set(re.findall(r'\b\w{4,}\b', query_lower))

        if not query_words:
            return 0.5

        # 제목과 초록에서 키워드 매칭
        title_matches = sum(1 for word in query_words if word in title_lower)
        abstract_matches = sum(1 for word in query_words if word in abstract_lower)

        # 점수 계산
        title_score = (title_matches / len(query_words)) * 0.7  # 제목 가중치 70%
        abstract_score = (abstract_matches / len(query_words)) * 0.3  # 초록 가중치 30%

        total_score = min(title_score + abstract_score, 1.0)
        return round(total_score, 2)

    def evaluate_single(self, query: str, paper: Dict[str, Any]) -> float:
        """
        단일 논문의 관련성 평가

        Args:
            query: 사용자 검색 쿼리
            paper: 평가할 논문

        Returns:
            관련성 점수 (0.0 ~ 1.0)
        """
        scores = self._evaluate_batch(query, [paper])
        return scores[0] if scores else 0.5

    def rank_papers(self, query: str, papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        논문들을 관련성 순으로 재정렬 (필터링 없이)

        Args:
            query: 사용자 검색 쿼리
            papers: 논문 리스트

        Returns:
            관련성 순으로 정렬된 논문 리스트 (관련성 점수 포함)
        """
        if not papers:
            return []

        logger.info(f"[관련성 순위] {len(papers)}개 논문 평가 시작...")

        # 배치로 처리
        batch_size = 10
        scored_papers = []

        for i in range(0, len(papers), batch_size):
            batch = papers[i:i+batch_size]
            batch_scores = self._evaluate_batch(query, batch)

            for paper, score in zip(batch, batch_scores):
                paper['relevance_score'] = score
                scored_papers.append(paper)

        # 관련성 점수 순으로 정렬
        scored_papers.sort(key=lambda p: p['relevance_score'], reverse=True)

        logger.info(f"[관련성 순위] 평가 완료 (평균: {sum(p['relevance_score'] for p in scored_papers)/len(scored_papers):.2f})")
        return scored_papers
