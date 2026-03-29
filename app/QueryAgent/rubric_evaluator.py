"""
Rubric-based Search Result Evaluator (RaR-Implicit)

ArxivQA의 RaR(Rubric-as-Reward) 방식으로 검색 결과 세트 전체를 평가.
개별 논문의 관련성이 아닌, 결과 세트의 다양성·포괄성·사려깊음·관련성을
4차원 rubric으로 평가하여 검색 품질을 판단한다.

Reference:
    ArxivQA RaR-Implicit (Rubric-as-Reward Implicit) — inference-time evaluation
    of search result sets using a holistic LLM rubric, decoupled from the
    per-paper length-penalty term λ(L) that is only used during training.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    AsyncOpenAI = None  # type: ignore[assignment,misc]


class RubricEvaluator:
    """ArxivQA RaR-Implicit 방식의 검색 결과 세트 루브릭 평가기.

    개별 논문의 관련성 점수(RelevanceFilter 담당)와 달리,
    이 클래스는 검색 결과 *전체*를 단일 평가 단위로 보고
    4차원 rubric(다양성·포괄성·사려깊음·관련성) 및 종합 점수를 산출한다.

    Attributes:
        INTENT_WEIGHTS: 검색 의도별 차원 가중치 (ArxivQA에서 도출).
        SUFFICIENCY_THRESHOLDS: 의도별 결과 충분성 임계값.
    """

    # Intent-weighted dimension weights (ArxivQA에서 도출)
    INTENT_WEIGHTS: Dict[str, Dict[str, float]] = {
        "paper_search": {
            "diversity": 0.2,
            "thoroughness": 0.2,
            "thoughtfulness": 0.2,
            "relevance": 0.4,
        },
        "topic_exploration": {
            "diversity": 0.3,
            "thoroughness": 0.3,
            "thoughtfulness": 0.2,
            "relevance": 0.2,
        },
        "survey": {
            "diversity": 0.2,
            "thoroughness": 0.4,
            "thoughtfulness": 0.2,
            "relevance": 0.2,
        },
        "latest_research": {
            "diversity": 0.1,
            "thoroughness": 0.1,
            "thoughtfulness": 0.3,
            "relevance": 0.5,
        },
        "method_search": {
            "diversity": 0.3,
            "thoroughness": 0.2,
            "thoughtfulness": 0.1,
            "relevance": 0.4,
        },
        "comparison": {
            "diversity": 0.4,
            "thoroughness": 0.2,
            "thoughtfulness": 0.2,
            "relevance": 0.2,
        },
    }

    # Sufficiency thresholds by intent
    SUFFICIENCY_THRESHOLDS: Dict[str, float] = {
        "paper_search": 0.55,
        "topic_exploration": 0.65,
        "survey": 0.70,
        "latest_research": 0.55,
        "method_search": 0.60,
        "comparison": 0.65,
        "default": 0.60,
    }

    def __init__(
        self,
        openai_client: Optional[Any] = None,
        model: str = "gpt-4o-mini",
        timeout: float = 15.0,
    ) -> None:
        """RubricEvaluator 초기화.

        Args:
            openai_client: 외부에서 주입하는 AsyncOpenAI 클라이언트.
                None이면 환경변수 OPENAI_API_KEY로 자체 생성을 시도한다.
                생성에 실패하거나 openai 패키지가 없으면 평가를 건너뛴다.
            model: LLM 모델 식별자. gpt-4o-mini 권장 (속도/비용 균형).
            timeout: LLM 호출 타임아웃(초). 기본 15.0.
        """
        self.model = model
        self.timeout = timeout

        if openai_client is not None:
            self.client: Optional[Any] = openai_client
            return

        if not OPENAI_AVAILABLE:
            self.client = None
            logger.warning(
                "[RubricEvaluator] openai 패키지가 설치되지 않아 루브릭 평가를 건너뜁니다."
            )
            return

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self.client = None
            logger.warning(
                "[RubricEvaluator] OPENAI_API_KEY가 없어 루브릭 평가를 건너뜁니다."
            )
            return

        self.client = AsyncOpenAI(api_key=api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        query: str,
        intent: str,
        papers: List[Dict[str, Any]],
        max_papers: int = 15,
    ) -> Dict[str, Any]:
        """결과 세트를 4차원 rubric으로 평가한다.

        LLM에 쿼리·의도·논문 목록을 제시하고,
        다양성(diversity), 포괄성(thoroughness), 사려깊음(thoughtfulness),
        관련성(relevance) 각 0-5점과 종합 홀리스틱 점수 1-10을 요청한다.

        Args:
            query: 사용자 검색 쿼리.
            intent: QueryAnalyzer가 분류한 검색 의도 문자열
                (e.g., "paper_search", "survey", "comparison").
            papers: 검색 결과 논문 리스트. 각 항목은 최소
                ``{"title": str, "abstract": str}`` 필드를 포함해야 한다.
            max_papers: 평가에 사용할 최대 논문 수 (비용·토큰 절약).
                초과분은 잘려나간다.

        Returns:
            다음 키를 가진 딕셔너리::

                {
                    "overall_score": float,          # 0.0-1.0 최종 점수
                    "dimensions": {
                        "diversity":      {"score": int (0-5), "feedback": str},
                        "thoroughness":   {"score": int (0-5), "feedback": str},
                        "thoughtfulness": {"score": int (0-5), "feedback": str},
                        "relevance":      {"score": int (0-5), "feedback": str},
                    },
                    "holistic_score": int,           # LLM 직접 종합 1-10
                    "is_sufficient": bool,
                    "weakest_dimension": str,
                    "missing_aspects": List[str],
                    "suggested_query": Optional[str],
                }

        Note:
            openai 클라이언트가 없거나 LLM 호출에 실패하면
            ``is_sufficient=True`` 인 기본 평가를 반환하여
            검색 파이프라인이 중단되지 않도록 한다.
        """
        if not papers:
            logger.debug("[RubricEvaluator] 논문 목록이 비어 있어 기본 평가를 반환합니다.")
            return self._default_evaluation(intent, is_sufficient=False)

        if self.client is None:
            logger.debug(
                "[RubricEvaluator] LLM 클라이언트 없음 — 루브릭 평가 건너뜀 (is_sufficient=True)."
            )
            return self._default_evaluation(intent, is_sufficient=True)

        # 평가 대상 논문 수 제한
        evaluation_papers = papers[:max_papers]

        try:
            raw = await self._call_llm(query, intent, evaluation_papers)
            evaluation = self._parse_llm_response(raw, intent)
        except Exception as exc:
            logger.warning(
                "[RubricEvaluator] LLM 호출 실패 (%s) — 기본 평가 반환.", exc
            )
            return self._default_evaluation(intent, is_sufficient=True)

        # 보완 쿼리 생성 (weakest_dimension 기반)
        evaluation["suggested_query"] = self.suggest_followup_query(
            evaluation, query, intent
        )

        logger.info(
            "[RubricEvaluator] 평가 완료: overall=%.3f, holistic=%d, sufficient=%s, weakest=%s",
            evaluation["overall_score"],
            evaluation["holistic_score"],
            evaluation["is_sufficient"],
            evaluation["weakest_dimension"],
        )
        return evaluation

    def suggest_followup_query(
        self,
        evaluation: Dict[str, Any],
        query: str,
        intent: str,
    ) -> Optional[str]:
        """weakest_dimension에 특화된 보완 쿼리를 생성한다.

        충분성 기준을 이미 충족했거나 weakest_dimension을 식별할 수 없는 경우
        None을 반환한다.

        Args:
            evaluation: :meth:`evaluate` 가 반환한 평가 딕셔너리.
            query: 원본 검색 쿼리.
            intent: 검색 의도 문자열.

        Returns:
            보완 쿼리 문자열 또는 None.
        """
        if evaluation.get("is_sufficient", True):
            return None

        weakest = evaluation.get("weakest_dimension", "")
        missing = evaluation.get("missing_aspects", [])
        missing_hint = f" {missing[0]}" if missing else ""

        strategies: Dict[str, str] = {
            "diversity": (
                f"{query} alternative methods approaches{missing_hint}"
            ),
            "thoroughness": (
                f"{query} survey overview{missing_hint}"
            ),
            "thoughtfulness": (
                f"{query} analysis implications limitations{missing_hint}"
            ),
            "relevance": (
                # relevance 부족 → 더 specific한 쿼리
                f'"{query}"{missing_hint}'
                if " " in query
                else f"{query} specific{missing_hint}"
            ),
        }

        suggested = strategies.get(weakest)
        if suggested:
            logger.debug(
                "[RubricEvaluator] 보완 쿼리 생성 (weakest=%s): %s", weakest, suggested
            )
        return suggested

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        query: str,
        intent: str,
        papers: List[Dict[str, Any]],
    ) -> str:
        """LLM에 루브릭 평가를 요청하고 원시 텍스트를 반환한다.

        Args:
            query: 사용자 검색 쿼리.
            intent: 검색 의도.
            papers: 평가 대상 논문 리스트 (이미 max_papers로 잘린 상태).

        Returns:
            LLM 응답 텍스트 (JSON 문자열이어야 함).

        Raises:
            Exception: API 호출 오류 또는 빈 응답.
        """
        prompt = self._build_prompt(query, intent, papers)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert academic search quality evaluator. "
                        "Evaluate the ENTIRE search result set — not individual papers — "
                        "using a 4-dimensional rubric. Return only valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=self.timeout,
        )

        content = response.choices[0].message.content
        if not content or not content.strip():
            raise ValueError("LLM이 빈 응답을 반환했습니다.")
        return content

    def _build_prompt(
        self,
        query: str,
        intent: str,
        papers: List[Dict[str, Any]],
    ) -> str:
        """루브릭 평가 프롬프트를 구성한다.

        Args:
            query: 사용자 검색 쿼리.
            intent: 검색 의도.
            papers: 평가 대상 논문 리스트.

        Returns:
            LLM user 메시지로 전달할 프롬프트 문자열.
        """
        # 논문 목록 (번호 + 제목 + 초록 앞 200자)
        paper_lines: List[str] = []
        for idx, paper in enumerate(papers, start=1):
            title = paper.get("title", "Untitled")
            abstract = (paper.get("abstract") or "")[:200]
            if abstract:
                paper_lines.append(f"{idx}. {title}\n   {abstract}...")
            else:
                paper_lines.append(f"{idx}. {title}")
        papers_text = "\n\n".join(paper_lines)

        return f"""Evaluate the following search result set for the given query and intent.

QUERY: "{query}"
INTENT: {intent}
TOTAL PAPERS: {len(papers)}

--- PAPERS ---
{papers_text}
--- END PAPERS ---

Score the ENTIRE result SET (not individual papers) on each dimension:

DIMENSION DEFINITIONS:
- diversity (0-5): Do the papers cover different sub-topics, methods, or perspectives?
  0=all papers cover the same narrow angle, 5=excellent spread across the topic space.
- thoroughness (0-5): Does the set cover the key aspects/subtopics expected for this query?
  0=major subtopics missing, 5=comprehensive coverage of the topic.
- thoughtfulness (0-5): Are the papers intellectually relevant (e.g., foundational, impactful,
  forward-looking)? 0=superficially related, 5=highly curated with clear intellectual value.
- relevance (0-5): Are the papers actually about the query topic?
  0=mostly off-topic, 5=all papers directly address the query.

HOLISTIC SCORE (1-10): Give an overall quality score for this result set as a whole,
following the ArxivQA RaR-Implicit rubric. This should reflect your overall impression,
not a simple average of the four dimensions.

Return a JSON object with this exact structure:
{{
    "dimensions": {{
        "diversity":      {{"score": <int 0-5>, "feedback": "<one sentence>"}},
        "thoroughness":   {{"score": <int 0-5>, "feedback": "<one sentence>"}},
        "thoughtfulness": {{"score": <int 0-5>, "feedback": "<one sentence>"}},
        "relevance":      {{"score": <int 0-5>, "feedback": "<one sentence>"}}
    }},
    "holistic_score": <int 1-10>,
    "missing_aspects": ["<aspect 1>", "<aspect 2>"],
    "suggested_followup": "<optional follow-up query or null>"
}}

Return only valid JSON. No explanation outside the JSON."""

    def _parse_llm_response(
        self,
        raw: str,
        intent: str,
    ) -> Dict[str, Any]:
        """LLM 응답 JSON을 파싱하고 최종 평가 딕셔너리를 구성한다.

        파싱에 실패하면 graceful degradation으로 기본 평가를 반환한다.

        Args:
            raw: LLM이 반환한 JSON 문자열.
            intent: 검색 의도 (가중치 및 임계값 조회용).

        Returns:
            :meth:`evaluate` 의 Returns 섹션과 동일한 구조의 딕셔너리.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "[RubricEvaluator] JSON 파싱 실패 (%s). 기본 평가 반환.", exc
            )
            return self._default_evaluation(intent, is_sufficient=True)

        # --- 차원 점수 추출 ---
        raw_dims: Dict[str, Any] = data.get("dimensions", {})
        dimensions: Dict[str, Dict[str, Any]] = {}
        dim_scores: Dict[str, int] = {}

        for dim in ("diversity", "thoroughness", "thoughtfulness", "relevance"):
            dim_data = raw_dims.get(dim, {})
            score = self._clamp_int(dim_data.get("score", 2), lo=0, hi=5)
            feedback = str(dim_data.get("feedback", "")).strip() or "No feedback provided."
            dimensions[dim] = {"score": score, "feedback": feedback}
            dim_scores[dim] = score

        # --- 홀리스틱 점수 ---
        holistic_raw = data.get("holistic_score", 5)
        holistic_score = self._clamp_int(holistic_raw, lo=1, hi=10)

        # --- ArxivQA RaR-Implicit 최종 점수 계산 ---
        # holistic을 [0, 1]로 정규화 (훈련 시 length-penalty λ(L)는 적용 안 함)
        holistic_normalized = (holistic_score - 1) / 9.0

        # 의도별 가중 차원 점수
        weights = self.INTENT_WEIGHTS.get(intent, self.INTENT_WEIGHTS["paper_search"])
        weighted_score = sum(
            (dim_scores[d] / 5.0) * weights[d]
            for d in ("diversity", "thoroughness", "thoughtfulness", "relevance")
        )

        # 최종: holistic 60% + weighted dimensions 40%
        overall_score = round(0.6 * holistic_normalized + 0.4 * weighted_score, 4)

        # --- 충분성 판정 ---
        threshold = self.SUFFICIENCY_THRESHOLDS.get(
            intent, self.SUFFICIENCY_THRESHOLDS["default"]
        )
        is_sufficient = overall_score >= threshold

        # --- 가장 취약한 차원 ---
        weakest_dim = min(dim_scores, key=lambda d: dim_scores[d])

        # --- 누락 측면 ---
        missing_aspects: List[str] = [
            str(a) for a in data.get("missing_aspects", []) if a
        ]

        return {
            "overall_score": overall_score,
            "dimensions": dimensions,
            "holistic_score": holistic_score,
            "is_sufficient": is_sufficient,
            "weakest_dimension": weakest_dim,
            "missing_aspects": missing_aspects,
            "suggested_query": None,  # evaluate()에서 채워짐
        }

    def _default_evaluation(
        self,
        intent: str,
        is_sufficient: bool,
    ) -> Dict[str, Any]:
        """LLM을 사용할 수 없거나 파싱에 실패했을 때 반환하는 기본 평가.

        검색 파이프라인이 루브릭 평가 실패로 중단되지 않도록
        항상 유효한 구조를 반환한다.

        Args:
            intent: 검색 의도 (로그 목적으로만 사용).
            is_sufficient: 강제로 설정할 충분성 값.

        Returns:
            :meth:`evaluate` 와 동일한 구조의 기본 딕셔너리.
        """
        logger.debug(
            "[RubricEvaluator] 기본 평가 반환 (intent=%s, is_sufficient=%s).",
            intent,
            is_sufficient,
        )
        default_dim = {"score": 3, "feedback": "Evaluation skipped — no LLM available."}
        return {
            "overall_score": 0.6,
            "dimensions": {
                "diversity": default_dim,
                "thoroughness": default_dim,
                "thoughtfulness": default_dim,
                "relevance": default_dim,
            },
            "holistic_score": 6,
            "is_sufficient": is_sufficient,
            "weakest_dimension": "relevance",
            "missing_aspects": [],
            "suggested_query": None,
        }

    @staticmethod
    def _clamp_int(value: Any, lo: int, hi: int) -> int:
        """값을 [lo, hi] 범위의 정수로 강제 변환한다.

        변환에 실패하면 lo와 hi의 중간값을 반환한다.

        Args:
            value: 변환할 값.
            lo: 허용 최솟값.
            hi: 허용 최댓값.

        Returns:
            [lo, hi] 범위 내 정수.
        """
        try:
            clamped = int(value)
        except (TypeError, ValueError):
            clamped = (lo + hi) // 2
        return max(lo, min(hi, clamped))
